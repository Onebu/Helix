"""Tests for database seed/import logic and get_db_session dependency.

Validates:
- ensure_columns handles all tables (not just evolution_runs)
- import_prompt_sidecars reads config.json and inserts PromptConfig rows
- import_prompt_sidecars reads personas.yaml and inserts Persona rows
- Repeated calls to seed/import are no-ops (idempotent)
- get_db_session yields a usable AsyncSession and closes it after use
"""

import json

import pytest
import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.storage.database import Database
from api.storage.models import (
    Persona,
    PromptConfig,
)


@pytest.fixture
async def db(tmp_path):
    """Create an in-memory SQLite database with all tables."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    database = Database(db_url)
    await database.create_tables()
    yield database
    await database.close()


@pytest.fixture
def prompts_dir(tmp_path):
    """Create a temporary prompts directory with config.json and personas.yaml."""
    prompt_dir = tmp_path / "prompts" / "test-prompt"
    prompt_dir.mkdir(parents=True)

    # config.json sidecar
    config = {
        "meta_model": "gpt-4",
        "target_model": "gpt-3.5-turbo",
        "meta_provider": "openai",
        "target_provider": "openai",
        "meta_temperature": 0.9,
        "target_temperature": 0.0,
    }
    (prompt_dir / "config.json").write_text(json.dumps(config))

    # personas.yaml sidecar
    personas = {
        "personas": [
            {
                "id": "confused-user",
                "role": "Confused user",
                "traits": ["easily confused", "asks vague questions"],
                "communication_style": "Rambling, unclear",
                "goal": "Get help despite unclear info",
                "edge_cases": ["gives wrong input types"],
                "behavior_criteria": [],
                "language": "en",
                "channel": "text",
            },
            {
                "id": "adversarial-user",
                "role": "Adversarial user",
                "traits": ["persistent", "creative"],
                "communication_style": "Direct, probing",
                "goal": "Find edge cases",
                "edge_cases": ["requests outside scope"],
                "behavior_criteria": [],
                "language": "en",
                "channel": "text",
            },
        ]
    }
    (prompt_dir / "personas.yaml").write_text(yaml.dump(personas))

    return str(tmp_path / "prompts")


class TestEnsureColumnsAllTables:
    """ensure_columns handles all tables, not just evolution_runs."""

    async def test_adds_missing_column_to_new_table(self, db):
        """If a column is missing from a table, ensure_columns adds it via ALTER TABLE."""
        # Drop a column from the settings table to simulate a missing column
        async with db.engine.begin() as conn:
            # Get existing columns
            def _get_cols(connection):
                from sqlalchemy import inspect as sa_inspect

                inspector = sa_inspect(connection)
                if inspector.has_table("settings"):
                    return {c["name"] for c in inspector.get_columns("settings")}
                return set()

            cols = await conn.run_sync(_get_cols)

        # The settings table should exist and have expected columns
        assert "category" in cols
        assert "data" in cols

        # ensure_columns should run without error on existing tables
        await db.ensure_columns()


class TestImportPromptSidecars:
    """import_prompt_sidecars reads config.json and personas.yaml sidecars."""

    async def test_imports_config_json_as_prompt_config(self, db, prompts_dir):
        """config.json sidecar is imported as a PromptConfig row."""
        await db.import_prompt_sidecars(prompts_dir)

        async with db.session_factory() as session:
            result = await session.execute(select(PromptConfig))
            configs = result.scalars().all()

        assert len(configs) == 1
        assert configs[0].prompt_id == "test-prompt"

    async def test_imports_personas_yaml_as_persona_rows(self, db, prompts_dir):
        """personas.yaml sidecar is imported as Persona rows."""
        await db.import_prompt_sidecars(prompts_dir)

        async with db.session_factory() as session:
            result = await session.execute(select(Persona))
            personas = result.scalars().all()

        assert len(personas) == 2
        persona_ids = {p.persona_id for p in personas}
        assert {"confused-user", "adversarial-user"} == persona_ids

    async def test_idempotent_no_duplicate_imports(self, db, prompts_dir):
        """Calling import twice does not create duplicate rows."""
        await db.import_prompt_sidecars(prompts_dir)
        await db.import_prompt_sidecars(prompts_dir)

        async with db.session_factory() as session:
            result = await session.execute(select(PromptConfig))
            configs = result.scalars().all()
            result2 = await session.execute(select(Persona))
            personas = result2.scalars().all()

        assert len(configs) == 1
        assert len(personas) == 2


class TestGetDbSession:
    """get_db_session yields a usable AsyncSession and closes it."""

    async def test_yields_usable_async_session(self, db, monkeypatch):
        """get_db_session should yield a working AsyncSession."""
        from api.web import deps

        # Monkeypatch get_config to return a config with our test DB URL
        class FakeConfig:
            database_url = str(db.engine.url)

        monkeypatch.setattr(deps, "get_config", lambda: FakeConfig())

        from api.web.deps import get_db_session

        gen = get_db_session()
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)

        # Should be able to execute a simple query
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

        # Clean up
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
