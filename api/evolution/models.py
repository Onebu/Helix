"""Evolution data models for the prompt optimization pipeline.

Defines the core value objects used throughout the evolution sub-package:
- Candidate: an evolved prompt template with its fitness evaluation
- EvolutionConfig: hyperparameters with Helix profile defaults and paper-inspired adaptations
- GenerationRecord: per-generation metrics
- EvolutionResult: final evolution output with termination reason
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from api.evaluation.models import EvaluationReport
from api.types import OTelAttributes

EvolutionProfile = Literal["cost_controlled", "paper_reference"]


class Candidate(BaseModel):
    """An evolved prompt candidate with its fitness evaluation.

    Candidates are immutable value objects -- create new instances
    rather than mutating in place to preserve lineage tracking.

    Attributes:
        id: Unique identifier (auto-generated UUID string).
        template: The Jinja2 prompt template text.
        fitness_score: Aggregate fitness score (<= 0.0). 0.0 = perfect, negative = penalized.
        rejected: Deprecated: use score magnitude instead. Kept for backward compat
            with frontend/lineage serialization.
        evaluation: Full evaluation report, if evaluated.
        generation: Which generation this candidate was created in.
        parent_ids: IDs of parent candidates used to produce this one.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    template: str
    fitness_score: float = 0.0
    normalized_score: float = 0.0
    rejected: bool = False
    evaluation: EvaluationReport | None = None
    generation: int = 0
    parent_ids: list[str] = Field(default_factory=list)
    otel: OTelAttributes | None = None


class EvolutionConfig(BaseModel):
    """Hyperparameters for the evolution loop.

    The default profile controls costs for API users. The paper-reference
    profile restores larger values where the public API does not override them.

    Attributes:
        generations: Number of evolution generations to run (>= 1).
        conversations_per_island: Number of RCC conversations per generation (>= 1).
        rcc_rounds: Number of RCC refinement rounds per conversation (>= 1).
        n_parents: Number of parents selected per conversation (>= 0).
        temperature: Boltzmann selection temperature (> 0). Higher = more random.
        structural_mutation_probability: Probability of structural mutation per conversation [0, 1].
        pr_no_parents: Probability of generating from scratch (no parents) [0, 1].
        budget_cap_usd: Pre-call scheduling budget cap in USD; None means no limit.
        population_cap: Maximum population size per island.
        n_islands: Number of islands for island model evolution (>= 1).
        n_emigrate: Number of top candidates to emigrate between islands per migration (>= 0).
        reset_interval: Generations between island resets (>= 0, where 0 means no resets).
        n_reset: Number of worst islands to reset per reset event (>= 0).
        n_top: Number of top candidates to preserve during island reset (>= 1).
    """

    evolution_profile: EvolutionProfile = "cost_controlled"
    generations: int = 10
    conversations_per_island: int = 5
    rcc_rounds: int = Field(
        default=3,
        validation_alias=AliasChoices("rcc_rounds", "n_seq"),
    )
    retain_intermediate_children: bool = False
    max_retries: int = 3
    promotions_per_island: int = 1
    n_parents: int = 5
    temperature: float = 1.0
    structural_mutation_probability: float = 0.2
    pr_no_parents: float = Field(default=1 / 6)
    budget_cap_usd: float | None = None
    population_cap: int | None = 10

    # Island model fields (Mind Evolution paper defaults)
    n_islands: int = 4
    n_emigrate: int = 5
    reset_interval: int = 3
    n_reset: int = 2
    n_top: int = 5

    # Cost-controlled initialization variants; paper-reference uses shared sequential initialization.
    n_seed_variants: int = 3

    # Subset sampling fields
    sample_size: int | None = None
    sample_ratio: float | None = None

    # Adaptive sampling fields (EVO-04/05/06)
    adaptive_sampling: bool = False
    adaptive_decay_constant: float = 3.0
    adaptive_min_rate: float = 0.1
    checkpoint_interval: int = 3  # Full eval every N generations (0 = disabled)

    @model_validator(mode="after")
    def resolve_profile(self) -> EvolutionConfig:
        if self.evolution_profile != "paper_reference":
            return self
        if "rcc_rounds" not in self.model_fields_set:
            self.rcc_rounds = 4
        if "retain_intermediate_children" not in self.model_fields_set:
            self.retain_intermediate_children = True
        if "max_retries" not in self.model_fields_set:
            self.max_retries = 5
        if "population_cap" not in self.model_fields_set:
            self.population_cap = None
        return self

    @field_validator(
        "generations",
        "conversations_per_island",
        "rcc_rounds",
        "max_retries",
        "promotions_per_island",
        "population_cap",
        "n_islands",
        "n_top",
        "sample_size",
    )
    @classmethod
    def positive_integer(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("value must be >= 1")
        return v

    @field_validator(
        "n_parents",
        "n_emigrate",
        "reset_interval",
        "n_reset",
        "n_seed_variants",
        "checkpoint_interval",
    )
    @classmethod
    def non_negative_integer(cls, v: int) -> int:
        if v < 0:
            raise ValueError("value must be >= 0")
        return v

    @field_validator("budget_cap_usd")
    @classmethod
    def budget_cap_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("budget_cap_usd must be >= 0")
        return v

    @field_validator("temperature")
    @classmethod
    def temperature_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("temperature must be > 0")
        return v

    @field_validator("structural_mutation_probability")
    @classmethod
    def structural_mutation_in_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("structural_mutation_probability must be in [0.0, 1.0]")
        return v

    @field_validator("pr_no_parents")
    @classmethod
    def pr_no_parents_in_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("pr_no_parents must be in [0.0, 1.0]")
        return v

    @field_validator("sample_ratio")
    @classmethod
    def sample_ratio_in_range(cls, v: float | None) -> float | None:
        if v is not None and (v <= 0.0 or v > 1.0):
            raise ValueError("sample_ratio must be in (0.0, 1.0]")
        return v

    @field_validator("adaptive_decay_constant")
    @classmethod
    def adaptive_decay_constant_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("adaptive_decay_constant must be > 0")
        return v

    @field_validator("adaptive_min_rate")
    @classmethod
    def adaptive_min_rate_in_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("adaptive_min_rate must be in [0.0, 1.0]")
        return v


class GenerationRecord(BaseModel):
    """Metrics for a single generation of evolution.

    Attributes:
        generation: Generation number (0-indexed).
        best_fitness: Best fitness score in this generation.
        avg_fitness: Average fitness score across the population.
        cost_summary: Cost breakdown for this generation.
        candidates_evaluated: Number of candidates evaluated.
    """

    generation: int
    best_fitness: float
    avg_fitness: float
    best_normalized: float = 0.0
    avg_normalized: float = 0.0
    cost_summary: dict[str, Any] = Field(default_factory=dict)
    candidates_evaluated: int


class EvolutionResult(BaseModel):
    """Final output of an evolution run.

    Attributes:
        best_candidate: The highest-fitness candidate found.
        generation_records: Per-generation metrics.
        total_cost: Aggregate cost for the entire run.
        termination_reason: Why evolution stopped -- one of
            "perfect_fitness", "budget_exhausted", "generations_complete".
        seed_evaluation: Baseline evaluation of the seed prompt for regression analysis.
        lineage_events: Serialized lineage events (replaces monkey-patched attribute).
    """

    best_candidate: Candidate
    generation_records: list[GenerationRecord] = Field(default_factory=list)
    total_cost: dict[str, Any] = Field(default_factory=dict)
    termination_reason: str
    seed_evaluation: EvaluationReport | None = None
    lineage_events: list[dict[str, Any]] | None = None
    effective_models: dict[str, str] | None = None
