"""E2E integration tests for wizard generation, registration, and evolution pipeline.

Covers:
  TEST-03: Full wizard flow (generate -> register -> list)
  TEST-04: Wizard-generated prompt works with evolution pipeline
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import yaml
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.web.app import create_app
from api.web.deps import (
    _get_session_factory,
    get_config,
    get_dataset_service,
    get_db_session,
    get_registry,
)
from api.web.event_bus import EventBus
from api.web.run_manager import RunManager
from api.config.models import GeneConfig, GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.aggregator import FitnessAggregator
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.renderer import TemplateRenderer
from api.evaluation.scorers import BehaviorJudgeScorer, ExactMatchScorer
from api.evaluation.validator import TemplateValidator
from api.evolution.islands import IslandEvolver
from api.evolution.models import EvolutionConfig
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.selector import BoltzmannSelector
from api.gateway.cost import CostTracker
from api.gateway.protocol import LLMProvider
from api.registry.service import PromptRegistry
from api.types import LLMResponse, ModelRole
from api.dataset.service import DatasetService
from api.storage.models import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


CANNED_WIZARD_YAML = """\
id: test-wizard
purpose: Handle support tickets
template: |
  Hello {{ name }}, welcome to {{ department }}.
  How can I help you today?
variables:
  - name: name
    type: string
  - name: department
    type: string
    is_anchor: true
"""

WIZARD_REQUEST = {
    "id": "test-wizard",
    "purpose": "Handle support tickets",
    "description": "A support ticket routing prompt",
    "variables": [
        {"name": "name", "var_type": "string", "description": "Customer name"},
        {"name": "department", "var_type": "string", "is_anchor": True},
    ],
    "constraints": "Keep responses professional and concise",
    "include_tools": False,
}


def _make_mock_provider(response_content: str) -> AsyncMock:
    """Create a mock LLM provider that returns a canned response."""
    mock_provider = AsyncMock()
    mock_provider.chat_completion.return_value = LLMResponse(
        content=response_content,
        tool_calls=None,
        model_used="gemini-2.5-pro",
        role=ModelRole.META,
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.001,
        timestamp=datetime.now(timezone.utc),
    )
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    return mock_provider


async def _build_test_app() -> FastAPI:
    """Create a FastAPI app configured for testing with an in-memory DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    application = create_app()

    test_config = GeneConfig(
        database_url=None,
    )

    test_registry = PromptRegistry(session_factory)
    test_dataset_service = DatasetService(session_factory)

    async def _override_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_config] = lambda: test_config
    application.dependency_overrides[get_registry] = lambda: test_registry
    application.dependency_overrides[get_dataset_service] = lambda: test_dataset_service
    application.dependency_overrides[get_db_session] = _override_db_session
    application.dependency_overrides[_get_session_factory] = lambda: session_factory

    application.state.run_manager = RunManager()
    application.state.event_bus = EventBus()

    # Store engine on app for cleanup
    application.state._test_engine = engine

    return application


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


def _build_mock_client(template: str) -> AsyncMock:
    """Build a mock LLM client that returns role-specific responses.

    - TARGET calls: return a greeting response
    - JUDGE calls: return a structured JSON score
    - META calls: return a revised template wrapped in delimiters
    """
    mock_client = AsyncMock(spec=LLMProvider)

    async def mock_chat_completion(messages, model, role, **kwargs):
        if role == ModelRole.TARGET:
            return _make_llm_response(
                content="Hello Alice, welcome to Support. How can I help you?",
                role=ModelRole.TARGET,
            )

        if role == ModelRole.JUDGE:
            return _make_llm_response(
                content=json.dumps({"score": 4, "reason": "Good greeting"}),
                role=ModelRole.JUDGE,
            )

        if role == ModelRole.META:
            # Check for critic vs author call
            system_content = ""
            for m in messages:
                if m.get("role") == "system":
                    system_content = m.get("content", "")

            if "critic" in system_content.lower() or "evaluate" in system_content.lower():
                return _make_llm_response(
                    content="The greeting could be more personalized.",
                    role=ModelRole.META,
                )

            # Author call -- return template with delimiters
            return _make_llm_response(
                content=f"<revised_template>\n{template}\n</revised_template>",
                role=ModelRole.META,
            )

        return _make_llm_response(content="fallback response", role=role)

    mock_client.chat_completion = AsyncMock(side_effect=mock_chat_completion)
    mock_client.close = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return mock_client


# ---------------------------------------------------------------------------
# TEST-03: Wizard Generation Flow
# ---------------------------------------------------------------------------


class TestWizardGeneration:
    """E2E tests for wizard generate -> register -> list flow (TEST-03)."""

    @patch("api.web.routers.wizard.create_provider")
    async def test_wizard_generates_valid_yaml(
        self, mock_create_provider: AsyncMock,
    ):
        """POST /api/wizard/generate returns 200 with yaml_template containing
        the prompt id and variable references."""
        mock_provider = _make_mock_provider(CANNED_WIZARD_YAML)
        mock_create_provider.return_value = mock_provider

        app = await _build_test_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/wizard/generate", json=WIZARD_REQUEST)

        assert resp.status_code == 200
        data = resp.json()
        assert "yaml_template" in data
        assert len(data["yaml_template"]) > 0
        assert "test-wizard" in data["yaml_template"]
        assert "{{ name }}" in data["yaml_template"]

    @patch("api.web.routers.wizard.create_provider")
    async def test_wizard_generate_then_register(
        self, mock_create_provider: AsyncMock,
    ):
        """Generate a template via wizard, then register it via POST /api/prompts/.
        Verify the prompt can be retrieved with correct content."""
        mock_provider = _make_mock_provider(CANNED_WIZARD_YAML)
        mock_create_provider.return_value = mock_provider

        app = await _build_test_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Step 1: Generate via wizard
            gen_resp = await client.post("/api/wizard/generate", json=WIZARD_REQUEST)
            assert gen_resp.status_code == 200
            yaml_template = gen_resp.json()["yaml_template"]

            # Step 2: Parse the YAML to extract fields
            parsed = yaml.safe_load(yaml_template)
            prompt_id = parsed["id"]
            purpose = parsed["purpose"]
            template_text = parsed["template"]

            # Step 3: Register the prompt
            reg_resp = await client.post(
                "/api/prompts/",
                json={
                    "id": prompt_id,
                    "purpose": purpose,
                    "template": template_text,
                },
            )
            assert reg_resp.status_code == 201

            # Step 4: Retrieve and verify
            get_resp = await client.get(f"/api/prompts/{prompt_id}")
            assert get_resp.status_code == 200
            detail = get_resp.json()
            assert detail["id"] == "test-wizard"
            assert detail["purpose"] == "Handle support tickets"
            assert "{{ name }}" in detail["template"]

    @patch("api.web.routers.wizard.create_provider")
    async def test_wizard_full_flow_prompt_in_list(
        self, mock_create_provider: AsyncMock,
    ):
        """Generate -> register -> list prompts -> verify the wizard-generated
        prompt appears in the list with correct purpose."""
        mock_provider = _make_mock_provider(CANNED_WIZARD_YAML)
        mock_create_provider.return_value = mock_provider

        app = await _build_test_app()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Generate via wizard
            gen_resp = await client.post("/api/wizard/generate", json=WIZARD_REQUEST)
            assert gen_resp.status_code == 200
            parsed = yaml.safe_load(gen_resp.json()["yaml_template"])

            # Register
            reg_resp = await client.post(
                "/api/prompts/",
                json={
                    "id": parsed["id"],
                    "purpose": parsed["purpose"],
                    "template": parsed["template"],
                },
            )
            assert reg_resp.status_code == 201

            # List and verify
            list_resp = await client.get("/api/prompts/")
            assert list_resp.status_code == 200
            prompts = list_resp.json()
            assert len(prompts) == 1
            assert prompts[0]["id"] == "test-wizard"
            assert prompts[0]["purpose"] == "Handle support tickets"


# ---------------------------------------------------------------------------
# TEST-04: Wizard Prompt Evolution
# ---------------------------------------------------------------------------


class TestWizardPromptEvolution:
    """E2E test proving a wizard-generated prompt works as an evolution seed (TEST-04)."""

    async def test_wizard_generated_prompt_evolves(self):
        """Create a Jinja2 template (mimicking wizard output), wire up mock
        evolution pipeline, run IslandEvolver, verify EvolutionResult."""
        # Wizard-style template
        wizard_template = (
            "Hello {{ name }}, welcome to {{ department }}.\nHow can I help you today?"
        )

        # Simple test cases with variables
        cases = [
            TestCase(
                id="greeting-alice",
                description="Greet Alice from Support",
                chat_history=[
                    {"role": "user", "content": "Hi, I need help with my account."},
                ],
                variables={"name": "Alice", "department": "Support"},
                expected_behavior="Greet customer by name and department",
            ),
            TestCase(
                id="greeting-bob",
                description="Greet Bob from Sales",
                chat_history=[
                    {"role": "user", "content": "I want to buy your product."},
                ],
                variables={"name": "Bob", "department": "Sales"},
                expected_behavior="Greet customer by name and department",
            ),
        ]

        mock_client = _build_mock_client(wizard_template)
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

        # Minimal evolution config: 1 generation, 1 island
        evolution_config = EvolutionConfig(
            generations=1,
            n_islands=1,
            conversations_per_island=1,
            n_seq=1,
            n_parents=1,
            population_cap=5,
            structural_mutation_probability=0.0,
        )

        generation_config = GenerationConfig(temperature=0.7, max_tokens=1024)

        evolver = IslandEvolver(
            config=evolution_config,
            evaluator=evaluator,
            rcc=rcc,
            mutator=mutator,
            selector=selector,
            cost_tracker=cost_tracker,
            original_template=wizard_template,
            anchor_variables=set(),
            cases=cases,
            target_model="mock-target",
            generation_config=generation_config,
            prompt_tools=None,
            purpose="Handle support tickets",
        )

        result = await evolver.run()

        # Verify evolution completed with valid result
        assert result is not None
        assert result.best_candidate is not None
        assert result.best_candidate.template is not None
        assert len(result.best_candidate.template) > 0
        assert result.termination_reason in (
            "generations_complete",
            "perfect_fitness",
            "budget_exhausted",
        )

        # Verify the mock client was actually called (pipeline wired correctly)
        assert mock_client.chat_completion.call_count > 0
