"""IslandEvolver: multi-island evolution orchestrator.

Wraps N EvolutionLoop instances with cyclic migration and periodic
island reset per the Mind Evolution algorithm (arXiv:2501.09891).

Cross-island coordination:
- Cyclic migration: top n_emigrate candidates from island i -> island (i+1) % n
- Island reset: lowest-performing islands replaced with top global candidates
- Global best tracking across all islands
- Budget enforcement across all islands via shared CostTracker

All intra-island evolution (RCC, mutation, evaluation, population management)
is delegated to EvolutionLoop.step_generation().
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import uuid
from typing import Any

from api.config.models import GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.models import EvaluationInvalidError, EvaluationReport
from api.evolution.loop import EventCallback, EvolutionLoop
from api.evolution.models import (
    Candidate,
    EvolutionConfig,
    EvolutionResult,
    GenerationRecord,
)
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.scouting import canonicalize_template, is_full_report
from api.evolution.selector import BoltzmannSelector
from api.exceptions import BudgetExhaustedError, GatewayError
from api.gateway.cost import CostTracker
from api.lineage.collector import LineageCollector
from api.lineage.models import LineageEvent

logger = logging.getLogger(__name__)


class IslandEvolver:
    """Multi-island evolution orchestrator.

    Manages N EvolutionLoop instances with cyclic migration
    and periodic island reset per the Mind Evolution algorithm.

    Args:
        config: Evolution hyperparameters including island model fields.
        evaluator: FitnessEvaluator for scoring candidate prompts.
        rcc: RCCEngine for critic-author conversation refinement.
        mutator: StructuralMutator for section-level restructuring.
        selector: BoltzmannSelector for parent selection.
        cost_tracker: Shared CostTracker for budget enforcement across islands.
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
        self._cost_tracker = cost_tracker
        self._original_template = original_template
        self._anchor_variables = anchor_variables
        self._collector = collector
        self._event_callback = event_callback
        self._current_generation: int = 0  # Tracked for _reset_islands

        # Create per-island EvolutionLoop instances for step_generation() delegation.
        # Each loop is a distinct instance so _seed_results state is isolated,
        # but they share services (evaluator, rcc, mutator, selector, cost_tracker,
        # collector, event_callback) since those are either stateless or concurrency-safe.
        self._loops: list[EvolutionLoop] = [
            EvolutionLoop(
                config=config,
                evaluator=evaluator,
                rcc=rcc,
                mutator=mutator,
                selector=selector,
                cost_tracker=cost_tracker,
                original_template=original_template,
                anchor_variables=anchor_variables,
                cases=cases,
                target_model=target_model,
                generation_config=generation_config,
                prompt_tools=prompt_tools,
                purpose=purpose,
                collector=collector,
                event_callback=event_callback,
            )
            for _ in range(config.n_islands)
        ]

        # Per-island populations (initialized in run())
        self._island_populations: list[list[Candidate]] = [[] for _ in range(config.n_islands)]

        # Store evaluation dependencies for seed evaluation
        self._cases = cases
        self._expected_case_ids = {case.id for case in cases}
        self._target_model = target_model
        self._generation_config = generation_config
        self._prompt_tools = prompt_tools
        self._purpose = purpose

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event via the callback, if one is registered."""
        if self._event_callback is not None:
            await self._event_callback(event_type, data)

    async def _evaluate_candidate_full(self, candidate: Candidate) -> Candidate:
        report = await self._evaluator.evaluate(
            template=candidate.template,
            cases=self._cases,
            target_model=self._target_model,
            generation_config=self._generation_config,
            prompt_tools=self._prompt_tools,
            purpose=self._purpose,
        )
        if not is_full_report(report, self._expected_case_ids):
            raise EvaluationInvalidError("Candidate evaluation did not cover every case exactly")
        return self._attach_full_report(candidate, report)

    @staticmethod
    def _attach_full_report(candidate: Candidate, report: EvaluationReport) -> Candidate:
        candidate.fitness_score = report.fitness.score
        candidate.normalized_score = report.fitness.normalized_score
        candidate.rejected = report.fitness.rejected
        candidate.evaluation = report
        return candidate

    async def _initialize_populations(self, seed_candidate: Candidate) -> bool:
        """Build profile-specific populations containing exact full reports only."""
        candidates_by_island = [[seed_candidate] for _ in range(self._config.n_islands)]
        budget_exhausted = False

        if self._config.evolution_profile == "paper_reference":
            shared = [seed_candidate]

            async def evaluate_and_keep(draft: Candidate) -> Candidate:
                draft = await self._evaluate_candidate_full(draft)
                draft.parent_ids = [seed_candidate.id]
                shared.append(draft)
                return draft

            for conversation in range(self._config.conversations_per_island):
                try:
                    drafts = await self._rcc.run_conversation(
                        parents=[seed_candidate],
                        original_template=self._original_template,
                        anchor_variables=self._anchor_variables,
                        purpose=self._purpose,
                        rcc_rounds=self._config.rcc_rounds,
                        generation=0,
                        evaluate_draft=evaluate_and_keep,
                    )
                except BudgetExhaustedError:
                    budget_exhausted = True
                    break
                if len(drafts) != self._config.rcc_rounds:
                    raise EvaluationInvalidError(
                        f"Paper initialization conversation {conversation} returned "
                        f"{len(drafts)} of {self._config.rcc_rounds} evaluated rounds"
                    )
            candidates_by_island = [shared for _ in range(self._config.n_islands)]
        else:
            accepted_templates = {canonicalize_template(seed_candidate.template)}
            accepted_variant_count = 0
            for variant_index in range(self._config.n_seed_variants):
                if self._budget_exceeded():
                    budget_exhausted = True
                    break
                try:
                    drafts = await self._rcc.run_conversation(
                        parents=[seed_candidate],
                        original_template=self._original_template,
                        anchor_variables=self._anchor_variables,
                        purpose=self._purpose,
                        rcc_rounds=1,
                        generation=0,
                    )
                    if not drafts:
                        continue
                    variant = drafts[-1]
                    canonical = canonicalize_template(variant.template)
                    if canonical in accepted_templates:
                        continue
                    variant.parent_ids = [seed_candidate.id]
                    variant = await self._evaluate_candidate_full(variant)
                    variant.parent_ids = [seed_candidate.id]
                    candidates_by_island[
                        accepted_variant_count % self._config.n_islands
                    ].append(variant)
                    accepted_templates.add(canonical)
                    accepted_variant_count += 1
                except BudgetExhaustedError:
                    budget_exhausted = True
                    break
                except Exception:
                    logger.warning(
                        "Seed variant %d generation failed", variant_index, exc_info=True
                    )

        for island, candidates in enumerate(candidates_by_island):
            self._island_populations[island] = []
            for candidate in candidates:
                if not self._is_full_candidate(candidate):
                    raise EvaluationInvalidError(
                        "Initial population candidate lacks an exact full evaluation"
                    )
                clone = candidate.model_copy(deep=True)
                if not candidate.parent_ids:
                    clone.parent_ids = [candidate.id]
                clone.id = str(uuid.uuid4())
                self._island_populations[island].append(clone)
                mutation = "seed" if not candidate.parent_ids else "seed_variant"
                clone_report = clone.evaluation
                assert clone_report is not None
                if self._collector is not None:
                    self._collector.record(
                        LineageEvent(
                            candidate_id=clone.id,
                            parent_ids=clone.parent_ids,
                            generation=0,
                            island=island,
                            fitness_score=clone.fitness_score,
                            normalized_score=clone.normalized_score,
                            rejected=clone.rejected,
                            mutation_type=mutation,
                            template=clone.template,
                        )
                    )
                await self._emit(
                    "candidate_evaluated",
                    {
                        "generation": 0,
                        "island": island,
                        "candidate_id": clone.id,
                        "fitness_score": clone.fitness_score,
                        "normalized_score": clone.normalized_score,
                        "rejected": clone.rejected,
                        "mutation_type": mutation,
                        "parent_ids": clone.parent_ids,
                        "template": clone.template,
                        "cases_passed": sum(
                            result.passed for result in clone_report.case_results
                        ),
                        "total_cases": clone_report.total_cases,
                    },
                )
        return budget_exhausted

    async def _finalize(
        self,
        best_candidate: Candidate,
        generation_records: list[GenerationRecord],
        termination_reason: str,
        seed_report: EvaluationReport,
    ) -> EvolutionResult:
        """Emit the single terminal event and return the matching result."""
        total_cost = self._cost_tracker.summary()
        await self._emit(
            "evolution_complete",
            {
                "termination_reason": termination_reason,
                "best_fitness": best_candidate.fitness_score,
                "best_normalized": best_candidate.normalized_score,
                "total_cost_usd": total_cost.get("total_cost_usd", 0.0),
                "generations_completed": len(generation_records),
            },
        )
        return EvolutionResult(
            best_candidate=best_candidate,
            generation_records=generation_records,
            total_cost=total_cost,
            termination_reason=termination_reason,
            seed_evaluation=seed_report,
        )

    async def run(self) -> EvolutionResult:
        """Execute multi-island evolution with migration and reset.

        1. Evaluate seed candidate ONCE (Pitfall 6 prevention).
        2. Clone seed into all N island populations.
        3. Generation loop with per-island step_generation(), migration, reset.
        4. Return EvolutionResult with global best and aggregate records.

        Returns:
            EvolutionResult with the best candidate across all islands,
            aggregate generation records, total cost, and termination reason.
        """
        # 1. Evaluate seed candidate once
        seed_candidate = Candidate(
            template=self._original_template,
            generation=0,
            parent_ids=[],
        )
        seed_candidate = await self._evaluate_candidate_full(seed_candidate)
        assert seed_candidate.evaluation is not None
        seed_report = seed_candidate.evaluation

        # Inject seed results for sampling decisions on ALL per-island loops
        for loop in self._loops:
            loop.set_seed_results(seed_report.case_results)

        # Record seed lineage event (so DiffViewer can trace back to origin)
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

        # Emit seed evaluation event so the dashboard updates in real-time
        await self._emit(
            "candidate_evaluated",
            {
                "generation": 0,
                "island": 0,
                "candidate_id": seed_candidate.id,
                "fitness_score": seed_candidate.fitness_score,
                "normalized_score": seed_candidate.normalized_score,
                "rejected": seed_candidate.rejected,
                "mutation_type": "seed",
                "parent_ids": seed_candidate.parent_ids,
                "template": seed_candidate.template,
                "cases_passed": sum(result.passed for result in seed_report.case_results),
                "total_cases": seed_report.total_cases,
            },
        )

        # 2. Check early termination on a fully evaluated, feasible seed.
        if self._is_perfect(seed_candidate):
            return await self._finalize(
                seed_candidate, [], "perfect_fitness", seed_report
            )

        # 3. Build profile-specific, fully evaluated island populations.
        initialization_budget_exhausted = await self._initialize_populations(seed_candidate)

        initialized_best = self._best_live_candidate()
        if initialization_budget_exhausted:
            return await self._finalize(
                initialized_best or seed_candidate, [], "budget_exhausted", seed_report
            )
        if initialized_best is not None and self._is_perfect(initialized_best):
            return await self._finalize(
                initialized_best, [], "perfect_fitness", seed_report
            )

        # 4. Generation loop
        best_global = initialized_best or seed_candidate
        generation_records: list[GenerationRecord] = []
        termination_reason = "generations_complete"

        for gen in range(self._config.generations):
            # Budget check at generation boundary
            if self._budget_exceeded():
                termination_reason = "budget_exhausted"
                logger.info("Budget exhausted before generation %d", gen)
                break

            # Track current generation for _reset_islands
            self._current_generation = gen + 1

            # Emit generation_started event (1-indexed for frontend)
            await self._emit(
                "generation_started",
                {
                    "generation": gen + 1,
                    "island_count": self._config.n_islands,
                },
            )

            island_records: list[GenerationRecord] = []
            gen_terminated = False

            # Process all islands in parallel via asyncio.gather.
            # Each island's step_generation is I/O-bound (LLM API calls),
            # so concurrent execution reduces wall-clock time by ~N.
            cost_before_generation = self._cost_tracker.summary()
            tasks = [
                self._loops[island_idx].step_generation(
                    population=self._island_populations[island_idx],
                    generation=gen,
                    island=island_idx,
                )
                for island_idx in range(self._config.n_islands)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            cost_after_generation = self._cost_tracker.summary()
            generation_cost = {
                key: cost_after_generation[key] - cost_before_generation[key]
                for key in cost_after_generation
            }

            # Process every settled result so a sibling failure cannot hide an improvement.
            errors: list[BaseException] = []
            step_reasons: list[str] = []
            for island_idx, result in enumerate(results):
                if isinstance(result, BudgetExhaustedError):
                    step_reasons.append("budget_exhausted")
                    continue
                if isinstance(result, GatewayError):
                    logger.error(
                        "Island %d gen %d: %s -- terminating",
                        island_idx,
                        gen,
                        result,
                    )
                    errors.append(result)
                    continue
                elif isinstance(result, BaseException):
                    logger.error(
                        "Island %d gen %d unexpected error: %s",
                        island_idx,
                        gen,
                        result,
                    )
                    errors.append(result)
                    continue

                population, record, step_reason = result
                self._island_populations[island_idx] = [
                    candidate for candidate in population if self._is_full_candidate(candidate)
                ]
                island_records.append(record)
                if step_reason is not None:
                    step_reasons.append(step_reason)

            best_global = self._best_live_candidate() or best_global
            if errors:
                termination_reason = "error"
                gen_terminated = True
            elif self._is_perfect(best_global):
                termination_reason = "perfect_fitness"
                gen_terminated = True
            elif "budget_exhausted" in step_reasons:
                termination_reason = "budget_exhausted"
                gen_terminated = True

            # Cyclic migration (after all islands complete this generation)
            if not gen_terminated:
                self._migrate()
                await self._emit(
                    "migration",
                    {
                        "generation": gen + 1,
                        "emigrants_per_island": self._config.n_emigrate,
                    },
                )
                # Cap populations after migration
                self._select_survivors_all()

            # Reset after completed generations 3/6/9, never after the final one.
            completed_generation = gen + 1
            if (
                not gen_terminated
                and self._config.reset_interval > 0
                and completed_generation % self._config.reset_interval == 0
                and completed_generation < self._config.generations
            ):
                try:
                    await self._reset_islands()
                except BudgetExhaustedError:
                    termination_reason = "budget_exhausted"
                    gen_terminated = True

            best_global = self._best_live_candidate() or best_global

            # Aggregate generation record
            if island_records:
                agg = self._aggregate_records(
                    island_records, generation_cost, best_candidate=best_global
                )
                generation_records.append(agg)

                # Emit generation_complete event (1-indexed for frontend)
                await self._emit(
                    "generation_complete",
                    {
                        "generation": gen + 1,
                        "best_fitness": agg.best_fitness,
                        "avg_fitness": agg.avg_fitness,
                        "best_normalized": agg.best_normalized,
                        "avg_normalized": agg.avg_normalized,
                        "candidates_evaluated": agg.candidates_evaluated,
                        "cost_usd": agg.cost_summary.get("total_cost_usd", 0.0),
                    },
                )

            if gen_terminated:
                break

        best_global = self._best_live_candidate() or best_global
        return await self._finalize(
            best_global, generation_records, termination_reason, seed_report
        )

    def _migrate(self) -> None:
        """Perform cyclic migration: top n_emigrate from island i -> island (i+1) % n.

        Skips if n_emigrate <= 0 or n_islands <= 1.
        Collects emigrants from all islands BEFORE modifying any (prevents order-dependence).
        Uses model_copy(deep=True) to prevent shared state between islands.
        """
        if self._config.n_emigrate <= 0 or self._config.n_islands <= 1:
            return

        n = self._config.n_islands

        # Collect exact-full emigrants before modifying any population.
        emigrants: list[list[Candidate]] = []
        for pop in self._island_populations:
            sorted_pop = sorted(
                (candidate for candidate in pop if self._is_full_candidate(candidate)),
                key=self._candidate_sort_key,
            )
            top = sorted_pop[: self._config.n_emigrate]
            emigrants.append([c.model_copy(deep=True) for c in top])

        # Inject emigrants into next island cyclically
        for i in range(n):
            target = (i + 1) % n
            for emigrant in emigrants[i]:
                original_id = emigrant.id
                emigrant.id = str(uuid.uuid4())
                emigrant.parent_ids = [original_id]
                self._island_populations[target].append(emigrant)
                if self._collector is not None:
                    self._collector.record(
                        LineageEvent(
                            candidate_id=emigrant.id,
                            parent_ids=[original_id],
                            generation=emigrant.generation,
                            island=target,
                            fitness_score=emigrant.fitness_score,
                            normalized_score=emigrant.normalized_score,
                            rejected=emigrant.rejected,
                            mutation_type="migrated",
                            template=emigrant.template,
                        )
                    )

        logger.info(
            "Migration complete: up to %d candidates moved per island",
            self._config.n_emigrate,
        )

    def _select_survivors_all(self) -> None:
        """Apply population cap to all islands after migration.

        Delegates to EvolutionLoop._select_survivors() for each island,
        preventing unbounded population growth from migration.
        """
        for i in range(len(self._island_populations)):
            self._island_populations[i] = self._loops[0]._select_survivors(
                [
                    candidate
                    for candidate in self._island_populations[i]
                    if self._is_full_candidate(candidate)
                ]
            )

    async def _reset_islands(self) -> None:
        """Replace lowest-performing islands with top global candidates.

        - n_reset capped at n_islands - 1 (never reset all islands)
        - Mean fitness per island computed from all candidates
        - Skips if no global candidates exist (Pitfall 4)
        - Uses model_copy(deep=True) for replacement candidates
        """
        n_reset = min(self._config.n_reset, self._config.n_islands - 1)
        if n_reset <= 0:
            return

        # Compute mean fitness from eligible candidates only.
        island_means: list[tuple[int, float]] = []
        for i, pop in enumerate(self._island_populations):
            eligible = [candidate for candidate in pop if self._is_full_candidate(candidate)]
            mean_f = (
                statistics.mean(c.fitness_score for c in eligible)
                if eligible
                else float("-inf")
            )
            island_means.append((i, mean_f))

        # Sort ascending by mean fitness (worst/most negative first)
        island_means.sort(key=lambda x: x[1])

        # Keep the top 15 exact-full, distinct candidates for reset selection.
        ranked = sorted(
            (
                candidate
                for pop in self._island_populations
                for candidate in pop
                if self._is_full_candidate(candidate)
            ),
            key=self._candidate_sort_key,
        )
        pool: list[Candidate] = []
        seen_templates: set[str] = set()
        for candidate in ranked:
            canonical = canonicalize_template(candidate.template)
            if canonical in seen_templates:
                continue
            seen_templates.add(canonical)
            pool.append(candidate)
            if len(pool) == 15:
                break

        target = min(self._config.n_top, len(pool))
        top_global = pool[:target]
        if self._config.evolution_profile == "paper_reference" and target:
            selected = await self._rcc.select_diverse(pool, target)
            pool_ids = {candidate.id for candidate in pool}
            selected_ids = [candidate.id for candidate in selected]
            feasible_target = min(target, sum(not candidate.rejected for candidate in pool))
            if (
                len(selected) == target
                and len(set(selected_ids)) == target
                and all(candidate_id in pool_ids for candidate_id in selected_ids)
                and sum(not candidate.rejected for candidate in selected) == feasible_target
            ):
                top_global = selected

        if not top_global:
            logger.warning("No global candidates for island reset; skipping")
            return

        # Replace worst islands
        for i in range(n_reset):
            island_idx = island_means[i][0]
            new_pop = []
            for c in top_global:
                clone = c.model_copy(deep=True)
                source_id = clone.id
                clone.id = str(uuid.uuid4())
                clone.parent_ids = [source_id]
                new_pop.append(clone)
                if self._collector is not None:
                    self._collector.record(
                        LineageEvent(
                            candidate_id=clone.id,
                            parent_ids=[source_id],
                            generation=clone.generation,
                            island=island_idx,
                            fitness_score=clone.fitness_score,
                            normalized_score=clone.normalized_score,
                            rejected=clone.rejected,
                            mutation_type="reset",
                            template=clone.template,
                        )
                    )
            self._island_populations[island_idx] = new_pop
            logger.info(
                "Reset island %d (mean fitness %.3f) with %d top global candidates",
                island_idx,
                island_means[i][1],
                len(top_global),
            )

        # Emit island_reset event with list of reset island indices
        await self._emit(
            "island_reset",
            {
                "generation": self._current_generation,
                "islands_reset": [island_means[i][0] for i in range(n_reset)],
            },
        )

    @staticmethod
    def _aggregate_records(
        island_records: list[GenerationRecord],
        cost_summary: dict[str, float],
        best_candidate: Candidate | None = None,
    ) -> GenerationRecord:
        """Create an aggregate GenerationRecord from per-island records.

        - best_fitness: max across all islands
        - avg_fitness: mean of island avg_fitnesses
        - candidates_evaluated: sum across all islands
        - cost_summary: one non-overlapping shared-tracker delta
        """
        best_fitness = (
            best_candidate.fitness_score
            if best_candidate is not None
            else max(r.best_fitness for r in island_records)
        )
        avg_fitness = statistics.mean(r.avg_fitness for r in island_records)
        best_normalized = (
            best_candidate.normalized_score
            if best_candidate is not None
            else max(r.best_normalized for r in island_records)
        )
        avg_normalized = statistics.mean(r.avg_normalized for r in island_records)
        candidates_evaluated = sum(r.candidates_evaluated for r in island_records)

        return GenerationRecord(
            generation=island_records[0].generation,
            best_fitness=best_fitness,
            avg_fitness=avg_fitness,
            best_normalized=best_normalized,
            avg_normalized=avg_normalized,
            cost_summary=cost_summary,
            candidates_evaluated=candidates_evaluated,
        )

    def _is_full_candidate(self, candidate: Candidate) -> bool:
        return candidate.evaluation is not None and is_full_report(
            candidate.evaluation, self._expected_case_ids
        )

    @staticmethod
    def _candidate_sort_key(candidate: Candidate) -> tuple[bool, float]:
        return candidate.rejected, -candidate.fitness_score

    def _best_live_candidate(self) -> Candidate | None:
        eligible = [
            candidate
            for population in self._island_populations
            for candidate in population
            if self._is_full_candidate(candidate)
        ]
        return min(eligible, key=self._candidate_sort_key) if eligible else None

    def _is_perfect(self, candidate: Candidate) -> bool:
        report = candidate.evaluation
        return bool(
            report is not None
            and self._is_full_candidate(candidate)
            and not candidate.rejected
            and candidate.fitness_score == 0.0
            and report.case_results
            and all(result.passed for result in report.case_results)
        )

    def _budget_exceeded(self) -> bool:
        """Check if the cost tracker total exceeds the configured budget cap.

        Returns False if no budget cap is configured.
        """
        if self._config.budget_cap_usd is None:
            return False
        return self._cost_tracker.summary()["total_cost_usd"] >= self._config.budget_cap_usd
