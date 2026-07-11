"""EvolutionLoop: single-island evolution orchestrator.

Ties together BoltzmannSelector, RCCEngine, StructuralMutator, and
FitnessEvaluator into a generation-by-generation loop with:
- Per-generation cost tracking (COST-02)
- Hard budget cap with conversation-level granularity (COST-03)
- Early termination on perfect fitness (score == 0.0) (EVO-08)
- Population management (fitness sorting, cap -- all candidates participate)
- Stochastic parent count sampling (Pr_no_parents)
- Probabilistic structural mutation
"""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from api.config.models import GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.adaptive import AdaptiveSampler
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.models import CaseResult, EvaluationInvalidError, EvaluationReport
from api.evaluation.sampling import SamplingStrategy
from api.evolution.models import (
    Candidate,
    EvolutionConfig,
    EvolutionResult,
    GenerationRecord,
)
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.scouting import ScoutResult, canonicalize_template, is_full_report
from api.evolution.selector import BoltzmannSelector
from api.exceptions import BudgetExhaustedError, GatewayError, RetryableError
from api.gateway.cost import CostTracker
from api.lineage.collector import LineageCollector
from api.lineage.models import LineageEvent

logger = logging.getLogger(__name__)

# Type alias for the optional async event callback.
# When provided, the callback is invoked with (event_type, data) at
# each instrumentation point. When None, no events are emitted.
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]] | None


class EvolutionLoop:
    """Orchestrates single-island prompt evolution.

    Manages the generation-by-generation loop, coordinating parent selection,
    RCC conversations, structural mutation, fitness evaluation, population
    management, and termination conditions.

    Args:
        config: Evolution hyperparameters (generations, budget, probabilities).
        evaluator: FitnessEvaluator for scoring candidate prompts.
        rcc: RCCEngine for critic-author conversation refinement.
        mutator: StructuralMutator for section-level restructuring.
        selector: BoltzmannSelector for parent selection.
        cost_tracker: Global CostTracker for budget enforcement.
        original_template: The seed Jinja2 template to evolve.
        anchor_variables: Variables that must be preserved in all candidates.
        cases: Test cases for fitness evaluation.
        target_model: OpenRouter model identifier for inference.
        generation_config: Temperature, max_tokens, etc. for inference.
        prompt_tools: Default tool definitions for evaluation (optional).
        purpose: Description of what the prompt is optimized for.
    """

    def __init__(
        self,
        config: EvolutionConfig,
        evaluator: FitnessEvaluator,
        rcc: RCCEngine,
        mutator: StructuralMutator,
        selector: BoltzmannSelector,
        cost_tracker: CostTracker,
        original_template: str,
        anchor_variables: set[str],
        cases: list[TestCase],
        target_model: str,
        generation_config: GenerationConfig,
        prompt_tools: list[dict] | None = None,
        purpose: str = "",
        collector: LineageCollector | None = None,
        event_callback: EventCallback = None,
    ) -> None:
        self._config = config
        self._evaluator = evaluator
        self._rcc = rcc
        self._mutator = mutator
        self._selector = selector
        self._cost_tracker = cost_tracker
        self._original_template = original_template
        self._anchor_variables = anchor_variables
        self._cases = cases
        self._expected_case_ids = {case.id for case in cases}
        self._target_model = target_model
        self._generation_config = generation_config
        self._prompt_tools = prompt_tools
        self._purpose = purpose
        self._collector = collector
        self._event_callback = event_callback
        self._seed_results: list[CaseResult] | None = None

        # Adaptive sampling (EVO-04/05/06): create sampler when enabled
        self._adaptive_sampler: AdaptiveSampler | None = None
        if config.adaptive_sampling:
            self._adaptive_sampler = AdaptiveSampler(
                decay_constant=config.adaptive_decay_constant,
                min_rate=config.adaptive_min_rate,
            )

    def set_seed_results(self, results: list[CaseResult]) -> None:
        """Inject seed evaluation results for sampling decisions.

        IslandEvolver calls this after its own seed evaluation so that
        step_generation() can apply SamplingStrategy.smart_subset().
        """
        self._seed_results = results

    async def run(self) -> EvolutionResult:
        """Execute the single-island evolution loop.

        1. Initialize population with the original template (evaluated for baseline).
        2. Iterate generations with budget checks, RCC conversations,
           structural mutation, evaluation, and population management.
        3. Terminate on perfect fitness, budget exhaustion, or generation count.

        Returns:
            EvolutionResult with best candidate, generation records,
            total cost, and termination reason.
        """
        # Initialize population: evaluate the original template for baseline
        seed_candidate = Candidate(
            template=self._original_template,
            generation=0,
            parent_ids=[],
        )
        seed_candidate = await self._evaluate_candidate_full(seed_candidate)
        seed_report = seed_candidate.evaluation
        assert seed_report is not None
        self._seed_results = seed_report.case_results

        if self._collector is not None:
            self._collector.record(
                LineageEvent(
                    candidate_id=seed_candidate.id,
                    parent_ids=[],
                    generation=0,
                    fitness_score=seed_candidate.fitness_score,
                    normalized_score=seed_candidate.normalized_score,
                    rejected=seed_candidate.rejected,
                    mutation_type="seed",
                    template=seed_candidate.template,
                )
            )

        population: list[Candidate] = [seed_candidate]
        best_candidate = seed_candidate
        generation_records: list[GenerationRecord] = []
        termination_reason = "generations_complete"

        if self._is_perfect(best_candidate):
            return EvolutionResult(
                best_candidate=best_candidate,
                generation_records=generation_records,
                total_cost=self._cost_tracker.summary(),
                termination_reason="perfect_fitness",
                seed_evaluation=seed_report,
            )

        # Generation loop
        for gen in range(self._config.generations):
            # Check budget at generation boundary
            if self._budget_exceeded():
                termination_reason = "budget_exhausted"
                logger.info("Budget exhausted before generation %d", gen)
                break

            population, record, step_reason = await self.step_generation(
                population=population,
                generation=gen,
            )
            generation_records.append(record)

            # Track best candidate (higher = less penalized = better)
            if population:
                gen_best = population[0]  # Already sorted by fitness desc
                if self._candidate_sort_key(gen_best) < self._candidate_sort_key(best_candidate):
                    best_candidate = gen_best

            # Check termination from step_generation
            if step_reason is not None:
                termination_reason = step_reason
                break

        return EvolutionResult(
            best_candidate=best_candidate,
            generation_records=generation_records,
            total_cost=self._cost_tracker.summary(),
            termination_reason=termination_reason,
            seed_evaluation=seed_report,
        )

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event via the callback, if one is registered."""
        if self._event_callback is not None:
            await self._event_callback(event_type, data)

    async def step_generation(
        self,
        population: list[Candidate],
        generation: int,
        island: int = 0,
    ) -> tuple[list[Candidate], GenerationRecord, str | None]:
        """Run one generation of evolution on the given population.

        Executes conversations_per_island RCC conversations, applies
        structural mutation probabilistically, evaluates candidates,
        manages population, and returns the result.

        This method is the building block for both single-island run()
        and multi-island IslandEvolver, which inserts migration and
        reset between generations.

        Args:
            population: Current population of candidates.
            generation: Generation number (0-indexed).

        Returns:
            A tuple of (updated_population, generation_record, termination_reason)
            where termination_reason is None if the generation completed normally,
            "perfect_fitness" if a perfect candidate was found, or
            "budget_exhausted" if the budget was exceeded mid-generation.
        """
        full_report_cache: dict[str, EvaluationReport] = {}
        for candidate in population:
            report = candidate.evaluation
            if report is None or not is_full_report(report, self._expected_case_ids):
                raise EvaluationInvalidError(
                    "Incoming population candidate lacks an exact full evaluation"
                )
            full_report_cache[canonicalize_template(candidate.template)] = report.model_copy(
                deep=True
            )

        completed_paper_drafts: list[Candidate] = []

        async def evaluate_paper_draft(candidate: Candidate) -> Candidate:
            canonical = canonicalize_template(candidate.template)
            cached = full_report_cache.get(canonical)
            if cached is None:
                candidate = await self._evaluate_candidate_full(candidate)
                assert candidate.evaluation is not None
                full_report_cache[canonical] = candidate.evaluation.model_copy(deep=True)
            else:
                candidate = self._attach_full_report(candidate, cached.model_copy(deep=True))
            completed_paper_drafts.append(candidate)
            return candidate

        cost_before_gen = self._cost_tracker.summary()
        termination_reason: str | None = None
        drafts: list[tuple[Candidate, bool]] = []

        is_checkpoint = (
            self._adaptive_sampler is not None
            and self._config.checkpoint_interval > 0
            and generation > 0
            and generation % self._config.checkpoint_interval == 0
        )

        for conv in range(self._config.conversations_per_island):
            if self._budget_exceeded():
                termination_reason = "budget_exhausted"
                logger.info(
                    "Budget exhausted at generation %d, conversation %d",
                    generation,
                    conv,
                )
                break

            n_parents_this = self._sample_parent_count()
            parents = self._selector.select(population, n_parents_this, self._config.temperature)

            try:
                conversation_drafts = list(await self._rcc.run_conversation(
                    parents=parents,
                    original_template=self._original_template,
                    anchor_variables=self._anchor_variables,
                    purpose=self._purpose,
                    rcc_rounds=self._config.rcc_rounds,
                    generation=generation,
                    evaluate_draft=(
                        evaluate_paper_draft
                        if self._config.retain_intermediate_children
                        else None
                    ),
                ))
            except BudgetExhaustedError:
                termination_reason = "budget_exhausted"
                drafts.extend((candidate, False) for candidate in completed_paper_drafts)
                break
            except RetryableError as exc:
                logger.warning(
                    "RCC conversation %d failed (gen %d, island %d): %s — skipping (transient)",
                    conv,
                    generation,
                    island,
                    exc,
                )
                continue
            except GatewayError as exc:
                logger.error(
                    "RCC conversation %d failed (gen %d, island %d): %s — aborting (non-retryable)",
                    conv,
                    generation,
                    island,
                    exc,
                )
                raise

            structural_candidate_id: str | None = None
            if (
                conversation_drafts
                and random.random() < self._config.structural_mutation_probability
            ):
                original = conversation_drafts[-1]
                try:
                    mutated = await self._mutator.mutate(
                        original,
                        self._original_template,
                        self._anchor_variables,
                    )
                    if canonicalize_template(mutated.template) != canonicalize_template(
                        original.template
                    ):
                        mutated.evaluation = None
                        mutated.fitness_score = 0.0
                        mutated.normalized_score = 0.0
                        mutated.rejected = False
                        if original.evaluation is not None:
                            conversation_drafts.append(mutated)
                        else:
                            conversation_drafts[-1] = mutated
                        structural_candidate_id = mutated.id
                except BudgetExhaustedError:
                    termination_reason = "budget_exhausted"
                    drafts.extend((candidate, False) for candidate in conversation_drafts)
                    break
                except RetryableError as exc:
                    logger.warning(
                        "Structural mutation failed (gen %d, island %d): %s — using RCC result",
                        generation,
                        island,
                        exc,
                    )
                except GatewayError:
                    raise

            drafts.extend(
                (candidate, candidate.id == structural_candidate_id)
                for candidate in conversation_drafts
            )

        seen_templates = {canonicalize_template(candidate.template) for candidate in population}
        distinct_drafts: list[tuple[Candidate, bool]] = []
        for candidate, applied_structural in drafts:
            canonical = canonicalize_template(candidate.template)
            if canonical in seen_templates:
                continue
            seen_templates.add(canonical)
            distinct_drafts.append((candidate, applied_structural))

        new_candidates: list[Candidate] = []
        mutation_types: dict[str, str] = {}
        pending: list[tuple[Candidate, bool]] = []
        for candidate, applied_structural in distinct_drafts:
            if candidate.evaluation is None:
                pending.append((candidate, applied_structural))
                continue
            if not is_full_report(candidate.evaluation, self._expected_case_ids):
                raise EvaluationInvalidError("RCC draft evaluation did not cover every case")
            new_candidates.append(candidate)
            mutation_types[candidate.id] = self._mutation_type(candidate, applied_structural)

        sampling_enabled = (
            not is_checkpoint
            and (
                self._config.sample_size is not None
                or self._config.sample_ratio is not None
            )
        )
        promoted: list[tuple[Candidate, bool]]
        if sampling_enabled and pending:
            elite = self._best_full_candidate(population)
            previous_results = (
                elite.evaluation.case_results
                if elite is not None and elite.evaluation is not None
                else self._seed_results
            )
            adaptive_weights = (
                self._adaptive_sampler.get_weights(self._cases)
                if self._adaptive_sampler
                else None
            )
            scout_cases = SamplingStrategy.smart_subset(
                cases=self._cases,
                previous_results=previous_results,
                sample_size=self._config.sample_size,
                sample_ratio=self._config.sample_ratio,
                adaptive_weights=adaptive_weights,
            )
            structural_by_id = {candidate.id: applied for candidate, applied in pending}
            scouts = []
            for candidate, _ in pending:
                try:
                    report = await self._evaluate_candidate(candidate, scout_cases)
                except BudgetExhaustedError:
                    termination_reason = "budget_exhausted"
                    break
                scouts.append(ScoutResult(candidate=candidate, report=report))
            if termination_reason == "budget_exhausted":
                promoted = []
            else:
                scouts.sort(
                    key=lambda scout: (
                        scout.report.fitness.rejected,
                        -scout.report.fitness.score,
                    )
                )
                promoted = [
                    (scout.candidate, structural_by_id[scout.candidate.id])
                    for scout in scouts[: self._config.promotions_per_island]
                ]
        else:
            promoted = pending

        for candidate, applied_structural in promoted:
            if self._budget_exceeded():
                termination_reason = "budget_exhausted"
                break
            try:
                candidate = await self._evaluate_candidate_full(candidate)
            except BudgetExhaustedError:
                termination_reason = "budget_exhausted"
                break
            new_candidates.append(candidate)
            mutation_types[candidate.id] = self._mutation_type(candidate, applied_structural)

        for candidate in new_candidates:
            mut_type = mutation_types[candidate.id]
            report = candidate.evaluation
            assert report is not None
            assert is_full_report(report, self._expected_case_ids)
            await self._emit(
                "candidate_evaluated",
                {
                    "generation": generation,
                    "candidate_id": candidate.id,
                    "fitness_score": candidate.fitness_score,
                    "normalized_score": candidate.normalized_score,
                    "rejected": candidate.rejected,
                    "mutation_type": mut_type,
                    "island": island,
                    "parent_ids": candidate.parent_ids,
                    "template": candidate.template,
                    "cases_passed": sum(result.passed for result in report.case_results),
                    "total_cases": report.total_cases,
                },
            )
            if self._collector is not None:
                self._collector.record(
                    LineageEvent(
                        candidate_id=candidate.id,
                        parent_ids=candidate.parent_ids,
                        generation=generation,
                        island=island,
                        fitness_score=candidate.fitness_score,
                        normalized_score=candidate.normalized_score,
                        rejected=candidate.rejected,
                        mutation_type=mut_type,
                        template=candidate.template,
                    )
                )

        if any(self._is_perfect(candidate) for candidate in new_candidates):
            termination_reason = "perfect_fitness"
            logger.info("Perfect fitness found at generation %d", generation)

        # Warn if all conversations failed (likely a systematic error, not transient)
        if len(new_candidates) == 0 and self._config.conversations_per_island > 0:
            logger.warning(
                "All %d conversations failed for gen %d island %d — no new candidates produced",
                self._config.conversations_per_island,
                generation,
                island,
            )

        # Update adaptive sampler with best candidate's results (EVO-04)
        if self._adaptive_sampler and new_candidates:
            best_new = min(new_candidates, key=self._candidate_sort_key)
            if best_new.evaluation:
                self._adaptive_sampler.update(best_new.evaluation.case_results)
                # On checkpoint: reset streaks for any case that failed (EVO-05)
                if is_checkpoint:
                    for r in best_new.evaluation.case_results:
                        if not r.passed:
                            self._adaptive_sampler.reset_case(r.case_id)

        # Population management
        combined = population + new_candidates
        population = self._select_survivors(combined)

        # Mark non-survivors in lineage
        if self._collector is not None:
            survivor_ids = {c.id for c in population}
            for c in new_candidates:
                if c.id not in survivor_ids:
                    # Record updated event for non-survivor
                    self._collector.record(
                        LineageEvent(
                            candidate_id=c.id,
                            parent_ids=c.parent_ids,
                            generation=generation,
                            island=island,
                            fitness_score=c.fitness_score,
                            normalized_score=c.normalized_score,
                            rejected=c.rejected,
                            mutation_type=mutation_types[c.id],
                            survived=False,
                            template=c.template,
                        )
                    )

        # Compute per-generation cost delta (COST-02)
        cost_after_gen = self._cost_tracker.summary()
        gen_cost_summary = {
            "total_calls": cost_after_gen["total_calls"] - cost_before_gen["total_calls"],
            "total_input_tokens": cost_after_gen["total_input_tokens"]
            - cost_before_gen["total_input_tokens"],
            "total_output_tokens": cost_after_gen["total_output_tokens"]
            - cost_before_gen["total_output_tokens"],
            "total_cost_usd": cost_after_gen["total_cost_usd"] - cost_before_gen["total_cost_usd"],
        }

        # Record generation metrics (all candidates participate)
        all_fitnesses = [c.fitness_score for c in population] if population else [0.0]
        all_normalized = [c.normalized_score for c in population] if population else [0.0]
        record = GenerationRecord(
            generation=generation,
            best_fitness=population[0].fitness_score if population else 0.0,
            avg_fitness=sum(all_fitnesses) / len(all_fitnesses),
            best_normalized=population[0].normalized_score if population else 0.0,
            avg_normalized=sum(all_normalized) / len(all_normalized),
            cost_summary=gen_cost_summary,
            candidates_evaluated=len(new_candidates),
        )

        return population, record, termination_reason

    async def _evaluate_candidate(
        self,
        candidate: Candidate,
        cases: list[TestCase],
    ) -> EvaluationReport:
        """Evaluate without attaching a possibly partial report to the candidate."""
        return await self._evaluator.evaluate(
            template=candidate.template,
            cases=cases,
            target_model=self._target_model,
            generation_config=self._generation_config,
            prompt_tools=self._prompt_tools,
            purpose=self._purpose,
        )

    async def _evaluate_candidate_full(self, candidate: Candidate) -> Candidate:
        """Attach fitness only after exact full-suite coverage is verified."""
        report = await self._evaluate_candidate(candidate, self._cases)
        if not is_full_report(report, self._expected_case_ids):
            raise EvaluationInvalidError("Candidate evaluation did not cover every case exactly")
        return self._attach_full_report(candidate, report)

    @staticmethod
    def _attach_full_report(candidate: Candidate, report: EvaluationReport) -> Candidate:
        """Copy verified full-report fields onto a candidate."""
        candidate.fitness_score = report.fitness.score
        candidate.normalized_score = report.fitness.normalized_score
        candidate.rejected = report.fitness.rejected
        candidate.evaluation = report
        return candidate

    def _best_full_candidate(self, population: list[Candidate]) -> Candidate | None:
        full_candidates = [
            candidate
            for candidate in population
            if candidate.evaluation is not None
            and is_full_report(candidate.evaluation, self._expected_case_ids)
        ]
        return min(full_candidates, key=self._candidate_sort_key) if full_candidates else None

    @staticmethod
    def _candidate_sort_key(candidate: Candidate) -> tuple[bool, float]:
        """Rank feasible candidates before rejected ones, then by raw fitness."""
        return candidate.rejected, -candidate.fitness_score

    @staticmethod
    def _mutation_type(candidate: Candidate, applied_structural: bool) -> str:
        if applied_structural:
            return "structural"
        return "fresh" if not candidate.parent_ids else "rcc"

    @staticmethod
    def _is_perfect(candidate: Candidate) -> bool:
        report = candidate.evaluation
        if report is None or report.fitness.rejected or not report.case_results:
            return False
        return all(result.passed for result in report.case_results)

    def _budget_exceeded(self) -> bool:
        """Check if the cost tracker total exceeds the configured budget cap.

        Returns False if no budget cap is configured.
        """
        if self._config.budget_cap_usd is None:
            return False
        return self._cost_tracker.summary()["total_cost_usd"] >= self._config.budget_cap_usd

    def _sample_parent_count(self) -> int:
        """Sample parent count with Pr_no_parents probability of zero.

        With probability pr_no_parents, returns 0 (fresh generation).
        Otherwise, returns random.randint(1, config.n_parents).
        """
        if self._config.n_parents == 0:
            return 0
        if random.random() < self._config.pr_no_parents:
            return 0
        return random.randint(1, self._config.n_parents)

    def _select_survivors(self, population: list[Candidate]) -> list[Candidate]:
        """Sort all candidates by fitness descending, cap at population_cap.

        All candidates participate -- heavily penalized ones just rank lower.

        Args:
            population: Current population including new candidates.

        Returns:
            Sorted and capped population, by fitness descending.
        """
        population.sort(key=self._candidate_sort_key)

        # Cap at population_cap
        return population[: self._config.population_cap]
