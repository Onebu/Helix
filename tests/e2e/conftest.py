"""E2E test fixtures: IVR prompt, dataset cases, tools, and prompt registration.

Loads fixture files from the fixtures/ directory and provides pytest fixtures
for constructing fully-wired E2E test scenarios.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.config.models import GeneConfig
from api.dataset.models import TestCase
from api.dataset.service import DatasetService
from api.registry.models import PromptRegistration
from api.registry.service import PromptRegistry
from api.storage.models import Base

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def ivr_prompt_template() -> str:
    """Load the IVR prompt Jinja2 template from fixtures."""
    return (FIXTURES_DIR / "ivr_prompt.md").read_text()


@pytest.fixture
def ivr_purpose() -> str:
    """Load the IVR prompt purpose description from fixtures."""
    return (FIXTURES_DIR / "ivr_purpose.md").read_text()


@pytest.fixture
def ivr_tools() -> list[dict]:
    """Load the IVR tool definitions from fixtures."""
    return json.loads((FIXTURES_DIR / "ivr_tools.json").read_text())


@pytest.fixture
def ivr_variables() -> dict:
    """Load the IVR variable values from fixtures."""
    return json.loads((FIXTURES_DIR / "ivr_variables.json").read_text())


@pytest.fixture
def ivr_cases() -> list[TestCase]:
    """Load the IVR test cases from fixtures as TestCase objects."""
    raw_cases = json.loads((FIXTURES_DIR / "ivr_cases.json").read_text())
    cases = []
    for case_data in raw_cases:
        # Load variables from the shared variables file if case has no overrides
        if not case_data.get("variables"):
            case_data["variables"] = json.loads((FIXTURES_DIR / "ivr_variables.json").read_text())
        # Load tools from the shared tools file if case has no overrides
        if case_data.get("tools") is None:
            case_data["tools"] = json.loads((FIXTURES_DIR / "ivr_tools.json").read_text())
        cases.append(TestCase(**case_data))
    return cases


@pytest.fixture
async def e2e_session_factory():
    """Create an in-memory SQLite engine with all tables for E2E tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def e2e_prompts_dir(e2e_session_factory, ivr_prompt_template, ivr_purpose, ivr_tools, ivr_cases):
    """Register the IVR prompt and add test cases via DB-backed services.

    Returns:
        The session_factory for creating services in tests.
    """
    registry = PromptRegistry(e2e_session_factory)
    dataset_service = DatasetService(e2e_session_factory)

    # Register the IVR prompt
    registration = PromptRegistration(
        id="ivr-ejemplo",
        purpose=ivr_purpose,
        template=ivr_prompt_template,
        tools=ivr_tools,
    )
    await registry.register(registration)

    # Add all test cases
    for case in ivr_cases:
        await dataset_service.add_case("ivr-ejemplo", case)

    return e2e_session_factory


def _load_base_config() -> GeneConfig:
    """Load GeneConfig using env vars.

    Used to detect available API keys for skip logic and fixtures.
    """
    try:
        return GeneConfig()
    except Exception:
        return GeneConfig()


@pytest.fixture
def e2e_config(e2e_prompts_dir):
    """Create a GeneConfig for E2E tests.

    Inherits API keys from env vars.
    """
    base = _load_base_config()
    return GeneConfig(
        openrouter_api_key=base.openrouter_api_key,
        gemini_api_key=base.gemini_api_key,
    )
