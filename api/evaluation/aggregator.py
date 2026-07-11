"""Penalty-based fitness aggregator with tier multipliers.

Implements the penalty-based scoring model per the MindEvolution paper:
- Perfect fitness = 0.0 (no penalties, ceiling)
- Every violation adds a negative penalty
- Critical cases multiply their penalty by critical_multiplier (default 5.0)
- Normal cases keep their penalty as-is (multiplier 1.0)
- Low cases multiply their penalty by low_multiplier (default 0.25)

Total fitness = sum of all tier-weighted penalties. 0.0 = perfect.
"""

from api.evaluation.models import CaseResult, EvaluationInvalidError, FitnessScore


class FitnessAggregator:
    """Aggregates per-case penalty scores into an overall fitness score.

    Uses tier multipliers where critical cases amplify penalties and
    low-priority cases dampen them, giving a smooth fitness landscape.

    Attributes:
        critical_multiplier: Multiplier for critical-tier penalties (default 5.0).
        normal_multiplier: Multiplier for normal-tier penalties (default 1.0).
        low_multiplier: Multiplier for low-tier penalties (default 0.25).
    """

    def __init__(
        self,
        critical_multiplier: float = 5.0,
        normal_multiplier: float = 1.0,
        low_multiplier: float = 0.25,
    ) -> None:
        self.critical_multiplier = critical_multiplier
        self.normal_multiplier = normal_multiplier
        self.low_multiplier = low_multiplier

    def aggregate(self, results: list[CaseResult]) -> FitnessScore:
        """Compute aggregate fitness from individual case penalty scores.

        Args:
            results: List of per-case evaluation results (scores <= 0).

        Returns:
            FitnessScore with summed tier-weighted penalties and semantic rejection.

        Raises:
            EvaluationInvalidError: If no case results were produced.
        """
        if not results:
            raise EvaluationInvalidError("Evaluation produced no case results")

        # Sum all case penalties with tier multipliers, and compute max possible penalty
        total = 0.0
        max_possible = 0.0
        for result in results:
            tier = result.tier.lower()
            if tier == "critical":
                multiplier = self.critical_multiplier
            elif tier == "low":
                multiplier = self.low_multiplier
            else:
                # "normal" and any unrecognized tier use normal_multiplier
                multiplier = self.normal_multiplier

            # Phase 33: halve multiplier for synthetic test cases (SYNTH-07)
            if result.synthetic:
                multiplier *= 0.5

            total += result.score * multiplier
            expected = result.expected or {}
            raw_behavior = expected.get("behavior", [])
            behavior_count = 1 if isinstance(raw_behavior, str) else len(raw_behavior or [])
            exact_count = 1 if expected.get("tool_calls") else 0
            max_penalty = 2 * (exact_count + behavior_count) or 2
            max_possible += -max_penalty * multiplier

        # Normalize: total / abs(max_possible), clamped to [-1.0, 0.0] range
        normalized = total / abs(max_possible) if max_possible != 0 else 0.0
        normalized = max(-1.0, min(0.0, normalized))

        failed_critical = [
            result.case_id
            for result in results
            if result.tier.lower() == "critical" and not result.passed
        ]
        rejected = bool(failed_critical)
        reason = (
            f"Critical case failed: {', '.join(failed_critical)}"
            if failed_critical
            else None
        )

        return FitnessScore(
            score=total,
            normalized_score=normalized,
            rejected=rejected,
            rejection_reason=reason,
            case_results=results,
        )
