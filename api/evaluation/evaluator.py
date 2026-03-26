"""FitnessEvaluator: orchestrates the full evaluation pipeline.

Ties together all Phase 2 components into a single evaluate() call:
render template -> run LLM inference -> score responses -> aggregate fitness.

This is the primary interface that Phase 3 (evolution engine) will use
to score candidate prompts.

NOTE: Currently evaluates cases sequentially for simplicity and correctness.
Concurrent evaluation via asyncio.gather() can be added later -- the
LiteLLMProvider's semaphore handles API rate limiting.
"""

import asyncio
import logging
from typing import Any

from api.config.models import GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.aggregator import FitnessAggregator
from api.evaluation.models import CaseResult, EvaluationReport
from api.evaluation.renderer import TemplateRenderer, TemplateRenderError
from api.evaluation.scorers import BehaviorJudgeScorer, ExactMatchScorer
from api.exceptions import GatewayError, RetryableError
from api.gateway.cost import CostTracker
from api.gateway.protocol import LLMProvider
from api.registry.llm_mocker import LLMMocker
from api.registry.schemas import MockDefinition
from api.registry.tool_resolver import DEFAULT_MAX_TOOL_STEPS, normalize_tool_call, resolve_tool_call
from api.types import ModelRole

logger = logging.getLogger(__name__)


class FitnessEvaluator:
    """Orchestrates the evaluation pipeline for scoring candidate prompts.

    Pipeline per case:
    1. Render: Inject case variables into the template via TemplateRenderer.
    2. Build messages: [system prompt + chat_history].
    3. Infer: Call LLM via LLMProvider with ModelRole.TARGET.
    4. Track cost: Record the response via CostTracker.
    5. Score: Route to ExactMatchScorer (tool_calls) or BehaviorJudgeScorer (behavior).
    6. Annotate: Set case_id and tier on the CaseResult.

    After all cases: aggregate via FitnessAggregator.

    Usage:
        evaluator = FitnessEvaluator(
            client=client,
            renderer=renderer,
            exact_scorer=exact_scorer,
            behavior_scorer=behavior_scorer,
            aggregator=aggregator,
            cost_tracker=cost_tracker,
        )
        report = await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=cases,
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )
    """

    def __init__(
        self,
        client: LLMProvider,
        renderer: TemplateRenderer,
        exact_scorer: ExactMatchScorer,
        behavior_scorer: BehaviorJudgeScorer,
        aggregator: FitnessAggregator,
        cost_tracker: CostTracker,
        extra_inference_kwargs: dict | None = None,
        mocks: list[MockDefinition] | None = None,
        llm_mocker: LLMMocker | None = None,
        format_guides: dict[str, list[str]] | None = None,
        max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS,
    ) -> None:
        self._client = client
        self._renderer = renderer
        self._exact_scorer = exact_scorer
        self._behavior_scorer = behavior_scorer
        self._aggregator = aggregator
        self._cost_tracker = cost_tracker
        self._extra_inference_kwargs = extra_inference_kwargs
        self._mocks = mocks
        self._llm_mocker = llm_mocker
        self._format_guides = format_guides or {}
        self._max_tool_steps = max_tool_steps

    async def evaluate(
        self,
        template: str,
        cases: list[TestCase],
        target_model: str,
        generation_config: GenerationConfig,
        prompt_tools: list[dict[str, Any]] | None = None,
        purpose: str = "",
    ) -> EvaluationReport:
        """Run the full evaluation pipeline on a candidate prompt.

        For each test case: renders the template with case variables,
        runs LLM inference, scores the response, and tracks cost.
        After all cases, aggregates scores into a FitnessScore.

        Args:
            template: Jinja2 template string (the candidate prompt).
            cases: List of TestCase objects to evaluate against.
            target_model: OpenRouter model identifier for inference.
            generation_config: Temperature, max_tokens, etc.
            prompt_tools: Default tool definitions (used when case has no tools).
            purpose: Purpose string passed to BehaviorJudgeScorer context.

        Returns:
            EvaluationReport with fitness score, per-case results, and cost summary.
        """
        case_results: list[CaseResult] = []

        for i, case in enumerate(cases):
            result = await self._evaluate_case(
                template=template,
                case=case,
                target_model=target_model,
                generation_config=generation_config,
                prompt_tools=prompt_tools,
                purpose=purpose,
            )
            case_results.append(result)
            # Small delay between cases to avoid provider rate limits
            if i < len(cases) - 1:
                await asyncio.sleep(0.3)

        # Aggregate all case results into a fitness score
        fitness = self._aggregator.aggregate(case_results)

        return EvaluationReport(
            fitness=fitness,
            case_results=case_results,
            total_cases=len(cases),
            cost_summary=self._cost_tracker.summary(),
        )

    async def _evaluate_case(
        self,
        template: str,
        case: TestCase,
        target_model: str,
        generation_config: GenerationConfig,
        prompt_tools: list[dict[str, Any]] | None,
        purpose: str,
    ) -> CaseResult:
        """Evaluate a single test case through the pipeline.

        Steps:
        1. Render template with case variables.
        2. Build messages (system + chat_history).
        3. Run LLM inference.
        4. Track cost.
        5. Score with appropriate scorer.
        6. Annotate result with case_id and tier.
        """
        # Step 1: Render template with case variables
        try:
            rendered_prompt = self._renderer.render(template, case.variables)
        except TemplateRenderError as exc:
            logger.warning("Rendering failed for case %s: %s", case.id, exc)
            return CaseResult(
                case_id=case.id,
                tier=case.tier.value,
                score=-2,
                passed=False,
                reason=f"Rendering error: {exc}",
                synthetic="synthetic" in (case.tags or []),
            )

        # Step 2: Build messages [system + chat_history]
        messages: list[dict[str, str]] = [
            {"role": "system", "content": rendered_prompt},
            *case.chat_history,
        ]

        # Step 3: Determine tools (case-specific takes precedence over prompt-level)
        tools = case.tools if case.tools is not None else prompt_tools

        # Step 4: Run LLM inference
        inference_kwargs: dict[str, Any] = {
            "messages": messages,
            "model": target_model,
            "role": ModelRole.TARGET,
            "temperature": generation_config.temperature,
            "max_tokens": generation_config.max_tokens,
        }
        if generation_config.top_p is not None:
            inference_kwargs["top_p"] = generation_config.top_p
        if generation_config.top_k is not None:
            inference_kwargs["top_k"] = generation_config.top_k
        if generation_config.frequency_penalty is not None:
            inference_kwargs["frequency_penalty"] = generation_config.frequency_penalty
        if generation_config.presence_penalty is not None:
            inference_kwargs["presence_penalty"] = generation_config.presence_penalty
        if tools is not None:
            inference_kwargs["tools"] = tools
        if self._extra_inference_kwargs:
            inference_kwargs.update(self._extra_inference_kwargs)

        try:
            response = await self._client.chat_completion(**inference_kwargs)
        except (GatewayError, RetryableError) as exc:
            logger.warning("API error for case %s: %s", case.id, exc)
            return CaseResult(
                case_id=case.id,
                tier=case.tier.value,
                score=-2,
                passed=False,
                reason=f"API error: {exc}",
                synthetic="synthetic" in (case.tags or []),
            )

        # Step 5: Track cost (initial call)
        self._cost_tracker.record(response)

        # Step 5b: Agentic tool loop — execute tool calls via mocks until stop
        if self._mocks is not None or self._llm_mocker is not None:
            tool_step = 0
            while response.tool_calls and tool_step < self._max_tool_steps:
                tool_step += 1

                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": response.tool_calls,
                })

                for tc in response.tool_calls:
                    normalized = normalize_tool_call(tc)
                    result_content = await resolve_tool_call(
                        normalized["name"],
                        normalized["arguments"] if isinstance(normalized["arguments"], dict) else {},
                        mocks=self._mocks,
                        llm_mocker=self._llm_mocker,
                        format_guides=self._format_guides if self._format_guides else None,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result_content,
                    })

                inference_kwargs["messages"] = messages
                try:
                    response = await self._client.chat_completion(**inference_kwargs)
                except (GatewayError, RetryableError) as exc:
                    logger.warning("API error during tool loop for case %s: %s", case.id, exc)
                    break

                self._cost_tracker.record(response)

        # Step 6: Score with appropriate scorer (4-way routing)
        expected = case.expected_output or {}
        has_tool_calls = bool(expected.get("tool_calls"))
        has_behavior = bool(expected.get("behavior"))

        if has_tool_calls and has_behavior:
            # Combined: ExactMatch first (short-circuit on failure), then behavior
            exact_result = await self._exact_scorer.score(
                expected=expected,
                actual_response=response,
                context={"case_id": case.id, "purpose": purpose},
            )
            if not exact_result.passed:
                result = exact_result  # Short-circuit: saves judge API cost
            else:
                behavior_result = await self._behavior_scorer.score(
                    expected=expected,
                    actual_response=response,
                    context={
                        "case_id": case.id,
                        "purpose": purpose,
                        "conversation": messages,
                    },
                )
                # AND gate: merge results (sum penalties)
                result = CaseResult(
                    case_id=case.id,
                    score=exact_result.score + behavior_result.score,
                    passed=exact_result.passed and behavior_result.passed,
                    reason=f"ExactMatch: {exact_result.reason} | Behavior: {behavior_result.reason}",
                    expected=expected,
                    actual_content=response.content,
                    actual_tool_calls=response.tool_calls,
                    criteria_results=behavior_result.criteria_results,
                )
        elif has_tool_calls:
            # Tool call only -> ExactMatchScorer
            result = await self._exact_scorer.score(
                expected=expected,
                actual_response=response,
                context={"case_id": case.id, "purpose": purpose},
            )
        elif has_behavior:
            # Behavior only -> BehaviorJudgeScorer
            result = await self._behavior_scorer.score(
                expected=expected,
                actual_response=response,
                context={
                    "case_id": case.id,
                    "purpose": purpose,
                    "conversation": messages,
                },
            )
        else:
            # Backward compat: content-only or no expected -> BehaviorJudgeScorer
            content = expected.get("content", "")
            if content:
                migrated = {**expected, "behavior": [f"Output matches expected: {content}"]}
            else:
                migrated = {**expected, "behavior": ["Response is relevant and helpful"]}
            result = await self._behavior_scorer.score(
                expected=migrated,
                actual_response=response,
                context={
                    "case_id": case.id,
                    "purpose": purpose,
                    "conversation": messages,
                },
            )

        # Step 7: Annotate with case_id, tier, and synthetic flag
        result.case_id = case.id
        result.tier = case.tier.value
        # Phase 33: thread synthetic tag from TestCase to CaseResult
        result.synthetic = "synthetic" in (case.tags or [])

        return result
