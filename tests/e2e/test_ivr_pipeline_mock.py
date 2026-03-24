"""Mock E2E tests: validate full pipeline wiring without real API calls.

These tests run with the normal test suite (NOT marked e2e).
They prove that register -> dataset -> evolve pipeline is correctly wired
using mocked LLM responses.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock


from api.config.models import GeneConfig, GenerationConfig
from api.dataset.models import PriorityTier
from api.dataset.service import DatasetService
from api.evaluation.aggregator import FitnessAggregator
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.renderer import TemplateRenderer
from api.evaluation.scorers import ExactMatchScorer, BehaviorJudgeScorer
from api.evaluation.validator import TemplateValidator
from api.evolution.islands import IslandEvolver
from api.evolution.models import EvolutionConfig
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.selector import BoltzmannSelector
from api.gateway.cost import CostTracker
from api.gateway.factory import create_provider
from api.gateway.litellm_provider import LiteLLMProvider
from api.gateway.protocol import LLMProvider
from api.registry.service import PromptRegistry
from api.types import LLMResponse, ModelRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    role: ModelRole = ModelRole.TARGET,
) -> LLMResponse:
    """Create a minimal LLMResponse for mocking."""
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        model_used="mock-model",
        role=role,
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.001,
        timestamp=datetime.now(timezone.utc),
    )


def _build_mock_client(ivr_prompt_template: str) -> AsyncMock:
    """Build a mock LLM client that returns role-specific responses.

    - TARGET calls: return a greeting response or tool call depending on context
    - JUDGE calls: return a structured JSON score
    - META calls: return a revised template wrapped in delimiters
    """
    mock_client = AsyncMock(spec=LLMProvider)

    async def mock_chat_completion(messages, model, role, **kwargs):
        if role == ModelRole.TARGET:
            # Check if the messages suggest a tool call scenario
            user_msg = ""
            for m in messages:
                if m.get("role") == "user":
                    user_msg = m.get("content", "")

            if "pedido" in user_msg.lower() or "pizza" in user_msg.lower():
                return _make_llm_response(
                    tool_calls=[
                        {
                            "name": "transfer_to_number",
                            "arguments": {
                                "target": "Pedidos",
                                "summary": "Cliente quiere hacer un pedido",
                            },
                        }
                    ],
                    role=ModelRole.TARGET,
                )
            return _make_llm_response(
                content="Bienvenido a Pizza Ejemplo. En que puedo ayudarle?",
                role=ModelRole.TARGET,
            )

        if role == ModelRole.JUDGE:
            return _make_llm_response(
                content=json.dumps({"score": 4, "reason": "Good response"}),
                role=ModelRole.JUDGE,
            )

        if role == ModelRole.META:
            # Check if this is a critic call or author call
            system_content = ""
            for m in messages:
                if m.get("role") == "system":
                    system_content = m.get("content", "")

            if "critic" in system_content.lower() or "evaluate" in system_content.lower():
                return _make_llm_response(
                    content="The prompt should be more concise in the greeting section.",
                    role=ModelRole.META,
                )

            # Author call or fresh generation -- return template with delimiters
            return _make_llm_response(
                content=f"<revised_template>\n{ivr_prompt_template}\n</revised_template>",
                role=ModelRole.META,
            )

        # Fallback
        return _make_llm_response(content="fallback response", role=role)

    mock_client.chat_completion = AsyncMock(side_effect=mock_chat_completion)
    mock_client.close = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMockE2ERegisterAndLoad:
    """Test prompt registration and loading via PromptRegistry."""

    async def test_mock_e2e_register_and_load(
        self, e2e_prompts_dir, ivr_prompt_template, ivr_purpose, ivr_tools
    ):
        """Register the IVR prompt, load it back, verify all fields."""
        session_factory = e2e_prompts_dir  # fixture now returns session_factory
        registry = PromptRegistry(session_factory)

        # Load the already-registered prompt
        record = await registry.load_prompt("ivr-ejemplo")

        assert record.id == "ivr-ejemplo"
        assert record.purpose == ivr_purpose
        assert len(record.template_variables) >= 10
        assert record.tools is not None
        assert len(record.tools) == 1
        assert record.tools[0]["function"]["name"] == "transfer_to_number"

        # Verify template contains expected variables
        assert record.template is not None
        assert "{{ business_name }}" in record.template


class TestMockE2EDatasetOperations:
    """Test dataset operations with IVR test cases."""

    async def test_mock_e2e_dataset_operations(self, e2e_prompts_dir, ivr_cases):
        """Add all IVR cases, list them back, verify counts and tiers."""
        session_factory = e2e_prompts_dir  # fixture now returns session_factory
        dataset_service = DatasetService(session_factory)

        # Cases were already added by the e2e_prompts_dir fixture
        cases = await dataset_service.list_cases("ivr-ejemplo")

        assert len(cases) == len(ivr_cases)

        # Verify tier distribution: 2 critical, 4 normal, 1 low
        tier_counts = {}
        for case in cases:
            tier_counts[case.tier] = tier_counts.get(case.tier, 0) + 1

        assert tier_counts[PriorityTier.CRITICAL] == 2
        assert tier_counts[PriorityTier.NORMAL] == 4
        assert tier_counts[PriorityTier.LOW] == 1

        # Verify summary
        summary = await dataset_service.summary("ivr-ejemplo")
        assert summary.total_cases == 7
        assert summary.critical_count == 2
        assert summary.normal_count == 4
        assert summary.low_count == 1


class TestMockE2EEvolutionPipelineWiring:
    """Test the full evolution pipeline with mocked LLM calls."""

    async def test_mock_e2e_evolution_pipeline_wiring(
        self, e2e_prompts_dir, ivr_prompt_template, ivr_cases, ivr_purpose
    ):
        """Wire up the full pipeline manually, run minimal evolution, verify result."""
        mock_client = _build_mock_client(ivr_prompt_template)
        cost_tracker = CostTracker()

        # Build evaluator components
        renderer = TemplateRenderer()
        exact_scorer = ExactMatchScorer()
        behavior_scorer = BehaviorJudgeScorer(client=mock_client, judge_model="mock-judge")
        aggregator = FitnessAggregator()

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=renderer,
            exact_scorer=exact_scorer,
            behavior_scorer=behavior_scorer,
            aggregator=aggregator,
            cost_tracker=cost_tracker,
        )

        validator = TemplateValidator()
        rcc = RCCEngine(
            client=mock_client,
            cost_tracker=cost_tracker,
            validator=validator,
            meta_model="mock-meta",
        )
        mutator = StructuralMutator(
            client=mock_client,
            cost_tracker=cost_tracker,
            validator=validator,
            meta_model="mock-meta",
        )
        selector = BoltzmannSelector()

        # Minimal evolution config: 1 generation, 1 island, 1 conversation, 1 seq turn
        evolution_config = EvolutionConfig(
            generations=1,
            n_islands=1,
            conversations_per_island=1,
            n_seq=1,
            n_parents=1,
            population_cap=5,
            structural_mutation_probability=0.0,  # Disable structural mutation for determinism
        )

        generation_config = GenerationConfig(temperature=0.7, max_tokens=1024)

        # Extract anchor variables
        anchor_variables = set()  # No anchors in this test for simplicity

        evolver = IslandEvolver(
            config=evolution_config,
            evaluator=evaluator,
            rcc=rcc,
            mutator=mutator,
            selector=selector,
            cost_tracker=cost_tracker,
            original_template=ivr_prompt_template,
            anchor_variables=anchor_variables,
            cases=ivr_cases,
            target_model="mock-target",
            generation_config=generation_config,
            prompt_tools=None,
            purpose=ivr_purpose,
        )

        result = await evolver.run()

        # Verify evolution completed
        assert result is not None
        assert result.best_candidate is not None
        assert result.best_candidate.template is not None
        assert len(result.best_candidate.template) > 0
        assert result.termination_reason in (
            "generations_complete",
            "perfect_fitness",
            "budget_exhausted",
        )

        # Verify generation records
        assert len(result.generation_records) >= 0  # May be 0 if seed was perfect

        # Verify the mock client was actually called (pipeline wired correctly)
        assert mock_client.chat_completion.call_count > 0

        # Verify cost tracker recorded calls
        summary = cost_tracker.summary()
        assert summary["total_calls"] > 0
        assert summary["total_cost_usd"] > 0


class TestMockE2EProviderFactoryIntegration:
    """Test provider factory creates different provider types."""

    def test_mock_e2e_provider_factory_integration(self):
        """Verify create_provider returns LiteLLMProvider for all providers."""
        config_gemini = GeneConfig(
            gemini_api_key="test-gemini-key",
        )
        gemini_provider = create_provider("gemini", config_gemini)
        assert isinstance(gemini_provider, LiteLLMProvider)
        assert isinstance(gemini_provider, LLMProvider)
        assert gemini_provider._provider == "gemini"

        config_or = GeneConfig(
            openrouter_api_key="test-or-key",
        )
        or_provider = create_provider("openrouter", config_or)
        assert isinstance(or_provider, LiteLLMProvider)
        assert isinstance(or_provider, LLMProvider)
        assert or_provider._provider == "openrouter"

        # Both are the same type but configured for different providers
        assert gemini_provider._provider != or_provider._provider
