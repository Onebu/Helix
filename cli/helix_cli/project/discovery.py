"""Discover prompt directories in a workspace."""

from __future__ import annotations

from pathlib import Path

import yaml


def find_prompts(workspace: Path) -> list[dict]:
    """Find all prompt directories (containing prompt.yaml) in the workspace."""
    prompts = []
    for child in sorted(workspace.iterdir()):
        try:
            if not child.is_dir():
                continue
            prompt_file = child / "prompt.yaml"
            if not prompt_file.exists():
                continue
        except PermissionError:
            continue
        try:
            data = yaml.safe_load(prompt_file.read_text(encoding="utf-8")) or {}
        except Exception:
            continue

        # Count test cases
        dataset_file = child / "dataset.yaml"
        test_cases = 0
        if dataset_file.exists():
            try:
                ds = yaml.safe_load(dataset_file.read_text(encoding="utf-8")) or {}
                test_cases = len(ds.get("cases", []))
            except Exception:
                pass

        # Count results
        results_dir = child / "results"
        results_count = 0
        if results_dir.is_dir():
            results_count = len(list(results_dir.glob("run-*.yaml")))

        prompts.append({
            "id": data.get("id", child.name),
            "purpose": data.get("purpose", ""),
            "path": str(child),
            "test_cases": test_cases,
            "has_config": (child / "config.yaml").exists(),
            "results_count": results_count,
        })
    return prompts


def resolve_prompt_dir(workspace: Path, prompt_id: str) -> Path:
    """Resolve a prompt ID to its directory path, raising if not found."""
    prompt_dir = workspace / prompt_id
    if not prompt_dir.is_dir() or not (prompt_dir / "prompt.yaml").exists():
        raise FileNotFoundError(
            f"Prompt '{prompt_id}' not found. "
            f"Expected {prompt_dir}/prompt.yaml to exist. "
            f"Run 'helix init {prompt_id}' first."
        )
    return prompt_dir
