"""Tests for StructuralMutator with section-level prompt operations."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from api.evaluation.validator import TemplateValidator
from api.evolution.models import Candidate
from api.evolution.mutator import StructuralMutator
from api.gateway.budgeted_provider import BudgetedProvider
from api.gateway.cost import CostTracker
from api.types import LLMResponse, ModelRole


@pytest.fixture
def mock_client():
    """AsyncMock for LiteLLMProvider."""
    return AsyncMock()


@pytest.fixture
def cost_tracker():
    return CostTracker()


@pytest.fixture
def validator():
    return TemplateValidator()


@pytest.fixture
def meta_model():
    return "anthropic/claude-sonnet-4"


@pytest.fixture
def mutator(mock_client, cost_tracker, validator, meta_model):
    return StructuralMutator(
        client=mock_client,
        cost_tracker=cost_tracker,
        validator=validator,
        meta_model=meta_model,
    )


@pytest.fixture
def sample_candidate():
    """A candidate with a multi-section Jinja2 template."""
    return Candidate(
        id="original-001",
        template=(
            "# System\n"
            "You are a helpful assistant for {{ domain }}.\n\n"
            "# Instructions\n"
            "Given {{ input }}, provide {{ output_format }}.\n\n"
            "# Constraints\n"
            "Be concise and accurate."
        ),
        fitness_score=0.7,
        generation=1,
    )


@pytest.fixture
def anchor_variables():
    return {"domain", "input", "output_format"}


def _make_llm_response(content: str) -> LLMResponse:
    """Helper to create a mock LLMResponse."""
    return LLMResponse(
        content=content,
        model_used="anthropic/claude-sonnet-4",
        role=ModelRole.META,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        timestamp=datetime.now(UTC),
    )


class TestSuccessfulMutation:
    """Tests for successful structural mutation operations."""

    @pytest.mark.asyncio
    async def test_successful_structural_mutation(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """Meta-model returns valid restructured template, new candidate returned."""
        restructured = (
            "# Instructions\n"
            "Given {{ input }}, provide {{ output_format }}.\n\n"
            "# System\n"
            "You are a helpful assistant for {{ domain }}.\n\n"
            "# Constraints\n"
            "Be concise and accurate."
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        result = await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        assert result.template == restructured
        assert result.id != sample_candidate.id
        assert result.fitness_score == 0.0  # needs re-evaluation
        assert result.evaluation is None

    @pytest.mark.asyncio
    async def test_mutation_preserves_variables(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """Mutated template keeps all variables, validation passes."""
        restructured = (
            "# Context\n"
            "Domain: {{ domain }}\n\n"
            "# Task\n"
            "Input: {{ input }}\n"
            "Output format: {{ output_format }}\n\n"
            "# Guidelines\n"
            "Be concise and accurate."
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        result = await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        # All anchor variables should be preserved
        validator = TemplateValidator()
        validation = validator.validate_preserved(
            sample_candidate.template, result.template, anchor_variables
        )
        assert validation.valid


class TestMutationFailsafe:
    """Tests for mutation failure modes that return original candidate."""

    @pytest.mark.asyncio
    async def test_mutation_drops_variable_returns_original(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """Meta-model drops a variable, original candidate returned."""
        # Missing {{ output_format }} variable
        bad_template = (
            "# Instructions\n"
            "Given {{ input }}, provide a response.\n\n"
            "# System\n"
            "You are a helpful assistant for {{ domain }}."
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{bad_template}\n</revised_template>"
        )

        result = await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        assert result is sample_candidate

    @pytest.mark.asyncio
    async def test_mutation_breaks_syntax_returns_original(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """Meta-model produces invalid Jinja2, original returned."""
        broken_template = (
            "# System\n"
            "{% if domain %}\n"
            "You are {{ domain }.\n"  # Missing closing }}
            "{% endif\n"  # Missing %}
            "Given {{ input }}, provide {{ output_format }}."
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{broken_template}\n</revised_template>"
        )

        result = await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        assert result is sample_candidate


class TestTemplateExtraction:
    """Tests for template extraction from LLM response."""

    @pytest.mark.asyncio
    async def test_mutation_extracts_from_delimiters(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """Parses <revised_template> tags correctly."""
        inner = "# Reordered\n{{ domain }} - {{ input }} - {{ output_format }}"
        response_text = (
            "Here is my restructured version:\n\n"
            f"<revised_template>\n{inner}\n</revised_template>\n\n"
            "I moved the sections around."
        )
        mock_client.chat_completion.return_value = _make_llm_response(response_text)

        result = await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        assert result.template == inner

    @pytest.mark.asyncio
    async def test_mutation_uses_full_content_without_delimiters(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """No tags, uses full response content."""
        full_content = "# Reordered\n{{ domain }} - {{ input }} - {{ output_format }}"
        mock_client.chat_completion.return_value = _make_llm_response(full_content)

        result = await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        assert result.template == full_content


class TestCostAndLineage:
    """Tests for cost tracking and parent lineage."""

    @pytest.mark.asyncio
    async def test_plain_provider_preserves_direct_cost_tracking(
        self, mutator, mock_client, cost_tracker, sample_candidate, anchor_variables
    ):
        """A directly constructed mutator records its plain-provider response."""
        restructured = "# Reordered\n{{ domain }} - {{ input }} - {{ output_format }}"
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        summary = cost_tracker.summary()
        assert summary["total_calls"] == 1
        assert summary["total_cost_usd"] > 0

    @pytest.mark.asyncio
    async def test_returned_candidate_has_parent_lineage(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """New candidate's parent_ids includes original."""
        restructured = "# Reordered\n{{ domain }} - {{ input }} - {{ output_format }}"
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        result = await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        assert sample_candidate.id in result.parent_ids


class TestSectionAwareMutation:
    """Tests for section-aware mutation prompt selection."""

    @pytest.mark.asyncio
    async def test_sectioned_template_includes_section_summary_in_prompt(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """A template with H1 sections causes the meta-model prompt to include section summary."""
        restructured = (
            "# Instructions\n"
            "Given {{ input }}, provide {{ output_format }}.\n\n"
            "# System\n"
            "You are a helpful assistant for {{ domain }}.\n\n"
            "# Constraints\n"
            "Be concise and accurate."
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        # Inspect the messages sent to the meta-model
        call_args = mock_client.chat_completion.call_args
        messages = call_args[0][0]  # first positional arg is messages list
        prompt_content = messages[0]["content"]

        # Should include section summary lines (from SectionParser.format_summary)
        assert "- System" in prompt_content
        assert "- Instructions" in prompt_content
        assert "- Constraints" in prompt_content
        # Should include section-aware instruction
        assert (
            "sectioning standard" in prompt_content.lower() or "section" in prompt_content.lower()
        )

    @pytest.mark.asyncio
    async def test_unsectioned_template_uses_original_prompt(
        self, mock_client, cost_tracker, validator, meta_model
    ):
        """A template without headers uses the original (non-section-aware) prompt."""
        mutator = StructuralMutator(
            client=mock_client,
            cost_tracker=cost_tracker,
            validator=validator,
            meta_model=meta_model,
        )
        unsectioned_candidate = Candidate(
            id="unsectioned-001",
            template="Just a plain prompt with {{ name }} and {{ task }}.",
            fitness_score=0.5,
            generation=1,
        )
        restructured = "A restructured prompt with {{ name }} and {{ task }}."
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        await mutator.mutate(
            unsectioned_candidate,
            original_template=unsectioned_candidate.template,
            anchor_variables={"name", "task"},
        )

        # Inspect the messages sent to the meta-model
        call_args = mock_client.chat_completion.call_args
        messages = call_args[0][0]
        prompt_content = messages[0]["content"]

        # Should NOT include section summary lines (no "- (unsectioned)" in prompt)
        assert "Section structure" not in prompt_content
        # Should still contain the template text
        assert "Just a plain prompt" in prompt_content

    @pytest.mark.asyncio
    async def test_section_metadata_is_compact_not_full_content(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """Section metadata in prompt uses name + purpose, not full content duplication."""
        restructured = (
            "# System\n"
            "You are a helpful assistant for {{ domain }}.\n\n"
            "# Instructions\n"
            "Given {{ input }}, provide {{ output_format }}.\n\n"
            "# Constraints\n"
            "Be concise and accurate."
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        await mutator.mutate(
            sample_candidate,
            original_template=sample_candidate.template,
            anchor_variables=anchor_variables,
        )

        call_args = mock_client.chat_completion.call_args
        messages = call_args[0][0]
        prompt_content = messages[0]["content"]

        # The section summary is compact (just names), not duplicating full content.
        # The template itself appears once in the prompt, but the summary should be
        # separate and compact.
        # Count how many times "- System" appears -- it should be in the summary section
        assert prompt_content.count("- System") >= 1
        assert prompt_content.count("- Instructions") >= 1
        assert prompt_content.count("- Constraints") >= 1


class TestMutationPromptIncludesVariables:
    """Mutation prompts must list exact variable names."""

    @pytest.mark.asyncio
    async def test_structural_mutation_prompt_contains_variable_names(
        self, mock_client, cost_tracker, validator, meta_model
    ):
        """Unsectioned mutation prompt must list anchor variable names."""
        mutator = StructuralMutator(
            client=mock_client,
            cost_tracker=cost_tracker,
            validator=validator,
            meta_model=meta_model,
        )
        unsectioned = Candidate(
            template="Plain prompt with {{ name }} and {{ task }}.",
            fitness_score=0.5,
            generation=1,
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            "<revised_template>Restructured {{ name }} {{ task }}</revised_template>"
        )

        await mutator.mutate(unsectioned, unsectioned.template, {"name", "task"})

        call_args = mock_client.chat_completion.call_args
        messages = call_args[0][0]
        prompt_content = messages[0]["content"]
        assert "name" in prompt_content
        assert "task" in prompt_content

    @pytest.mark.asyncio
    async def test_section_aware_mutation_prompt_contains_variable_names(
        self, mutator, mock_client, sample_candidate, anchor_variables
    ):
        """Sectioned mutation prompt must list anchor variable names."""
        restructured = (
            "# System\nFor {{ domain }}.\n\n# Instructions\n{{ input }} -> {{ output_format }}"
        )
        mock_client.chat_completion.return_value = _make_llm_response(
            f"<revised_template>\n{restructured}\n</revised_template>"
        )

        await mutator.mutate(sample_candidate, sample_candidate.template, anchor_variables)

        call_args = mock_client.chat_completion.call_args
        messages = call_args[0][0]
        prompt_content = messages[0]["content"]
        assert "domain" in prompt_content
        assert "input" in prompt_content
        assert "output_format" in prompt_content


@pytest.mark.asyncio
async def test_wrapped_mutator_records_response_exactly_once(
    sample_candidate, anchor_variables, validator, meta_model
):
    inner = AsyncMock()
    restructured = "# Reordered\n{{ domain }} - {{ input }} - {{ output_format }}"
    inner.chat_completion.return_value = _make_llm_response(
        f"<revised_template>{restructured}</revised_template>"
    )
    tracker = CostTracker()
    mutator = StructuralMutator(
        client=BudgetedProvider(inner, tracker),
        cost_tracker=tracker,
        validator=validator,
        meta_model=meta_model,
    )

    await mutator.mutate(sample_candidate, sample_candidate.template, anchor_variables)

    assert inner.chat_completion.await_count == 1
    assert tracker.summary()["total_calls"] == 1


def test_wrapped_mutator_rejects_mismatched_cost_tracker(validator, meta_model):
    wrapped_tracker = CostTracker()
    client = BudgetedProvider(AsyncMock(), wrapped_tracker)

    with pytest.raises(ValueError, match="same CostTracker"):
        StructuralMutator(
            client=client,
            cost_tracker=CostTracker(),
            validator=validator,
            meta_model=meta_model,
        )
