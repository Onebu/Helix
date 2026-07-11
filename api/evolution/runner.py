"""Wire the evolution engine dependencies for API and direct Python callers."""

from __future__ import annotations

import contextlib
import logging

from api.evolution.models import EvolutionConfig, EvolutionResult

logger = logging.getLogger(__name__)


async def run_evolution(
    config,
    prompt_record,
    cases,
    evolution_config: EvolutionConfig,
    event_callback=None,
    meta_model: str | None = None,
    meta_provider: str | None = None,
    target_model: str | None = None,
    target_provider: str | None = None,
    judge_model: str | None = None,
    judge_provider: str | None = None,
    generation_config=None,
    thinking_config: dict | None = None,
) -> EvolutionResult:
    """Execute the full evolution pipeline.

    Wires up all service dependencies (evaluator, rcc, mutator, selector,
    cost tracker, island evolver) and runs the evolution.

    Creates separate provider instances for each unique provider name
    (meta, target, judge may use different providers like openrouter/gemini).

    Args:
        config: GeneConfig with API keys and model settings.
        prompt_record: The loaded PromptRecord.
        cases: List of test cases for evaluation.
        evolution_config: Evolution hyperparameters.
        event_callback: Optional async callback for streaming events.
        meta_model: Override meta model name (None = use config default).
        meta_provider: Override meta provider name (None = use config default).
        target_model: Override target model name (None = use config default).
        target_provider: Override target provider name (None = use config default).
        judge_model: Override judge model name (None = use config default).
        judge_provider: Override judge provider name (None = use config default).
        generation_config: Override GenerationConfig for inference params
            (None = use config.generation defaults).
        thinking_config: Per-role thinking config dict for Gemini models
            (e.g., {"meta": {"thinking_budget": 1024}, "target": {"thinking_level": "low"}}).
            None = no thinking config (provider defaults).

    Returns:
        EvolutionResult with best candidate and generation records.
    """
    from api.evaluation.aggregator import FitnessAggregator
    from api.evaluation.evaluator import FitnessEvaluator
    from api.evaluation.renderer import TemplateRenderer
    from api.evaluation.scorers import BehaviorJudgeScorer, ExactMatchScorer
    from api.evaluation.validator import TemplateValidator
    from api.evolution.islands import IslandEvolver
    from api.evolution.mutator import StructuralMutator
    from api.evolution.rcc import RCCEngine
    from api.evolution.selector import BoltzmannSelector
    from api.gateway.budgeted_provider import BudgetedProvider
    from api.gateway.cost import CostTracker
    from api.gateway.factory import create_provider
    from api.lineage.collector import LineageCollector

    # Resolve effective model/provider values via local variables (NEVER mutate config)
    eff_meta_model = meta_model or config.meta_model
    eff_meta_provider = meta_provider or config.meta_provider
    eff_target_model = target_model or config.target_model
    eff_target_provider = target_provider or config.target_provider
    eff_judge_model = judge_model or config.judge_model
    eff_judge_provider = judge_provider or config.judge_provider

    cost_tracker = CostTracker(budget_cap_usd=evolution_config.budget_cap_usd)
    cost_tracker.validate_models([eff_meta_model, eff_target_model, eff_judge_model])
    collector = LineageCollector()

    # Create one provider per unique provider name
    async with contextlib.AsyncExitStack() as stack:
        providers = {}
        for pname in {eff_meta_provider, eff_target_provider, eff_judge_provider}:
            provider = create_provider(pname, config)
            entered = await stack.enter_async_context(provider)
            providers[pname] = BudgetedProvider(entered, cost_tracker)

        meta_client = providers[eff_meta_provider]
        target_client = providers[eff_target_provider]
        judge_client = providers[eff_judge_provider]

        # Build thinking kwargs per role for Gemini models via extra_body.
        # Budget <= 0 is omitted: -1 means dynamic (provider default),
        # 0 means "off" which most 2.5 models reject with 400.
        def _build_thinking_kwargs(role_name: str) -> dict:
            if not thinking_config or role_name not in thinking_config:
                return {}
            tc = thinking_config[role_name]
            if "thinking_budget" in tc:
                budget = tc["thinking_budget"]
                if budget <= 0:
                    return {}
                return {"extra_body": {"google": {"thinking_config": {"thinking_budget": budget}}}}
            if "thinking_level" in tc:
                return {"extra_body": {"google": {"thinking_config": tc}}}
            return {}

        # Build evaluator components
        renderer = TemplateRenderer()
        exact_scorer = ExactMatchScorer()
        behavior_scorer = BehaviorJudgeScorer(
            client=judge_client,
            judge_model=eff_judge_model,
            extra_kwargs=_build_thinking_kwargs("judge") or None,
        )
        aggregator = FitnessAggregator()

        evaluator = FitnessEvaluator(
            client=target_client,
            renderer=renderer,
            exact_scorer=exact_scorer,
            behavior_scorer=behavior_scorer,
            aggregator=aggregator,
            cost_tracker=cost_tracker,
            extra_inference_kwargs=_build_thinking_kwargs("target") or None,
            evaluation_concurrency=min(4, config.concurrency_limit),
        )

        validator = TemplateValidator()
        rcc = RCCEngine(
            client=meta_client,
            cost_tracker=cost_tracker,
            validator=validator,
            meta_model=eff_meta_model,
            max_retries=evolution_config.max_retries,
            extra_kwargs=_build_thinking_kwargs("meta") or None,
        )
        mutator = StructuralMutator(
            client=meta_client,
            cost_tracker=cost_tracker,
            validator=validator,
            meta_model=eff_meta_model,
            extra_kwargs=_build_thinking_kwargs("meta") or None,
        )
        selector = BoltzmannSelector()

        # Read the template from the DB-loaded PromptRecord
        template = prompt_record.template or ""

        evolver = IslandEvolver(
            config=evolution_config,
            evaluator=evaluator,
            rcc=rcc,
            mutator=mutator,
            selector=selector,
            cost_tracker=cost_tracker,
            original_template=template,
            anchor_variables=prompt_record.anchor_variables,
            cases=cases,
            target_model=eff_target_model,
            generation_config=generation_config or config.generation,
            prompt_tools=prompt_record.tools,
            purpose=prompt_record.purpose,
            collector=collector,
            event_callback=event_callback,
        )

        result = await evolver.run()
        # Store lineage events as proper field (replaces monkey-patch)
        if collector.events:
            result.lineage_events = collector.to_dict_list()

        # Attach effective model/provider info for persistence
        result.effective_models = {
            "meta_model": eff_meta_model,
            "meta_provider": eff_meta_provider,
            "target_model": eff_target_model,
            "target_provider": eff_target_provider,
            "judge_model": eff_judge_model,
            "judge_provider": eff_judge_provider,
        }

        return result
