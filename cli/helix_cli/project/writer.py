"""Write evolution results to YAML files."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from api.evolution.models import EvolutionResult


def write_result(prompt_dir: Path, result: EvolutionResult, config_snapshot: dict) -> Path:
    """Write an EvolutionResult to results/run-NNN.yaml. Returns the file path."""
    results_dir = prompt_dir / "results"
    results_dir.mkdir(exist_ok=True)

    # Compute next run number
    existing = list(results_dir.glob("run-*.yaml"))
    max_num = 0
    for f in existing:
        m = re.match(r"run-(\d+)\.yaml", f.name)
        if m:
            max_num = max(max_num, int(m.group(1)))
    run_num = max_num + 1
    run_id = f"run-{run_num:03d}"

    # Build result dict
    data = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "termination_reason": result.termination_reason,
        "best_template": result.best_candidate.template,
        "fitness": {
            "score": result.best_candidate.fitness_score,
            "normalized_score": result.best_candidate.normalized_score,
        },
        "cost": result.total_cost,
        "effective_models": result.effective_models,
        "generation_records": [
            {
                "generation": rec.generation,
                "best_fitness": rec.best_fitness,
                "avg_fitness": rec.avg_fitness,
                "candidates_evaluated": rec.candidates_evaluated,
            }
            for rec in result.generation_records
        ],
        "config_snapshot": config_snapshot,
    }

    if result.seed_evaluation:
        data["seed_fitness"] = result.seed_evaluation.fitness.score

    path = results_dir / f"{run_id}.yaml"
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def read_latest_result(prompt_dir: Path) -> dict | None:
    """Read the most recent run result, or None if no results exist."""
    results_dir = prompt_dir / "results"
    if not results_dir.is_dir():
        return None

    files = sorted(results_dir.glob("run-*.yaml"), reverse=True)
    if not files:
        return None

    return yaml.safe_load(files[0].read_text(encoding="utf-8"))


def read_result(prompt_dir: Path, run_id: str) -> dict | None:
    """Read a specific run result by ID."""
    path = prompt_dir / "results" / f"{run_id}.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))
