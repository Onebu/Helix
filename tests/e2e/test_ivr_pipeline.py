"""Real E2E tests: exercise Gemini API with actual IVR prompt scenarios.

ALL tests marked with @pytest.mark.e2e -- skipped by default.
Run with: uv run pytest -m e2e -v

API key resolved via GENE_GEMINI_API_KEY env var.
These tests cost real money. Budget caps and minimal configs keep costs low.
"""

import pytest

from api.config.models import GeneConfig, GenerationConfig
from api.evolution.models import EvolutionConfig
from api.gateway.litellm_provider import LiteLLMProvider
from api.types import ModelRole
from tests.e2e.conftest import _load_base_config

_base_config = _load_base_config()

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _base_config.gemini_api_key,
        reason="gemini_api_key not configured (GENE_GEMINI_API_KEY env var)",
    ),
]


@pytest.fixture
def gemini_api_key() -> str:
    """Get the Gemini API key from config cascade."""
    assert _base_config.gemini_api_key is not None
    return _base_config.gemini_api_key


class TestE2EGeminiChatCompletion:
    """Smoke test: basic Gemini API chat completion."""

    async def test_e2e_gemini_chat_completion(self, gemini_api_key):
        """Make one chat_completion call, verify response structure."""
        async with LiteLLMProvider(provider="gemini", api_key=gemini_api_key) as provider:
            response = await provider.chat_completion(
                messages=[
                    {"role": "user", "content": "Responde en una oracion: Que es una pizzeria?"}
                ],
                model="gemini-3-flash-preview",
                role=ModelRole.TARGET,
                temperature=0,
            )

        assert response.content is not None
        assert len(response.content) > 0
        assert response.input_tokens > 0
        assert response.output_tokens > 0
        assert response.cost_usd >= 0


class TestE2EGeminiToolCalling:
    """Test Gemini API tool calling with IVR scenario."""

    async def test_e2e_gemini_tool_calling(
        self, gemini_api_key, ivr_prompt_template, ivr_variables, ivr_tools
    ):
        """Make a tool-calling chat_completion, verify transfer_to_number is invoked."""
        from api.evaluation.renderer import TemplateRenderer

        # Render the IVR prompt with real variables
        renderer = TemplateRenderer()
        rendered_prompt = renderer.render(ivr_prompt_template, ivr_variables)

        async with LiteLLMProvider(provider="gemini", api_key=gemini_api_key) as provider:
            response = await provider.chat_completion(
                messages=[
                    {"role": "system", "content": rendered_prompt},
                    {
                        "role": "user",
                        "content": "Hola, soy Maria Lopez. Quiero hacer un pedido de pizzas por favor, transfiereme.",
                    },
                ],
                model="gemini-3-flash-preview",
                role=ModelRole.TARGET,
                tools=ivr_tools,
                temperature=0,
            )

        # Should invoke transfer_to_number for an explicit transfer request
        assert response.tool_calls is not None, (
            f"Expected tool_calls but got text response: {response.content}"
        )
        assert len(response.tool_calls) >= 1

        # Find the transfer_to_number call
        transfer_call = None
        for tc in response.tool_calls:
            fn = tc.get("function", tc) if isinstance(tc, dict) else tc
            name = fn.get("name", "")
            if name == "transfer_to_number":
                transfer_call = fn
                break

        assert transfer_call is not None, (
            f"Expected transfer_to_number tool call, got: {response.tool_calls}"
        )


class TestE2EFullEvolutionRun:
    """Full pipeline test: register, build dataset, evolve with real Gemini API."""

    async def test_e2e_full_evolution_run(
        self,
        e2e_prompts_dir,
        ivr_prompt_template,
        ivr_purpose,
        ivr_cases,
        gemini_api_key,
    ):
        """Run a minimal evolution with real Gemini API calls.

        Uses gemini-3-flash-preview for all roles (cheapest).
        Budget capped at $0.50 to prevent runaway costs.
        Uses a subset of cases (3) for cost control.
        """
        from api.evolution.runner import run_evolution

        prompts_dir = e2e_prompts_dir / "prompts"

        config = GeneConfig(
            prompts_dir=str(prompts_dir),
            gemini_api_key=gemini_api_key,
            meta_provider="gemini",
            target_provider="gemini",
            judge_provider="gemini",
            meta_model="gemini-3-flash-preview",
            target_model="gemini-3-flash-preview",
            judge_model="gemini-3-flash-preview",
            generation=GenerationConfig(temperature=0),
        )

        # Load prompt record
        from api.registry.service import PromptRegistry
        from api.storage.git import GitStorage

        git_storage = GitStorage(prompts_dir)
        registry = PromptRegistry(prompts_dir, git_storage)
        prompt_record = await registry.load_prompt("ivr-ejemplo", config)

        # Use a subset of cases (first 3) for cost control
        subset_cases = ivr_cases[:3]

        # Minimal evolution config
        evolution_config = EvolutionConfig(
            generations=1,
            n_islands=1,
            conversations_per_island=1,
            n_seq=1,
            n_parents=1,
            population_cap=5,
            budget_cap_usd=0.50,
        )

        result = await run_evolution(
            config=config,
            prompt_record=prompt_record,
            cases=subset_cases,
            evolution_config=evolution_config,
        )

        # Verify evolution completed
        assert result is not None
        assert result.best_candidate is not None
        assert result.best_candidate.fitness_score >= 0
        assert result.termination_reason in (
            "generations_complete",
            "perfect_fitness",
            "budget_exhausted",
        )
