"""Load YAML project files into Helix domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml
from dotenv import load_dotenv
from jinja2 import Environment, meta

from api.config.models import GeneConfig, GenerationConfig
from api.dataset.models import PriorityTier, TestCase
from api.evolution.models import EvolutionConfig
from api.registry.models import PromptRecord, VariableDefinition

# PromptRecord uses forward refs (ToolSchemaDefinition, MockDefinition, PersonaProfile).
# Importing schemas.py triggers model_rebuild() which resolves them.
import api.registry.schemas  # noqa: F401

_jinja_env = Environment()


def _extract_anchor_variables(variable_defs: list[VariableDefinition]) -> set[str]:
    """Extract anchor variable names, including dot-notation for nested anchors."""
    anchors: set[str] = set()
    for v in variable_defs:
        if v.is_anchor:
            anchors.add(v.name)
        if v.items_schema:
            for sub in v.items_schema:
                if sub.is_anchor:
                    anchors.add(f"{v.name}.{sub.name}")
    return anchors


def load_prompt(prompt_dir: Path) -> PromptRecord:
    """Load prompt.yaml into a PromptRecord."""
    data = yaml.safe_load((prompt_dir / "prompt.yaml").read_text(encoding="utf-8"))
    if not data:
        raise ValueError(f"Empty prompt.yaml in {prompt_dir}")

    template = data.get("template", "")
    prompt_id = data.get("id", prompt_dir.name)
    purpose = data.get("purpose", "")

    # Extract template variables via Jinja2 AST
    ast = _jinja_env.parse(template)
    template_variables = meta.find_undeclared_variables(ast)

    # Build variable definitions
    explicit_vars = data.get("variables")
    if explicit_vars:
        variable_defs = [VariableDefinition(**v) for v in explicit_vars]
        # Add any template vars not covered by explicit definitions
        explicit_names = {v.name for v in variable_defs}
        for var_name in sorted(template_variables - explicit_names):
            variable_defs.append(VariableDefinition(name=var_name))
    else:
        variable_defs = [VariableDefinition(name=n) for n in sorted(template_variables)]

    anchor_variables = _extract_anchor_variables(variable_defs)

    return PromptRecord(
        id=prompt_id,
        purpose=purpose,
        template=template,
        template_variables=template_variables,
        anchor_variables=anchor_variables,
        commit_hash=None,
        created_at=datetime.now(UTC),
        tools=data.get("tools"),
        description=data.get("description"),
    )


def load_dataset(prompt_dir: Path) -> list[TestCase]:
    """Load dataset.yaml into a list of TestCase objects."""
    dataset_file = prompt_dir / "dataset.yaml"
    if not dataset_file.exists():
        return []

    data = yaml.safe_load(dataset_file.read_text(encoding="utf-8"))
    if not data:
        return []

    raw_cases = data.get("cases", [])
    cases = []
    for raw in raw_cases:
        tier_str = raw.get("tier", "normal")
        cases.append(
            TestCase(
                id=raw.get("id", str(uuid4())),
                name=raw.get("name"),
                description=raw.get("description"),
                chat_history=raw.get("chat_history", []),
                variables=raw.get("variables", {}),
                tools=raw.get("tools"),
                expected_output=raw.get("expected_output"),
                tier=PriorityTier(tier_str),
                tags=raw.get("tags", []),
            )
        )
    return cases


def load_config(
    prompt_dir: Path,
    *,
    cli_overrides: dict | None = None,
) -> tuple[GeneConfig, EvolutionConfig, dict]:
    """Load config.yaml and merge with env vars and CLI overrides.

    Returns (GeneConfig, EvolutionConfig, run_kwargs) where run_kwargs
    contains model/provider overrides and thinking_config for run_evolution().
    """
    load_dotenv()

    config_file = prompt_dir / "config.yaml"
    yaml_data: dict = {}
    if config_file.exists():
        yaml_data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}

    # Build GeneConfig overrides from YAML models section
    gene_overrides: dict = {}
    models_cfg = yaml_data.get("models", {})
    for role in ("meta", "target", "judge"):
        role_cfg = models_cfg.get(role, {})
        if "model" in role_cfg:
            gene_overrides[f"{role}_model"] = role_cfg["model"]
        if "provider" in role_cfg:
            gene_overrides[f"{role}_provider"] = role_cfg["provider"]

    # GeneConfig: constructor args > env vars > defaults
    config = GeneConfig(**gene_overrides)

    # Build GenerationConfig if present
    gen_yaml = yaml_data.get("generation", {})
    if gen_yaml:
        gen_config = GenerationConfig(**gen_yaml)
        config = config.model_copy(update={"generation": gen_config})

    # Build EvolutionConfig from YAML + CLI overrides
    evo_yaml = yaml_data.get("evolution", {})
    if "islands" in evo_yaml:
        evo_yaml["n_islands"] = evo_yaml.pop("islands")
    if cli_overrides:
        evo_yaml.update(cli_overrides)
    evo_config = EvolutionConfig(**evo_yaml)

    # Build run_evolution kwargs (model overrides, thinking)
    run_kwargs: dict = {}
    for role in ("meta", "target", "judge"):
        role_cfg = models_cfg.get(role, {})
        if "model" in role_cfg:
            run_kwargs[f"{role}_model"] = role_cfg["model"]
        if "provider" in role_cfg:
            run_kwargs[f"{role}_provider"] = role_cfg["provider"]

    # Thinking config
    thinking_config: dict = {}
    for role in ("meta", "target", "judge"):
        role_cfg = models_cfg.get(role, {})
        if "thinking_budget" in role_cfg and role_cfg["thinking_budget"] is not None:
            thinking_config[f"{role}_thinking_budget"] = role_cfg["thinking_budget"]
    if thinking_config:
        run_kwargs["thinking_config"] = thinking_config

    if gen_yaml:
        run_kwargs["generation_config"] = config.generation

    return config, evo_config, run_kwargs
