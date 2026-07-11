"""Value objects and guards for ephemeral candidate scouting."""

from __future__ import annotations

from dataclasses import dataclass

from api.evaluation.models import EvaluationReport
from api.evolution.models import Candidate


def canonicalize_template(template: str) -> str:
    """Normalize insignificant outer and line-ending whitespace."""
    return "\n".join(line.rstrip() for line in template.strip().splitlines())


def is_full_report(report: EvaluationReport, expected_case_ids: set[str]) -> bool:
    """Return whether a report covers every expected case ID exactly."""
    case_results = report.case_results
    result_ids = [result.case_id for result in case_results]
    expected_count = len(expected_case_ids)
    return (
        len(case_results) == report.total_cases == expected_count
        and len(set(result_ids)) == len(result_ids)
        and set(result_ids) == expected_case_ids
    )


@dataclass(frozen=True, slots=True)
class ScoutResult:
    """A partial report kept separate from candidate fitness state."""

    candidate: Candidate
    report: EvaluationReport
