"""Shared test fixtures for API tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.web.app import create_app
from api.web.deps import (
    _get_session_factory,
    get_config,
    get_dataset_service,
    get_db_session,
    get_registry,
)
from api.web.auth import get_current_user
from api.web.event_bus import EventBus
from api.web.run_manager import RunManager
from api.config.models import GeneConfig
from api.dataset.service import DatasetService
from api.registry.service import PromptRegistry
from api.storage.models import Base, User


@pytest.fixture
async def db_engine():
    """Create an in-memory SQLite engine with all tables."""
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
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session backed by in-memory SQLite."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
def app(db_engine) -> FastAPI:
    """Create a fresh FastAPI app with DB-backed services.

    Uses DB-backed PromptRegistry and DatasetService with the shared
    in-memory SQLite engine for test isolation.
    """
    application = create_app()

    test_config = GeneConfig(
        database_url=None,
    )

    # DB session factory using shared in-memory engine
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # DB-backed services
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

    # Override auth with a fixed test user
    _test_user = User(id=1, username="testuser", hashed_password="", is_active=True)
    application.dependency_overrides[get_current_user] = lambda: _test_user

    # Manually set up app state that lifespan would create
    # (ASGI transport does not invoke lifespan events)
    application.state.run_manager = RunManager()
    application.state.event_bus = EventBus()

    return application


@pytest.fixture
async def client(app: FastAPI):
    """Async HTTP client wired to the test app via ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
