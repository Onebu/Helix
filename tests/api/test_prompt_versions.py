"""Tests for prompt versioning: ORM model, service methods, and API endpoints."""

from __future__ import annotations

import httpx
import pytest


# -- Helpers --


async def _register_prompt(
    client: httpx.AsyncClient,
    prompt_id: str = "test-prompt",
    template: str = "Hello {{ name }}",
    purpose: str = "A test prompt",
) -> httpx.Response:
    """POST a new prompt and return the response."""
    return await client.post(
        "/api/prompts/",
        json={
            "id": prompt_id,
            "purpose": purpose,
            "template": template,
        },
    )


# ============================================================================
# Task 1: Service-level version tests
# ============================================================================


class TestVersionAutoCreation:
    """Registering a prompt auto-creates version 1."""

    async def test_register_creates_version_1(self, client, db_engine):
        """Registering a prompt auto-creates version 1 in prompt_versions table."""
        await _register_prompt(client, "ver-prompt", "Hello {{ name }}")

        # Query the prompt_versions table directly
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.storage.models import PromptVersion

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            result = await session.execute(
                select(PromptVersion).where(PromptVersion.prompt_id == "ver-prompt")
            )
            versions = result.scalars().all()

        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].template == "Hello {{ name }}"


class TestCreateVersion:
    """create_version returns the new version with incremented version number."""

    async def test_create_version_increments(self, client, db_engine):
        """create_version returns version 2 after initial version 1."""
        await _register_prompt(client, "cv-prompt", "Original template")

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.registry.service import PromptRegistry

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        registry = PromptRegistry(session_factory)
        result = await registry.create_version("cv-prompt", "Evolved template v2")

        assert result["version"] == 2
        assert result["template"] == "Evolved template v2"
        assert "created_at" in result


class TestListVersions:
    """list_versions returns all versions ordered by version number."""

    async def test_list_versions_ordered(self, client, db_engine):
        """list_versions returns all versions in ascending order."""
        await _register_prompt(client, "lv-prompt", "Template v1")

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.registry.service import PromptRegistry

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        registry = PromptRegistry(session_factory)
        await registry.create_version("lv-prompt", "Template v2")
        await registry.create_version("lv-prompt", "Template v3")

        versions = await registry.list_versions("lv-prompt")

        assert len(versions) == 3
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2
        assert versions[2]["version"] == 3
        assert versions[0]["template"] == "Template v1"
        assert versions[1]["template"] == "Template v2"
        assert versions[2]["template"] == "Template v3"


class TestActivateVersion:
    """activate_version changes active version and updates Prompt.template."""

    async def test_activate_version_updates_prompt(self, client, db_engine):
        """activate_version updates Prompt.template to match the activated version."""
        await _register_prompt(client, "av-prompt", "Template v1")

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.registry.service import PromptRegistry
        from api.storage.models import Prompt

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        registry = PromptRegistry(session_factory)
        await registry.create_version("av-prompt", "Template v2")

        # Activate version 1 (not latest)
        result = await registry.activate_version("av-prompt", 1)

        assert result["version"] == 1
        assert result["template"] == "Template v1"

        # Verify Prompt.template was updated
        async with session_factory() as session:
            prompt_result = await session.execute(
                select(Prompt).where(Prompt.id == "av-prompt")
            )
            prompt = prompt_result.scalar_one()
            assert prompt.template == "Template v1"
            assert prompt.active_version == 1

    async def test_activate_nonexistent_version_raises(self, client, db_engine):
        """activate_version raises PromptNotFoundError for nonexistent version."""
        await _register_prompt(client, "av2-prompt", "Template v1")

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.exceptions import PromptNotFoundError
        from api.registry.service import PromptRegistry

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        registry = PromptRegistry(session_factory)

        with pytest.raises(PromptNotFoundError):
            await registry.activate_version("av2-prompt", 99)


class TestLoadPromptActiveVersion:
    """load_prompt returns the active version's template."""

    async def test_load_prompt_returns_active_template(self, client, db_engine):
        """load_prompt returns the active version's template, not necessarily latest."""
        await _register_prompt(client, "lp-prompt", "Template v1")

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.registry.service import PromptRegistry

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        registry = PromptRegistry(session_factory)

        # Create v2 (becomes active)
        await registry.create_version("lp-prompt", "Template v2")
        # Activate v1 back
        await registry.activate_version("lp-prompt", 1)

        # load_prompt should return v1 template
        record = await registry.load_prompt("lp-prompt")
        assert record.template == "Template v1"


class TestGetVersionTemplate:
    """get_version_template returns the template text for a specific version."""

    async def test_get_specific_version_template(self, client, db_engine):
        """get_version_template returns correct template for a version number."""
        await _register_prompt(client, "gvt-prompt", "Template v1")

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.registry.service import PromptRegistry

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        registry = PromptRegistry(session_factory)
        await registry.create_version("gvt-prompt", "Template v2")

        template = await registry.get_version_template("gvt-prompt", 1)
        assert template == "Template v1"

        template2 = await registry.get_version_template("gvt-prompt", 2)
        assert template2 == "Template v2"

    async def test_get_nonexistent_version_template_raises(self, client, db_engine):
        """get_version_template raises PromptNotFoundError for nonexistent version."""
        await _register_prompt(client, "gvt2-prompt", "Template v1")

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from api.exceptions import PromptNotFoundError
        from api.registry.service import PromptRegistry

        session_factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        registry = PromptRegistry(session_factory)

        with pytest.raises(PromptNotFoundError):
            await registry.get_version_template("gvt2-prompt", 99)


# ============================================================================
# Task 2: API endpoint tests
# ============================================================================


class TestListVersionsEndpoint:
    """GET /api/prompts/{id}/versions returns list of version objects."""

    async def test_list_versions_returns_versions(self, client):
        """GET /api/prompts/{id}/versions returns version list with is_active flag."""
        await _register_prompt(client, "ep-list", "Template v1")

        # Create v2 via accept endpoint
        await client.post(
            "/api/prompts/ep-list/versions/accept",
            json={"template": "Template v2"},
        )

        resp = await client.get("/api/prompts/ep-list/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["version"] == 1
        assert data[0]["template"] == "Template v1"
        assert data[0]["is_active"] is False  # v2 is active after accept
        assert data[1]["version"] == 2
        assert data[1]["template"] == "Template v2"
        assert data[1]["is_active"] is True
        assert "created_at" in data[0]

    async def test_list_versions_nonexistent_prompt_returns_404(self, client):
        """GET /api/prompts/nonexistent/versions returns 404."""
        resp = await client.get("/api/prompts/nonexistent/versions")
        assert resp.status_code == 404


class TestGetVersionEndpoint:
    """GET /api/prompts/{id}/versions/{version} returns single version."""

    async def test_get_single_version(self, client):
        """GET /api/prompts/{id}/versions/1 returns the version template."""
        await _register_prompt(client, "ep-get", "Template v1")

        resp = await client.get("/api/prompts/ep-get/versions/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert data["template"] == "Template v1"
        assert "created_at" in data

    async def test_get_nonexistent_version_returns_404(self, client):
        """GET /api/prompts/{id}/versions/99 returns 404."""
        await _register_prompt(client, "ep-get2", "Template v1")

        resp = await client.get("/api/prompts/ep-get2/versions/99")
        assert resp.status_code == 404


class TestActivateVersionEndpoint:
    """PUT /api/prompts/{id}/versions/{version}/activate switches active version."""

    async def test_activate_version_endpoint(self, client):
        """PUT /api/prompts/{id}/versions/1/activate returns activated version info."""
        await _register_prompt(client, "ep-act", "Template v1")

        # Create v2
        await client.post(
            "/api/prompts/ep-act/versions/accept",
            json={"template": "Template v2"},
        )

        # Activate v1
        resp = await client.put("/api/prompts/ep-act/versions/1/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert data["is_active"] is True

        # Verify prompt template was updated
        prompt_resp = await client.get("/api/prompts/ep-act")
        assert prompt_resp.json()["template"] == "Template v1"

    async def test_activate_nonexistent_version_returns_404(self, client):
        """PUT /api/prompts/{id}/versions/99/activate returns 404."""
        await _register_prompt(client, "ep-act2", "Template v1")

        resp = await client.put("/api/prompts/ep-act2/versions/99/activate")
        assert resp.status_code == 404


class TestAcceptVersionEndpoint:
    """POST /api/prompts/{id}/versions/accept creates a new version."""

    async def test_accept_creates_new_version(self, client):
        """POST /api/prompts/{id}/versions/accept returns 201 with new version."""
        await _register_prompt(client, "ep-accept", "Template v1")

        resp = await client.post(
            "/api/prompts/ep-accept/versions/accept",
            json={"template": "Evolved template v2"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["version"] == 2
        assert data["template"] == "Evolved template v2"
        assert data["is_active"] is True
        assert "created_at" in data

    async def test_accept_increments_version_numbers(self, client):
        """Multiple accepts increment version numbers correctly."""
        await _register_prompt(client, "ep-incr", "Template v1")

        resp2 = await client.post(
            "/api/prompts/ep-incr/versions/accept",
            json={"template": "Template v2"},
        )
        assert resp2.json()["version"] == 2

        resp3 = await client.post(
            "/api/prompts/ep-incr/versions/accept",
            json={"template": "Template v3"},
        )
        assert resp3.json()["version"] == 3


class TestRunResultsPromptId:
    """GET /api/history/run/by-uuid/{uuid}/results includes prompt_id."""

    async def test_run_results_includes_prompt_id(self):
        """RunResultsResponse now includes prompt_id field."""
        from fastapi import FastAPI

        from api.web.app import create_app
        from api.web.deps import get_config, get_database
        from api.web.run_manager import RunManager
        from api.config.models import GeneConfig
        from api.storage.database import Database
        from api.storage.models import EvolutionRun

        db = Database("sqlite+aiosqlite://")
        await db.create_tables()

        application = create_app()
        test_config = GeneConfig(
            database_url="sqlite+aiosqlite://",
        )
        application.dependency_overrides[get_config] = lambda: test_config
        application.dependency_overrides[get_database] = lambda: db
        application.state.run_manager = RunManager()

        # Insert a run
        session = await db.get_session()
        try:
            run = EvolutionRun(
                prompt_id="test-prompt",
                status="completed",
                meta_model="test",
                target_model="test",
                hyperparameters={},
                run_uuid="test-uuid-123",
            )
            session.add(run)
            await session.commit()
        finally:
            await session.close()

        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            resp = await c.get("/api/history/run/by-uuid/test-uuid-123/results")
            assert resp.status_code == 200
            data = resp.json()
            assert data["prompt_id"] == "test-prompt"

        await db.close()
