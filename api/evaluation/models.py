"""Shared Pydantic models for the evaluation sub-package.

These models define the contracts used by all evaluation components:
scorers, aggregator, regression checker, sampling, and the top-level evaluator.

CaseResult.tier uses a plain string ("critical", "normal", "low") rather than
importing PriorityTier from the dataset sub-package to avoid cross-package
dependency issues during parallel Wave 1 execution.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from api.types import OTelAttributes


class EvaluationInvalidError(ValueError):
    """Raised when an evaluation cannot produce trustworthy case results."""


class CaseResult(BaseModel):
    """Result of evaluating a single dataset case against an evolved prompt.

    Attributes:
        case_id: Unique identifier for the dataset case.
        tier: Priority tier as a string -- "critical", "normal", or "low".
        score: Numeric penalty for this case (<= 0). 0 = passed, negative = penalty.
        passed: Whether the case passed its evaluation criteria.
        reason: Human-readable explanation of the score/pass decision.
        expected: Expected output dictionary (ground truth), if applicable.
        actual_content: The LLM's text response for this case.
        actual_tool_calls: The LLM's tool calls for this case.
        criteria_results: Per-criterion evaluation details from BehaviorJudgeScorer.
            List of dicts with keys: criterion (str), passed (bool), reason (str).
            None when not applicable (e.g., ExactMatchScorer results).
    """

    case_id: str
    tier: str = "normal"
    score: float
    passed: bool = False
    reason: str = ""
    expected: dict[str, Any] | None = None
    actual_content: str | None = None
    actual_tool_calls: list[dict[str, Any]] | None = None
    criteria_results: list[dict[str, Any]] | None = None
    otel: OTelAttributes | None = None
    # Phase 33: synthetic flag -- True when test case has "synthetic" tag
    synthetic: bool = False


class FitnessScore(BaseModel):
    """Aggregate fitness score for an evolved prompt candidate.

    Penalty-based model: perfect = 0.0, violations produce negative scores.
    Score is the sum of tier-weighted penalties from all case results.

    Attributes:
        score: Overall fitness score (<= 0.0). 0.0 = perfect, negative = penalized.
        rejected: Whether any failed critical case makes the candidate infeasible.
        rejection_reason: Reason for rejection, if rejected.
        case_results: Individual case results that contributed to this score.
    """

    score: float
    normalized_score: float = 0.0
    rejected: bool = False
    rejection_reason: str | None = None
    case_results: list[CaseResult] = []


class EvaluationReport(BaseModel):
    """Full evaluation output for a prompt candidate.

    Attributes:
        fitness: The aggregate fitness score.
        case_results: All individual case results.
        total_cases: Total number of cases evaluated.
        cost_summary: Cost breakdown for the evaluation run.
    """

    fitness: FitnessScore
    case_results: list[CaseResult]
    total_cases: int
    cost_summary: dict[str, Any] = {}


class ValidationResult(BaseModel):
    """Result of validating that an evolved template preserves required variables.

    Attributes:
        valid: Whether all required variables are preserved.
        missing_variables: Variables present in original but missing from evolved.
        original_variables: All variables found in the original template.
        evolved_variables: All variables found in the evolved template.
        renamed_variables: Mapping of missing variable -> likely new name
            (detected by string similarity). Empty if no renames detected.
    """

    valid: bool
    missing_variables: list[str] = []
    original_variables: list[str] = []
    evolved_variables: list[str] = []
    renamed_variables: dict[str, str] = {}
