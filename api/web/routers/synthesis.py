"""Synthesis API endpoint for triggering synthetic test generation.

Provides POST /{prompt_id}/synthesize for starting a background
synthesis run. Progress is streamed via WebSocket at /ws/synthesis/{run_id}.

The synthesis pipeline uses SynthesisEngine from plan 33-02, which
simulates multi-turn conversations between persona agents (META model)
and the target prompt (TARGET model), scores them, and persists failing
conversations as new test cases.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from api.dataset.models import TestCase
from api.registry.tool_resolver import DEFAULT_MAX_TOOL_STEPS
from api.storage.models import User
from api.synthesis.models import SynthesisConfig
from api.web.auth import get_current_user
from api.web.deps import get_config, get_dataset_service, get_registry
from api.web.schemas import (
    ReviewRequest,
    ReviewResponse,
    SynthesizeRequest,
    SynthesizeResponse,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/{prompt_id}/synthesize", response_model=SynthesizeResponse)
async def start_synthesis(
    prompt_id: str,
    body: SynthesizeRequest,
    request: Request,
    config=Depends(get_config),
    registry=Depends(get_registry),
    dataset_service=Depends(get_dataset_service),
    user: User = Depends(get_current_user),
):
    """Start a synthesis run as a background task.

    Loads the prompt's personas, creates a SynthesisEngine, and launches
    conversation simulation as a background asyncio task. Progress events
    are published to the EventBus for WebSocket streaming.

    Args:
        prompt_id: Prompt to synthesize test cases for.
        body: Synthesis configuration (persona_ids, num_conversations, max_turns).
        request: FastAPI request for accessing app state.
        config: Application configuration.
        registry: Prompt registry for loading prompt data.
        dataset_service: Dataset service for persisting test cases.

    Returns:
        SynthesizeResponse with run_id and initial status.

    Raises:
        HTTPException: 400 if no personas defined for the prompt.
    """
    event_bus = request.app.state.event_bus

    # Initialize pending_reviews dict on app state if not present
    if getattr(request.app.state, "pending_reviews", None) is None:
        request.app.state.pending_reviews = {}

    # Load prompt record from DB (raises PromptNotFoundError -> 404 via exception handler)
    prompt_record = await registry.load_prompt(prompt_id, config)

    # Use existing personas or auto-generate defaults
    personas = prompt_record.personas or []
    if not personas:
        from api.synthesis.models import PersonaProfile

        personas = [
            PersonaProfile(
                id="confused-user",
                role="Confused user who misunderstands instructions",
                traits=["easily confused", "asks vague questions", "gives incomplete info"],
                communication_style="Rambling, unclear, mixes topics",
                goal="Get help despite providing unclear or contradictory information",
                edge_cases=["gives wrong input types", "changes topic mid-conversation"],
            ),
            PersonaProfile(
                id="adversarial-user",
                role="Adversarial user who tries to break the system",
                traits=["persistent", "creative", "boundary-testing"],
                communication_style="Direct, probing, tries unexpected inputs",
                goal="Find edge cases where the system fails or gives wrong answers",
                edge_cases=["requests outside scope", "provides malformed data"],
            ),
            PersonaProfile(
                id="impatient-user",
                role="Impatient user who wants quick answers",
                traits=["rushed", "skips details", "easily frustrated"],
                communication_style="Short messages, abbreviations, demands speed",
                goal="Complete the task as fast as possible with minimal interaction",
                edge_cases=["interrupts flow", "skips required steps"],
            ),
        ]
        logger.info(
            "No personas found for %s -- using 3 default adversarial personas", prompt_id
        )

    # Filter personas by request
    active_personas = personas
    if body.persona_ids is not None:
        active_personas = [p for p in personas if p.id in body.persona_ids]
        if not active_personas:
            raise HTTPException(
                status_code=400,
                detail="None of the requested persona_ids match defined personas.",
            )

    # Generate run_id and create EventBus run
    run_id = str(uuid.uuid4())
    event_bus.create_run(run_id)

    # Get template from DB-loaded record
    prompt_template = prompt_record.template or ""

    # Launch background synthesis task
    asyncio.create_task(
        _run_synthesis_background(
            run_id=run_id,
            prompt_id=prompt_id,
            prompt_template=prompt_template,
            personas=active_personas,
            tools=prompt_record.tools,
            mocks=prompt_record.mocks,
            config=config,
            dataset_service=dataset_service,
            event_bus=event_bus,
            num_conversations=body.num_conversations,
            max_turns=body.max_turns,
            persona_ids=body.persona_ids,
            scenario_context=body.scenario_context,
            purpose=prompt_record.purpose if hasattr(prompt_record, "purpose") else "",
            review_mode=body.review_mode,
            pending_reviews=request.app.state.pending_reviews,
        )
    )

    return SynthesizeResponse(
        run_id=run_id,
        status="started",
        total_personas=len(active_personas),
        num_conversations=body.num_conversations,
    )


async def _run_synthesis_background(
    *,
    run_id: str,
    prompt_id: str,
    prompt_template: str,
    personas: list,
    tools: list | None,
    mocks: list | None,
    config,
    dataset_service,
    event_bus,
    num_conversations: int,
    max_turns: int,
    persona_ids: list[str] | None,
    scenario_context: str | None = None,
    purpose: str = "",
    review_mode: bool = False,
    pending_reviews: dict | None = None,
) -> None:
    """Background coroutine that runs the synthesis pipeline.

    Creates providers, scorer, engine and runs synthesis. Publishes
    events to EventBus for WebSocket streaming. On completion or error,
    publishes terminal events and cleans up.
    """
    # Lazy imports to avoid circular imports and heavy startup
    from api.evaluation.scorers import BehaviorJudgeScorer
    from api.gateway.factory import create_provider
    from api.synthesis.engine import SynthesisEngine

    meta_provider = None
    target_provider = None
    judge_provider = None
    tool_mocker_provider = None

    try:
        logger.info("Synthesis background starting for %s (run=%s)", prompt_id, run_id)

        # Merge per-prompt config overrides from DB via registry
        from api.config.loader import load_prompt_config
        from api.storage.database import Database

        # Load per-prompt overrides from DB
        merged_config = config
        if config.database_url:
            db = Database(config.database_url)
            session = await db.get_session()
            try:
                from sqlalchemy import select as sa_select

                from api.storage.models import PromptConfig as PromptConfigModel

                pc_row = (
                    await session.execute(
                        sa_select(PromptConfigModel).where(
                            PromptConfigModel.prompt_id == prompt_id
                        )
                    )
                ).scalar_one_or_none()

                if pc_row:
                    overrides: dict = {}
                    if pc_row.provider:
                        overrides["meta_provider"] = pc_row.provider
                    if pc_row.model:
                        overrides["meta_model"] = pc_row.model
                    if pc_row.temperature is not None:
                        overrides["meta_temperature"] = pc_row.temperature
                    if pc_row.thinking_budget is not None:
                        overrides["meta_thinking_budget"] = pc_row.thinking_budget
                    if pc_row.extra:
                        overrides.update(pc_row.extra)
                    if overrides:
                        merged_config = load_prompt_config(
                            config, prompt_dir=None, overrides_dict=overrides
                        )
            finally:
                await session.close()

        # Create providers using merged config (respects per-prompt overrides)
        meta_provider = create_provider(merged_config.meta_provider, merged_config)
        target_provider = create_provider(merged_config.target_provider, merged_config)
        judge_provider = create_provider(merged_config.judge_provider, merged_config)

        # Create scorer
        judge_scorer = BehaviorJudgeScorer(judge_provider, merged_config.judge_model)

        # Build event callback that publishes to EventBus
        async def event_callback(event_type: str, data: dict) -> None:
            await event_bus.publish(run_id, event_type, data)

        # Resolve per-role temperatures (fallback to hardcoded defaults for synthesis)
        meta_temperature = (
            merged_config.meta_temperature if merged_config.meta_temperature is not None else 0.9
        )
        target_temperature = merged_config.target_temperature

        # Load tool mocker config and format guides from DB
        format_guides: dict[str, list[str]] = {}
        llm_mocker = None
        max_tool_steps = DEFAULT_MAX_TOOL_STEPS

        if config.database_url:
            from sqlalchemy import select as sa_select

            from api.storage.database import Database
            from api.storage.models import PromptConfig as PromptConfigModel
            from api.storage.models import ToolFormatGuide

            db = Database(config.database_url)
            session = await db.get_session()
            try:
                # Load tool_mocker settings from prompt config extra JSON
                pc_row = (
                    await session.execute(
                        sa_select(PromptConfigModel).where(
                            PromptConfigModel.prompt_id == prompt_id
                        )
                    )
                ).scalar_one_or_none()

                tool_mocker_mode = "static"
                tool_mocker_provider_name = None
                tool_mocker_model_name = None
                max_tool_steps = DEFAULT_MAX_TOOL_STEPS

                if pc_row and pc_row.extra:
                    tool_mocker_mode = pc_row.extra.get("tool_mocker_mode", "static") or "static"
                    tool_mocker_provider_name = pc_row.extra.get("tool_mocker_provider")
                    tool_mocker_model_name = pc_row.extra.get("tool_mocker_model")
                    max_tool_steps = pc_row.extra.get("max_tool_steps", DEFAULT_MAX_TOOL_STEPS)

                if tool_mocker_mode == "llm":
                    # Load format guides for this prompt
                    rows = (
                        (
                            await session.execute(
                                sa_select(ToolFormatGuide).where(
                                    ToolFormatGuide.prompt_id == prompt_id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for row in rows:
                        format_guides[row.tool_name] = row.examples

                    if format_guides and tool_mocker_provider_name and tool_mocker_model_name:
                        from api.registry.llm_mocker import LLMMocker

                        try:
                            tool_mocker_provider = create_provider(
                                tool_mocker_provider_name, merged_config
                            )
                            llm_mocker = LLMMocker(tool_mocker_provider, tool_mocker_model_name)
                            logger.info(
                                "LLM mocker enabled for %s (%s/%s, %d format guides)",
                                prompt_id,
                                tool_mocker_provider_name,
                                tool_mocker_model_name,
                                len(format_guides),
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to create LLM mocker: %s -- falling back to static",
                                exc,
                            )
            finally:
                await session.close()

        # Create engine
        engine = SynthesisEngine(
            meta_provider=meta_provider,
            target_provider=target_provider,
            judge_scorer=judge_scorer,
            dataset_service=dataset_service,
            meta_model=merged_config.meta_model,
            target_model=merged_config.target_model,
            event_callback=event_callback,
            meta_temperature=meta_temperature,
            target_temperature=target_temperature,
            llm_mocker=llm_mocker,
            format_guides=format_guides if format_guides else None,
            max_tool_steps=max_tool_steps,
        )

        # Load existing cases for variable sampling
        existing_cases = await dataset_service.list_cases(prompt_id)

        # Load variable definitions from DB Prompt row
        variable_definitions = None
        if config.database_url:
            from sqlalchemy import select as sa_select

            from api.storage.database import Database
            from api.storage.models import Prompt as PromptModel

            db = Database(config.database_url)
            session = await db.get_session()
            try:
                result = await session.execute(
                    sa_select(PromptModel).where(PromptModel.id == prompt_id)
                )
                prompt_row = result.scalar_one_or_none()
                if prompt_row and prompt_row.variables:
                    from api.registry.models import VariableDefinition

                    variable_definitions = [
                        VariableDefinition(**v) for v in prompt_row.variables
                    ]
            finally:
                await session.close()

        # Build synthesis config
        synth_config = SynthesisConfig(
            num_conversations=num_conversations,
            max_turns=max_turns,
            persona_ids=persona_ids,
            scenario_context=scenario_context,
            review_mode=review_mode,
        )

        # Run synthesis
        result = await engine.run_synthesis(
            prompt_id=prompt_id,
            prompt_template=prompt_template,
            personas=personas,
            config=synth_config,
            existing_cases=existing_cases,
            tools=tools,
            mocks=mocks,
            variable_definitions=variable_definitions,
            prompt_purpose=purpose,
        )

        # Store result for review if review_mode is active
        if review_mode and pending_reviews is not None:
            pending_reviews[run_id] = result

        logger.info(
            "Synthesis complete for %s: %d conversations, %d persisted, %d discarded "
            "(review_mode=%s)",
            prompt_id,
            result.total_conversations,
            result.total_persisted,
            result.total_discarded,
            review_mode,
        )

    except Exception as exc:
        logger.exception("Synthesis failed for %s", prompt_id)
        try:
            await event_bus.publish(
                run_id,
                "synthesis_failed",
                {
                    "error": f"Synthesis failed: {type(exc).__name__}: {exc}",
                },
            )
        except Exception:
            pass
    finally:
        # Cleanup providers (including tool mocker provider if created)
        for provider in (meta_provider, target_provider, judge_provider, tool_mocker_provider):
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass
        # Cleanup EventBus run
        event_bus.cleanup_run(run_id)


@router.post("/{prompt_id}/review", response_model=ReviewResponse)
async def review_conversations(
    prompt_id: str,
    body: ReviewRequest,
    request: Request,
    dataset_service=Depends(get_dataset_service),
    user: User = Depends(get_current_user),
):
    """Submit approve/reject decisions for synthesized conversations.

    Retrieves the buffered synthesis result by run_id, persists approved
    conversations as test cases via DatasetService, and discards rejected ones.
    Cleans up the in-memory buffer after processing.

    Args:
        prompt_id: Prompt to persist approved conversations to.
        body: Review decisions with run_id and per-conversation actions.
        request: FastAPI request for accessing app state.
        dataset_service: Dataset service for persisting test cases.

    Returns:
        ReviewResponse with approved/rejected counts and persisted case IDs.

    Raises:
        HTTPException: 404 if the review session is not found or expired.
    """
    pending_reviews = getattr(request.app.state, "pending_reviews", None) or {}
    result = pending_reviews.get(body.run_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Review session not found or expired.",
        )

    approved = 0
    rejected = 0
    case_ids: list[str] = []

    for decision in body.decisions:
        if decision.action == "approve":
            conv = result.conversations[decision.conversation_index]
            edits = decision.edits or {}

            test_case = TestCase(
                chat_history=edits.get("chat_history", conv.chat_history),
                variables=edits.get("variables", conv.variables),
                expected_output=edits.get(
                    "expected_output",
                    {"behavior": conv.behavior_criteria} if conv.behavior_criteria else None,
                ),
                tags=edits.get("tags", ["synthetic"]),
                name=edits.get("name"),
            )

            persisted_case, _warnings = await dataset_service.add_case(prompt_id, test_case)
            case_ids.append(persisted_case.id)
            approved += 1
        else:
            rejected += 1

    # Clean up the pending review to free memory
    pending_reviews.pop(body.run_id, None)

    return ReviewResponse(
        approved=approved,
        rejected=rejected,
        case_ids=case_ids,
    )
