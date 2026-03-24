"""Tests for evolution history endpoints.

Tests use an in-memory SQLite database to verify history queries.
"""

from __future__ import annotations


import httpx
import pytest
from fastapi import FastAPI

from api.web.app import create_app
from api.web.deps import get_config, get_database
from api.config.models import GeneConfig
from api.storage.database import Database
from api.storage.models import EvolutionRun


# -- Fixtures --


@pytest.fixture
async def db():
    """Create an in-memory SQLite database for testing."""
    database = Database("sqlite+aiosqlite://")
    await database.create_tables()
    yield database
    await database.close()


@pytest.fixture
def db_app(db: Database) -> FastAPI:
    """App with database dependency overridden to use in-memory SQLite."""
    application = create_app()

    test_config = GeneConfig(
        database_url="sqlite+aiosqlite://",
    )

    application.dependency_overrides[get_config] = lambda: test_config
    application.dependency_overrides[get_database] = lambda: db

    # Set up RunManager for app state (ASGI transport doesn't invoke lifespan)
    from api.web.run_manager import RunManager

    application.state.run_manager = RunManager()

    return application


@pytest.fixture
async def db_client(db_app: FastAPI):
    """Async HTTP client for the db_app."""
    transport = httpx.ASGITransport(app=db_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# -- Helpers --


async def _insert_run(db: Database, prompt_id: str = "test-prompt") -> EvolutionRun:
    """Insert a test EvolutionRun and return it."""
    session = await db.get_session()
    try:
        run = EvolutionRun(
            prompt_id=prompt_id,
            status="completed",
            meta_model="test-meta",
            target_model="test-target",
            judge_model="test-judge",
            hyperparameters={"generations": 5},
            total_cost_usd=0.50,
            best_fitness_score=0.95,
            generations_completed=5,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run
    finally:
        await session.close()


# -- GET /api/history/{prompt_id} --


async def test_history_empty_returns_list(
    db_client: httpx.AsyncClient,
):
    """GET /api/history/test-prompt with no runs returns empty list."""
    resp = await db_client.get("/api/history/test-prompt")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_history_with_runs(
    db: Database,
    db_client: httpx.AsyncClient,
):
    """GET /api/history/test-prompt with runs returns list with correct fields."""
    await _insert_run(db, "test-prompt")

    resp = await db_client.get("/api/history/test-prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["prompt_id"] == "test-prompt"
    assert item["status"] == "completed"
    assert item["best_fitness_score"] == 0.95
    assert item["total_cost_usd"] == 0.50
    assert item["generations_completed"] == 5
    assert item["meta_model"] == "test-meta"
    assert item["target_model"] == "test-target"


async def test_history_no_db_returns_503(
    client: httpx.AsyncClient,
):
    """GET /api/history/test-prompt without DB configured returns 503."""
    resp = await client.get("/api/history/test-prompt")
    assert resp.status_code == 503


# -- GET /api/history/run/{run_id} --


async def test_get_run_detail(
    db: Database,
    db_client: httpx.AsyncClient,
):
    """GET /api/history/run/{id} returns correct fields."""
    run = await _insert_run(db, "test-prompt")

    resp = await db_client.get(f"/api/history/run/{run.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run.id
    assert data["prompt_id"] == "test-prompt"
    assert data["status"] == "completed"
    assert data["meta_model"] == "test-meta"


async def test_get_run_not_found(
    db_client: httpx.AsyncClient,
):
    """GET /api/history/run/999 returns 404."""
    resp = await db_client.get("/api/history/run/999")
    assert resp.status_code == 404
