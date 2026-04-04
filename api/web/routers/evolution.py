"""Evolution start/stop/status API endpoints.

Provides POST /start, POST /{run_id}/stop, GET /{run_id}/status
for triggering and managing background evolution runs.

The actual evolution pipeline is imported lazily to avoid heavy
startup costs and circular imports.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from api.config.models import GenerationConfig
from api.evolution.models import EvolutionConfig
from api.storage.models import User
from api.web.auth import get_current_user
from api.web.deps import get_config, get_dataset_service, get_registry
from api.web.schemas import EvolutionRunRequest, EvolutionRunStatus

router = APIRouter()


@router.post("/start", response_model=EvolutionRunStatus)
async def start_evolution(
    body: EvolutionRunRequest,
    request: Request,
    config=Depends(get_config),
    registry=Depends(get_registry),
    dataset_service=Depends(get_dataset_service),
    user: User = Depends(get_current_user),
):
    """Start an evolution run as a background task.

    Loads the prompt and test cases, builds an EvolutionConfig,
    and hands the coroutine to the RunManager.
    """
    # Lazy import to avoid circular imports and heavy startup cost
    from api.evolution.runner import run_evolution

    run_manager = request.app.state.run_manager

    # Load prompt (raises PromptNotFoundError -> 404 via exception handler)
    prompt_record = await registry.load_prompt(body.prompt_id, config)

    # Load test cases
    cases = await dataset_service.list_cases(body.prompt_id)
    if not cases:
        raise HTTPException(status_code=400, detail="No test cases found")

    # Build evolution config from request body
    config_kwargs = dict(
        generations=body.generations,
        n_islands=body.islands,
        conversations_per_island=body.conversations_per_island,
        budget_cap_usd=body.budget_cap_usd,
        sample_size=body.sample_size,
        sample_ratio=body.sample_ratio,
    )
    if body.pr_no_parents is not None:
        config_kwargs["pr_no_parents"] = body.pr_no_parents
    if body.temperature is not None:
        config_kwargs["temperature"] = body.temperature
    if body.structural_mutation_probability is not None:
        config_kwargs["structural_mutation_probability"] = body.structural_mutation_probability

    # Thread advanced evolution params from request body
    for field in ["n_seq", "population_cap", "n_emigrate", "reset_interval", "n_reset", "n_top"]:
        val = getattr(body, field)
        if val is not None:
            config_kwargs[field] = val

    # Thread adaptive sampling params from request body
    for field in [
        "adaptive_sampling",
        "adaptive_decay_constant",
        "adaptive_min_rate",
        "checkpoint_interval",
    ]:
        val = getattr(body, field)
        if val is not None:
            config_kwargs[field] = val

    evo_config = EvolutionConfig(**config_kwargs)

    # Build GenerationConfig override from inference params
    gen_kwargs: dict = {}
    if body.inference_temperature is not None:
        gen_kwargs["temperature"] = body.inference_temperature
    for field in ["top_p", "top_k", "max_tokens", "frequency_penalty", "presence_penalty"]:
        val = getattr(body, field)
        if val is not None:
            gen_kwargs[field] = val
    generation_config = GenerationConfig(**gen_kwargs) if gen_kwargs else None

    # Create the coroutine factory and hand to run manager with event_bus
    event_bus = request.app.state.event_bus

    # Resolve effective model/provider values for RunManager persistence
    effective_models = {
        "meta_model": body.meta_model or config.meta_model,
        "meta_provider": body.meta_provider or config.meta_provider,
        "target_model": body.target_model or config.target_model,
        "target_provider": body.target_provider or config.target_provider,
        "judge_model": body.judge_model or config.judge_model,
        "judge_provider": body.judge_provider or config.judge_provider,
    }

    # Build per-role thinking config (Gemini-specific)
    thinking_config = {}
    for role in ["meta", "target", "judge"]:
        budget = getattr(body, f"{role}_thinking_budget")
        level = getattr(body, f"{role}_thinking_level")
        if budget is not None:
            thinking_config[role] = {"thinking_budget": budget}
        elif level is not None:
            thinking_config[role] = {"thinking_level": level}
    thinking_config = thinking_config or None

    def coro_factory(event_callback=None):
        return run_evolution(
            config,
            prompt_record,
            cases,
            evo_config,
            event_callback=event_callback,
            meta_model=body.meta_model or None,
            meta_provider=body.meta_provider or None,
            target_model=body.target_model or None,
            target_provider=body.target_provider or None,
            judge_model=body.judge_model or None,
            judge_provider=body.judge_provider or None,
            generation_config=generation_config,
            thinking_config=thinking_config,
        )

    run_id = await run_manager.start_run(
        body.prompt_id,
        coro_factory,
        event_bus=event_bus,
        config=config,
        evolution_config=evo_config,
        effective_models=effective_models,
        generation_config=generation_config,
        thinking_config=thinking_config,
    )

    return EvolutionRunStatus(**run_manager.get_status(run_id))


@router.get("/active", response_model=list[EvolutionRunStatus])
async def list_active_runs(request: Request, user: User = Depends(get_current_user)):
    """List all currently active (in-memory) evolution runs."""
    run_manager = request.app.state.run_manager
    all_statuses = run_manager.list_runs()
    return [EvolutionRunStatus(**s) for s in all_statuses if s is not None]


@router.post("/{run_id}/stop")
async def stop_evolution(run_id: str, request: Request, user: User = Depends(get_current_user)):
    """Cancel a running evolution task."""
    run_manager = request.app.state.run_manager
    stopped = await run_manager.stop_run(run_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Run not found or already completed")
    return {"status": "cancelled", "run_id": run_id}


@router.get("/{run_id}/status", response_model=EvolutionRunStatus)
async def get_run_status(run_id: str, request: Request, user: User = Depends(get_current_user)):
    """Get the current status of an evolution run."""
    run_manager = request.app.state.run_manager
    status = run_manager.get_status(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return EvolutionRunStatus(**status)
