"""Tests for evolution data models: Candidate, EvolutionConfig, GenerationRecord, EvolutionResult."""

import uuid

import pytest
from pydantic import ValidationError

from api.evolution.models import (
    Candidate,
    EvolutionConfig,
    EvolutionResult,
    GenerationRecord,
)
from api.exceptions import BudgetExhaustedError, GenePrompterError

# --- Candidate Tests ---


class TestCandidate:
    """Tests for the Candidate model."""

    def test_candidate_creation_with_defaults(self):
        """Candidate should have sensible defaults for all optional fields."""
        c = Candidate(template="You are a helpful assistant.")
        assert c.template == "You are a helpful assistant."
        assert c.fitness_score == 0.0
        assert c.rejected is False
        assert c.evaluation is None
        assert c.generation == 0
        assert c.parent_ids == []

    def test_candidate_auto_generates_uuid_id(self):
        """Each Candidate should get a unique auto-generated UUID id."""
        c1 = Candidate(template="template1")
        c2 = Candidate(template="template2")
        # Both should have valid UUID strings
        uuid.UUID(c1.id)  # Raises if not valid UUID
        uuid.UUID(c2.id)
        # And they should be different
        assert c1.id != c2.id

    def test_candidate_with_explicit_id(self):
        """Candidate should accept an explicit id."""
        c = Candidate(id="custom-id-123", template="template")
        assert c.id == "custom-id-123"

    def test_candidate_with_all_fields(self):
        """Candidate should accept all fields including evaluation."""
        from api.evaluation.models import (
            CaseResult,
            EvaluationReport,
            FitnessScore,
        )

        report = EvaluationReport(
            fitness=FitnessScore(score=0.85),
            case_results=[CaseResult(case_id="c1", score=0.85)],
            total_cases=1,
        )
        c = Candidate(
            template="evolved template",
            fitness_score=0.85,
            rejected=False,
            evaluation=report,
            generation=3,
            parent_ids=["parent-1", "parent-2"],
        )
        assert c.fitness_score == 0.85
        assert c.generation == 3
        assert len(c.parent_ids) == 2
        assert c.evaluation is not None
        assert c.evaluation.fitness.score == 0.85


# --- EvolutionConfig Tests ---


class TestEvolutionConfig:
    """Tests for the EvolutionConfig model."""

    def test_cost_controlled_profile_is_explicit_default(self):
        config = EvolutionConfig()
        assert config.evolution_profile == "cost_controlled"
        assert config.rcc_rounds == 3
        assert config.retain_intermediate_children is False
        assert config.max_retries == 3
        assert config.promotions_per_island == 1
        assert config.population_cap == 10

    def test_paper_reference_profile_resolves_paper_scale(self):
        config = EvolutionConfig(evolution_profile="paper_reference")
        assert config.rcc_rounds == 4
        assert config.retain_intermediate_children is True
        assert config.max_retries == 5
        assert config.population_cap is None

    def test_paper_reference_profile_preserves_explicit_overrides(self):
        config = EvolutionConfig(
            evolution_profile="paper_reference",
            rcc_rounds=2,
            retain_intermediate_children=False,
            max_retries=1,
            population_cap=7,
        )
        assert config.rcc_rounds == 2
        assert config.retain_intermediate_children is False
        assert config.max_retries == 1
        assert config.population_cap == 7

    def test_legacy_n_seq_input_maps_to_rcc_rounds(self):
        config = EvolutionConfig.model_validate({"n_seq": 2})
        assert config.rcc_rounds == 2
        assert "n_seq" not in config.model_dump()

    def test_paper_reference_preserves_explicit_legacy_n_seq(self):
        config = EvolutionConfig.model_validate(
            {"evolution_profile": "paper_reference", "n_seq": 2}
        )
        assert config.rcc_rounds == 2

    def test_explicit_null_population_cap_is_preserved(self):
        config = EvolutionConfig(population_cap=None)
        assert config.population_cap is None

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("rcc_rounds", 0),
            ("max_retries", 0),
            ("promotions_per_island", 0),
            ("population_cap", 0),
            ("n_seed_variants", -1),
            ("budget_cap_usd", -0.01),
            ("sample_size", 0),
            ("sample_ratio", 0.0),
        ],
    )
    def test_positive_work_bounds(self, field, value):
        with pytest.raises(ValidationError):
            EvolutionConfig(**{field: value})

    def test_cost_controlled_defaults_preserve_existing_values(self):
        """The default profile preserves the existing cost-controlled values."""
        config = EvolutionConfig()
        assert config.generations == 10
        assert config.conversations_per_island == 5
        assert config.rcc_rounds == 3
        assert config.n_parents == 5
        assert config.temperature == 1.0
        assert config.structural_mutation_probability == 0.2
        assert abs(config.pr_no_parents - 1 / 6) < 0.001
        assert config.budget_cap_usd is None
        assert config.population_cap == 10

    def test_custom_config_values(self):
        """EvolutionConfig should accept custom values."""
        config = EvolutionConfig(
            generations=20,
            conversations_per_island=10,
            rcc_rounds=5,
            n_parents=3,
            temperature=0.5,
            structural_mutation_probability=0.3,
            pr_no_parents=0.25,
            budget_cap_usd=10.0,
            population_cap=20,
        )
        assert config.generations == 20
        assert config.budget_cap_usd == 10.0

    def test_validation_rejects_zero_generations(self):
        """generations must be >= 1."""
        with pytest.raises(ValidationError):
            EvolutionConfig(generations=0)

    def test_validation_rejects_negative_generations(self):
        """generations must be >= 1."""
        with pytest.raises(ValidationError):
            EvolutionConfig(generations=-1)

    def test_validation_rejects_zero_conversations(self):
        """conversations_per_island must be >= 1."""
        with pytest.raises(ValidationError):
            EvolutionConfig(conversations_per_island=0)

    def test_validation_rejects_zero_legacy_n_seq(self):
        """The n_seq compatibility input must be >= 1."""
        with pytest.raises(ValidationError):
            EvolutionConfig(n_seq=0)

    def test_validation_rejects_negative_n_parents(self):
        """n_parents must be >= 0."""
        with pytest.raises(ValidationError):
            EvolutionConfig(n_parents=-1)

    def test_validation_rejects_zero_temperature(self):
        """temperature must be > 0."""
        with pytest.raises(ValidationError):
            EvolutionConfig(temperature=0.0)

    def test_validation_rejects_negative_temperature(self):
        """temperature must be > 0."""
        with pytest.raises(ValidationError):
            EvolutionConfig(temperature=-0.5)

    def test_validation_rejects_mutation_probability_out_of_range(self):
        """structural_mutation_probability must be in [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            EvolutionConfig(structural_mutation_probability=-0.1)
        with pytest.raises(ValidationError):
            EvolutionConfig(structural_mutation_probability=1.1)

    def test_validation_rejects_pr_no_parents_out_of_range(self):
        """pr_no_parents must be in [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            EvolutionConfig(pr_no_parents=-0.1)
        with pytest.raises(ValidationError):
            EvolutionConfig(pr_no_parents=1.1)

    def test_validation_allows_zero_n_parents(self):
        """n_parents=0 is valid (always generate from scratch)."""
        config = EvolutionConfig(n_parents=0)
        assert config.n_parents == 0

    def test_validation_allows_boundary_values(self):
        """Boundary values should be accepted."""
        config = EvolutionConfig(
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        )
        assert config.structural_mutation_probability == 0.0
        assert config.pr_no_parents == 0.0

        config2 = EvolutionConfig(
            structural_mutation_probability=1.0,
            pr_no_parents=1.0,
        )
        assert config2.structural_mutation_probability == 1.0
        assert config2.pr_no_parents == 1.0

    # --- Island Model Config Tests ---

    def test_island_config_defaults_match_paper(self):
        """Island model defaults should match Mind Evolution paper values."""
        config = EvolutionConfig()
        assert config.n_islands == 4
        assert config.n_emigrate == 5
        assert config.reset_interval == 3
        assert config.n_reset == 2
        assert config.n_top == 5

    def test_island_config_custom_values(self):
        """Island model fields should accept custom values."""
        config = EvolutionConfig(
            n_islands=8,
            n_emigrate=3,
            reset_interval=5,
            n_reset=1,
            n_top=10,
        )
        assert config.n_islands == 8
        assert config.n_emigrate == 3
        assert config.reset_interval == 5
        assert config.n_reset == 1
        assert config.n_top == 10

    def test_island_config_validation_n_islands_at_least_one(self):
        """n_islands must be >= 1."""
        with pytest.raises(ValidationError):
            EvolutionConfig(n_islands=0)

    def test_island_config_validation_n_emigrate_non_negative(self):
        """n_emigrate must be >= 0."""
        with pytest.raises(ValidationError):
            EvolutionConfig(n_emigrate=-1)

    def test_island_config_validation_reset_interval_non_negative(self):
        """reset_interval must be >= 0 (0 means no resets)."""
        with pytest.raises(ValidationError):
            EvolutionConfig(reset_interval=-1)

    def test_island_config_validation_n_reset_non_negative(self):
        """n_reset must be >= 0."""
        with pytest.raises(ValidationError):
            EvolutionConfig(n_reset=-1)

    def test_island_config_validation_n_top_at_least_one(self):
        """n_top must be >= 1."""
        with pytest.raises(ValidationError):
            EvolutionConfig(n_top=0)

    def test_island_config_allows_zero_emigrate_and_reset(self):
        """n_emigrate=0 and n_reset=0 are valid (no migration/no resets)."""
        config = EvolutionConfig(n_emigrate=0, n_reset=0)
        assert config.n_emigrate == 0
        assert config.n_reset == 0

    # --- Sampling Config Tests ---

    def test_sampling_fields_default_to_none(self):
        """EvolutionConfig() should have sample_size=None, sample_ratio=None (backward compat)."""
        config = EvolutionConfig()
        assert config.sample_size is None
        assert config.sample_ratio is None

    def test_sample_size_stores_value(self):
        """EvolutionConfig(sample_size=10) stores sample_size=10, sample_ratio defaults to None."""
        config = EvolutionConfig(sample_size=10)
        assert config.sample_size == 10
        assert config.sample_ratio is None

    def test_sample_ratio_stores_value(self):
        """EvolutionConfig(sample_ratio=0.3) stores sample_ratio=0.3, sample_size defaults to None."""
        config = EvolutionConfig(sample_ratio=0.3)
        assert config.sample_ratio == 0.3
        assert config.sample_size is None

    def test_sample_ratio_rejects_above_one(self):
        """EvolutionConfig(sample_ratio=1.5) raises ValueError."""
        with pytest.raises(ValidationError):
            EvolutionConfig(sample_ratio=1.5)

    def test_sample_ratio_rejects_negative(self):
        """EvolutionConfig(sample_ratio=-0.1) raises ValueError."""
        with pytest.raises(ValidationError):
            EvolutionConfig(sample_ratio=-0.1)

    def test_sample_size_rejects_negative(self):
        """EvolutionConfig(sample_size=-1) raises ValueError."""
        with pytest.raises(ValidationError):
            EvolutionConfig(sample_size=-1)


# --- GenerationRecord Tests ---


class TestGenerationRecord:
    """Tests for the GenerationRecord model."""

    def test_generation_record_stores_metrics(self):
        """GenerationRecord should store all generation metrics."""
        record = GenerationRecord(
            generation=3,
            best_fitness=0.92,
            avg_fitness=0.75,
            cost_summary={"total_cost_usd": 0.05, "input_tokens": 1000},
            candidates_evaluated=5,
        )
        assert record.generation == 3
        assert record.best_fitness == 0.92
        assert record.avg_fitness == 0.75
        assert record.cost_summary["total_cost_usd"] == 0.05
        assert record.candidates_evaluated == 5


# --- EvolutionResult Tests ---


class TestEvolutionResult:
    """Tests for the EvolutionResult model."""

    def test_evolution_result_stores_final_output(self):
        """EvolutionResult should store the best candidate, records, cost, and reason."""
        candidate = Candidate(template="best prompt")
        records = [
            GenerationRecord(
                generation=0,
                best_fitness=0.5,
                avg_fitness=0.4,
                cost_summary={},
                candidates_evaluated=5,
            ),
            GenerationRecord(
                generation=1,
                best_fitness=0.8,
                avg_fitness=0.65,
                cost_summary={},
                candidates_evaluated=5,
            ),
        ]
        result = EvolutionResult(
            best_candidate=candidate,
            generation_records=records,
            total_cost={"total_cost_usd": 1.23},
            termination_reason="generations_complete",
        )
        assert result.best_candidate.template == "best prompt"
        assert len(result.generation_records) == 2
        assert result.total_cost["total_cost_usd"] == 1.23
        assert result.termination_reason == "generations_complete"

    def test_evolution_result_termination_reasons(self):
        """EvolutionResult should accept all valid termination reasons."""
        candidate = Candidate(template="t")
        for reason in ("perfect_fitness", "budget_exhausted", "generations_complete"):
            result = EvolutionResult(
                best_candidate=candidate,
                generation_records=[],
                total_cost={},
                termination_reason=reason,
            )
            assert result.termination_reason == reason


# --- BudgetExhaustedError Tests ---


class TestBudgetExhaustedError:
    """Tests for the BudgetExhaustedError exception."""

    def test_is_helix_error_subclass(self):
        """BudgetExhaustedError should be a GenePrompterError subclass."""
        assert issubclass(BudgetExhaustedError, GenePrompterError)
        assert issubclass(BudgetExhaustedError, Exception)

    def test_can_be_raised_and_caught(self):
        """BudgetExhaustedError should be raisable and catchable."""
        with pytest.raises(BudgetExhaustedError, match="Budget exceeded"):
            raise BudgetExhaustedError("Budget exceeded: $5.00 of $5.00 limit")
