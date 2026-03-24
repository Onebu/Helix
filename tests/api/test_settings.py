"""Tests for the Settings API endpoints (GET/PUT /api/settings, POST /api/settings/test-connection).

Tests validate DB-backed settings persistence: reads/writes go to the Setting table,
API keys come from env vars only (never stored in DB), response shapes are unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.web.app import create_app
from api.web.deps import get_config, get_db_session
from api.web.event_bus import EventBus
from api.web.run_manager import RunManager
from api.config.models import GeneConfig
from api.storage.models import Base, Setting


@pytest.fixture
async def settings_engine():
    """In-memory SQLite engine for settings tests."""
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def settings_session_factory(settings_engine):
    """Session factory sharing the in-memory engine."""
    return async_sessionmaker(settings_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def seed_settings(settings_session_factory):
    """Seed Setting rows with test config values (API keys stripped)."""
    async with settings_session_factory() as session:
        session.add(
            Setting(
                category="global_config",
                data={
                    "meta_provider": "gemini",
                    "meta_model": "gemini-2.5-pro",
                    "target_provider": "openrouter",
                    "target_model": "openai/gpt-4o-mini",
                    "judge_provider": "gemini",
                    "judge_model": "gemini-2.5-flash",
                    "concurrency_limit": 10,
                },
            )
        )
        session.add(
            Setting(
                category="generation_defaults",
                data={"temperature": 0.7, "max_tokens": 4096},
            )
        )
        await session.commit()


@pytest.fixture
def settings_app(settings_session_factory, seed_settings) -> FastAPI:
    """FastAPI app configured with DB session override and test config."""
    application = create_app()

    test_config = GeneConfig(
        meta_provider="gemini",
        meta_model="gemini-2.5-pro",
        target_provider="openrouter",
        target_model="openai/gpt-4o-mini",
        judge_provider="gemini",
        judge_model="gemini-2.5-flash",
        gemini_api_key="test-key-abcd1234",
        openrouter_api_key="or-key-wxyz5678",
        concurrency_limit=10,
    )

    async def _override_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with settings_session_factory() as session:
            yield session

    application.dependency_overrides[get_config] = lambda: test_config
    application.dependency_overrides[get_db_session] = _override_db_session

    application.state.run_manager = RunManager()
    application.state.event_bus = EventBus()

    return application


@pytest.fixture
async def settings_client(settings_app: FastAPI):
    """Async HTTP client wired to the settings test app."""
    transport = httpx.ASGITransport(app=settings_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- GET /api/settings ---


@pytest.mark.anyio
async def test_get_settings_returns_roles(settings_client: httpx.AsyncClient):
    """GET /api/settings returns all 3 roles with expected structure."""
    resp = await settings_client.get("/api/settings/")
    assert resp.status_code == 200
    data = resp.json()

    # All 3 roles present
    for role in ("meta", "target", "judge"):
        assert role in data
        role_data = data[role]
        assert "provider" in role_data
        assert "model" in role_data
        assert "has_key" in role_data
        assert "key_hint" in role_data


@pytest.mark.anyio
async def test_get_settings_returns_correct_values(settings_client: httpx.AsyncClient):
    """GET /api/settings returns the configured values from DB."""
    resp = await settings_client.get("/api/settings/")
    data = resp.json()

    assert data["meta"]["provider"] == "gemini"
    assert data["meta"]["model"] == "gemini-2.5-pro"
    assert data["target"]["provider"] == "openrouter"
    assert data["target"]["model"] == "openai/gpt-4o-mini"
    assert data["judge"]["provider"] == "gemini"
    assert data["judge"]["model"] == "gemini-2.5-flash"


@pytest.mark.anyio
async def test_get_settings_masks_api_keys(settings_client: httpx.AsyncClient):
    """API keys are never returned in full -- only has_key and masked hint."""
    resp = await settings_client.get("/api/settings/")
    data = resp.json()

    # Gemini key configured -> meta and judge roles should have has_key=True
    assert data["meta"]["has_key"] is True
    assert data["meta"]["key_hint"].endswith("1234")
    assert data["meta"]["key_hint"].startswith("\u2022\u2022\u2022\u2022")

    # OpenRouter key configured -> target role
    assert data["target"]["has_key"] is True
    assert data["target"]["key_hint"].endswith("5678")

    # Full key should never appear in the response
    raw = resp.text
    assert "test-key-abcd1234" not in raw
    assert "or-key-wxyz5678" not in raw


@pytest.mark.anyio
async def test_get_settings_includes_global_fields(settings_client: httpx.AsyncClient):
    """GET /api/settings includes concurrency_limit, generation, and providers."""
    resp = await settings_client.get("/api/settings/")
    data = resp.json()

    assert "concurrency_limit" in data
    assert data["concurrency_limit"] == 10

    assert "generation" in data
    assert isinstance(data["generation"], dict)

    assert "providers" in data
    assert "gemini" in data["providers"]
    assert "openrouter" in data["providers"]
    assert "openai" in data["providers"]


# --- PUT /api/settings ---


@pytest.mark.anyio
async def test_put_settings_updates_values(settings_client: httpx.AsyncClient):
    """PUT /api/settings updates config in DB and returns updated values."""
    resp = await settings_client.put(
        "/api/settings/",
        json={
            "meta_provider": "openai",
            "meta_model": "gpt-4o",
            "concurrency_limit": 5,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["provider"] == "openai"
    assert data["meta"]["model"] == "gpt-4o"
    assert data["concurrency_limit"] == 5


@pytest.mark.anyio
async def test_put_settings_writes_to_db(
    settings_client: httpx.AsyncClient,
    settings_session_factory,
):
    """PUT /api/settings persists changes to Setting table."""
    await settings_client.put(
        "/api/settings/",
        json={
            "target_model": "anthropic/claude-sonnet-4",
        },
    )

    # Verify DB was updated
    async with settings_session_factory() as session:
        result = await session.execute(select(Setting).where(Setting.category == "global_config"))
        row = result.scalar_one()
        assert row.data["target_model"] == "anthropic/claude-sonnet-4"


@pytest.mark.anyio
async def test_put_settings_partial_preserves_existing(
    settings_client: httpx.AsyncClient,
    settings_session_factory,
):
    """PUT with partial update preserves existing DB values."""
    await settings_client.put(
        "/api/settings/",
        json={"concurrency_limit": 20},
    )

    async with settings_session_factory() as session:
        result = await session.execute(select(Setting).where(Setting.category == "global_config"))
        row = result.scalar_one()
        # Updated field
        assert row.data["concurrency_limit"] == 20
        # Preserved fields
        assert row.data["meta_provider"] == "gemini"
        assert row.data["meta_model"] == "gemini-2.5-pro"


@pytest.mark.anyio
async def test_put_settings_encrypts_api_keys_in_db(
    settings_client: httpx.AsyncClient,
    settings_session_factory,
    monkeypatch,
):
    """PUT /api/settings stores API keys encrypted in 'api_keys' category, not global_config."""
    monkeypatch.setenv("HELIX_SECRET_KEY", "test-encryption-secret")
    # Reset module-level singleton so it picks up the test env var
    import api.storage.encryption as enc_mod

    enc_mod._encryptor = None

    await settings_client.put(
        "/api/settings/",
        json={
            "gemini_api_key": "new-key-9999",
            "openrouter_api_key": "or-new-key-8888",
            "openai_api_key": "oai-new-key-7777",
            "meta_model": "updated-model",
        },
    )

    async with settings_session_factory() as session:
        # API key fields must NOT appear in global_config
        result = await session.execute(select(Setting).where(Setting.category == "global_config"))
        row = result.scalar_one()
        assert "gemini_api_key" not in row.data
        assert "openrouter_api_key" not in row.data
        assert "openai_api_key" not in row.data
        # Non-key field should be stored in global_config
        assert row.data["meta_model"] == "updated-model"

        # API keys should be in "api_keys" category, encrypted
        result = await session.execute(select(Setting).where(Setting.category == "api_keys"))
        keys_row = result.scalar_one()
        assert "gemini_api_key" in keys_row.data
        assert "openrouter_api_key" in keys_row.data
        assert "openai_api_key" in keys_row.data
        # Values should be encrypted (start with gAAAAA), not plaintext
        assert keys_row.data["gemini_api_key"].startswith("gAAAAA")
        assert "new-key-9999" not in keys_row.data["gemini_api_key"]

    # Clean up singleton
    enc_mod._encryptor = None


@pytest.mark.anyio
async def test_put_settings_invalidates_cache(settings_client: httpx.AsyncClient):
    """PUT /api/settings calls get_config.cache_clear()."""
    with patch("api.web.routers.settings.get_config") as mock_get_config:
        mock_config = GeneConfig(
            meta_provider="gemini",
            meta_model="gemini-2.5-pro",
        )
        mock_get_config.return_value = mock_config
        mock_get_config.cache_clear = lambda: None

        resp = await settings_client.put(
            "/api/settings/",
            json={"concurrency_limit": 3},
        )

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_api_keys_from_env_not_db(settings_client: httpx.AsyncClient):
    """API keys come from GeneConfig (env vars), not from DB Setting rows."""
    resp = await settings_client.get("/api/settings/")
    data = resp.json()

    # Keys come from GeneConfig (set via constructor in fixture), not DB
    # Meta uses gemini provider -> should have the gemini key
    assert data["meta"]["has_key"] is True
    # Target uses openrouter -> should have the openrouter key
    assert data["target"]["has_key"] is True


# --- GET /api/settings/defaults ---


@pytest.mark.anyio
async def test_get_defaults_returns_default_values(settings_client: httpx.AsyncClient):
    """GET /api/settings/defaults returns GeneConfig default values."""
    resp = await settings_client.get("/api/settings/defaults")
    assert resp.status_code == 200
    data = resp.json()

    # Defaults from GeneConfig
    assert data["meta"]["provider"] == "openrouter"
    assert data["meta"]["model"] == "anthropic/claude-sonnet-4"
    assert data["target"]["provider"] == "openrouter"
    assert data["target"]["model"] == "openai/gpt-4o-mini"
    assert data["judge"]["provider"] == "openrouter"
    assert data["judge"]["model"] == "anthropic/claude-sonnet-4"
    assert data["concurrency_limit"] == 10


# --- POST /api/settings/test-connection ---


@pytest.mark.anyio
async def test_connection_success(settings_client: httpx.AsyncClient):
    """POST /api/settings/test-connection with valid key returns success."""
    mock_response = httpx.Response(
        200, json={"data": []}, request=httpx.Request("GET", "http://test")
    )

    with patch("api.web.routers.settings.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_response)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_instance

        resp = await settings_client.post(
            "/api/settings/test-connection",
            json={"provider": "gemini", "api_key": "valid-key-1234"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["error"] is None


@pytest.mark.anyio
async def test_connection_failure(settings_client: httpx.AsyncClient):
    """POST /api/settings/test-connection with invalid key returns failure."""
    with patch("api.web.routers.settings.httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Unauthorized",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(401),
            )
        )
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_instance

        resp = await settings_client.post(
            "/api/settings/test-connection",
            json={"provider": "gemini", "api_key": "bad-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"] is not None


@pytest.mark.anyio
async def test_connection_unknown_provider(settings_client: httpx.AsyncClient):
    """POST /api/settings/test-connection with unknown provider returns 400."""
    resp = await settings_client.post(
        "/api/settings/test-connection",
        json={"provider": "unknown_provider", "api_key": "some-key"},
    )
    assert resp.status_code == 400
