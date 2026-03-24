"""Tests for the GET /api/history/run/{run_id}/results endpoint.

Tests use an in-memory SQLite database to verify run results queries
including lineage_events, case_results, seed_case_results, and best_candidate_id.
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


async def _insert_run(
    db: Database,
    prompt_id: str = "test-prompt",
    extra_metadata: dict | None = None,
) -> EvolutionRun:
    """Insert a test EvolutionRun with optional extra_metadata and return it."""
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
            extra_metadata=extra_metadata,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run
    finally:
        await session.close()


# -- Tests --


async def test_results_returns_lineage_events(
    db: Database,
    db_client: httpx.AsyncClient,
):
    """GET /api/history/run/{id}/results returns lineage_events from extra_metadata."""
    lineage = [
        {
            "candidate_id": "c1",
            "parent_ids": [],
            "generation": 0,
            "island": 0,
            "fitness_score": 0.8,
            "rejected": False,
            "mutation_type": "seed",
            "survived": True,
            "template": "Hello {{ name }}",
        },
        {
            "candidate_id": "c2",
            "parent_ids": ["c1"],
            "generation": 1,
            "island": 0,
            "fitness_score": 0.95,
            "rejected": False,
            "mutation_type": "rcc",
            "survived": True,
            "template": "Hi {{ name }}!",
        },
    ]
    run = await _insert_run(db, extra_metadata={"lineage_events": lineage})

    resp = await db_client.get(f"/api/history/run/{run.id}/results")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["lineage_events"]) == 2
    assert data["lineage_events"][0]["candidate_id"] == "c1"
    assert data["lineage_events"][1]["candidate_id"] == "c2"
    assert data["lineage_events"][1]["parent_ids"] == ["c1"]


async def test_results_null_metadata_returns_empty(
    db: Database,
    db_client: httpx.AsyncClient,
):
    """GET /api/history/run/{id}/results returns empty arrays when extra_metadata is null."""
    run = await _insert_run(db, extra_metadata=None)

    resp = await db_client.get(f"/api/history/run/{run.id}/results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["lineage_events"] == []
    assert data["case_results"] == []
    assert data["seed_case_results"] == []
    assert data["best_candidate_id"] is None
    assert data["best_template"] is None


async def test_results_returns_case_results(
    db: Database,
    db_client: httpx.AsyncClient,
):
    """GET /api/history/run/{id}/results returns case_results from extra_metadata."""
    cases = [
        {
            "case_id": "case-1",
            "tier": "critical",
            "score": 1.0,
            "passed": True,
            "reason": "Matched",
            "expected": {"content": "hello"},
            "actual_content": "hello",
            "actual_tool_calls": None,
        },
        {
            "case_id": "case-2",
            "tier": "normal",
            "score": 0.5,
            "passed": False,
            "reason": "Partial match",
        },
    ]
    run = await _insert_run(db, extra_metadata={"case_results": cases})

    resp = await db_client.get(f"/api/history/run/{run.id}/results")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["case_results"]) == 2
    assert data["case_results"][0]["case_id"] == "case-1"
    assert data["case_results"][0]["passed"] is True
    assert data["case_results"][1]["case_id"] == "case-2"
    assert data["case_results"][1]["passed"] is False


async def test_results_returns_404_for_nonexistent_run(
    db_client: httpx.AsyncClient,
):
    """GET /api/history/run/999/results returns 404 for non-existent run_id."""
    resp = await db_client.get("/api/history/run/999/results")
    assert resp.status_code == 404


async def test_results_returns_best_candidate_id(
    db: Database,
    db_client: httpx.AsyncClient,
):
    """GET /api/history/run/{id}/results returns best_candidate_id and best_template."""
    lineage = [
        {
            "candidate_id": "seed-1",
            "parent_ids": [],
            "generation": 0,
            "island": 0,
            "fitness_score": 0.5,
            "rejected": False,
            "mutation_type": "seed",
            "survived": True,
            "template": "Original prompt",
        },
        {
            "candidate_id": "best-1",
            "parent_ids": ["seed-1"],
            "generation": 1,
            "island": 0,
            "fitness_score": 1.0,
            "rejected": False,
            "mutation_type": "rcc",
            "survived": True,
            "template": "Evolved prompt",
        },
    ]
    run = await _insert_run(
        db,
        extra_metadata={
            "lineage_events": lineage,
            "best_candidate_id": "best-1",
        },
    )

    resp = await db_client.get(f"/api/history/run/{run.id}/results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["best_candidate_id"] == "best-1"
    assert data["best_template"] == "Evolved prompt"
