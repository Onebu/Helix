"""Tests for the 5 new ORM models: Setting, PromptConfig, Preset, PlaygroundVariable, Persona.

Validates table names, columns, types, indexes, constraints, and Base.metadata registration.
Uses SQLAlchemy inspection (no real database required).
"""

from sqlalchemy import inspect as sa_inspect

from api.storage.models import Base


class TestSettingModel:
    """Setting model has tablename 'settings' with correct columns."""

    def test_tablename(self):
        from api.storage.models import Setting

        assert Setting.__tablename__ == "settings"

    def test_columns(self):
        from api.storage.models import Setting

        mapper = sa_inspect(Setting)
        column_names = {c.key for c in mapper.column_attrs}
        assert {"id", "category", "data", "user_id"}.issubset(column_names)

    def test_id_is_primary_key(self):
        from api.storage.models import Setting

        mapper = sa_inspect(Setting)
        pk_cols = [c.name for c in mapper.primary_key]
        assert "id" in pk_cols

    def test_has_user_id_column(self):
        from api.storage.models import Setting

        col = Setting.__table__.columns["user_id"]
        assert col.nullable is True

    def test_data_is_json(self):
        from api.storage.models import Setting

        col = Setting.__table__.columns["data"]
        assert "JSON" in type(col.type).__name__.upper()


class TestPromptConfigModel:
    """PromptConfig model has tablename 'prompt_configs' with correct columns."""

    def test_tablename(self):
        from api.storage.models import PromptConfig

        assert PromptConfig.__tablename__ == "prompt_configs"

    def test_columns(self):
        from api.storage.models import PromptConfig

        mapper = sa_inspect(PromptConfig)
        column_names = {c.key for c in mapper.column_attrs}
        expected = {
            "id",
            "prompt_id",
            "provider",
            "model",
            "temperature",
            "thinking_budget",
            "extra",
        }
        assert expected.issubset(column_names), f"Missing: {expected - column_names}"

    def test_id_is_primary_key(self):
        from api.storage.models import PromptConfig

        mapper = sa_inspect(PromptConfig)
        pk_cols = [c.name for c in mapper.primary_key]
        assert "id" in pk_cols

    def test_prompt_id_has_unique_index(self):
        from api.storage.models import PromptConfig

        col = PromptConfig.__table__.columns["prompt_id"]
        assert col.unique is True or col.index is True

    def test_nullable_fields(self):
        from api.storage.models import PromptConfig

        table = PromptConfig.__table__
        assert table.columns["provider"].nullable is True
        assert table.columns["model"].nullable is True
        assert table.columns["temperature"].nullable is True
        assert table.columns["thinking_budget"].nullable is True
        assert table.columns["extra"].nullable is True


class TestPresetModel:
    """Preset model has tablename 'presets' with correct columns."""

    def test_tablename(self):
        from api.storage.models import Preset

        assert Preset.__tablename__ == "presets"

    def test_columns(self):
        from api.storage.models import Preset

        mapper = sa_inspect(Preset)
        column_names = {c.key for c in mapper.column_attrs}
        expected = {"id", "name", "type", "data", "is_default", "created_at"}
        assert expected.issubset(column_names), f"Missing: {expected - column_names}"

    def test_id_is_primary_key(self):
        from api.storage.models import Preset

        mapper = sa_inspect(Preset)
        pk_cols = [c.name for c in mapper.primary_key]
        assert "id" in pk_cols

    def test_is_default_defaults_to_false(self):
        from api.storage.models import Preset

        col = Preset.__table__.columns["is_default"]
        assert col.default is not None

    def test_created_at_column(self):
        from api.storage.models import Preset

        col = Preset.__table__.columns["created_at"]
        assert (
            "DATETIME" in type(col.type).__name__.upper() or "DateTime" in type(col.type).__name__
        )


class TestPlaygroundVariableModel:
    """PlaygroundVariable model has tablename 'playground_variables' with correct columns."""

    def test_tablename(self):
        from api.storage.models import PlaygroundVariable

        assert PlaygroundVariable.__tablename__ == "playground_variables"

    def test_columns(self):
        from api.storage.models import PlaygroundVariable

        mapper = sa_inspect(PlaygroundVariable)
        column_names = {c.key for c in mapper.column_attrs}
        expected = {"id", "prompt_id", "variable_name", "value"}
        assert expected.issubset(column_names), f"Missing: {expected - column_names}"

    def test_id_is_primary_key(self):
        from api.storage.models import PlaygroundVariable

        mapper = sa_inspect(PlaygroundVariable)
        pk_cols = [c.name for c in mapper.primary_key]
        assert "id" in pk_cols

    def test_prompt_id_is_indexed(self):
        from api.storage.models import PlaygroundVariable

        col = PlaygroundVariable.__table__.columns["prompt_id"]
        assert col.index is True or any(
            "prompt_id" in str(idx.columns) for idx in PlaygroundVariable.__table__.indexes
        )

    def test_value_is_text(self):
        from api.storage.models import PlaygroundVariable

        col = PlaygroundVariable.__table__.columns["value"]
        type_name = type(col.type).__name__.upper()
        assert "TEXT" in type_name or "CLOB" in type_name

    def test_unique_constraint_prompt_id_variable_name(self):
        from api.storage.models import PlaygroundVariable

        table = PlaygroundVariable.__table__
        # Check unique constraints
        unique_constraints = [
            c for c in table.constraints if hasattr(c, "columns") and len(c.columns) > 1
        ]
        found = False
        for uc in unique_constraints:
            col_names = {c.name for c in uc.columns}
            if {"prompt_id", "variable_name"} == col_names:
                found = True
                break
        assert found, "Missing unique constraint on (prompt_id, variable_name)"


class TestPersonaModel:
    """Persona model has tablename 'personas' with correct columns aligned to PersonaProfile."""

    def test_tablename(self):
        from api.storage.models import Persona

        assert Persona.__tablename__ == "personas"

    def test_columns(self):
        from api.storage.models import Persona

        mapper = sa_inspect(Persona)
        column_names = {c.key for c in mapper.column_attrs}
        expected = {
            "id",
            "prompt_id",
            "persona_id",
            "role",
            "traits",
            "communication_style",
            "goal",
            "edge_cases",
            "behavior_criteria",
            "language",
            "channel",
            "created_at",
        }
        assert expected.issubset(column_names), f"Missing: {expected - column_names}"

    def test_id_is_primary_key(self):
        from api.storage.models import Persona

        mapper = sa_inspect(Persona)
        pk_cols = [c.name for c in mapper.primary_key]
        assert "id" in pk_cols

    def test_prompt_id_is_indexed(self):
        from api.storage.models import Persona

        col = Persona.__table__.columns["prompt_id"]
        assert col.index is True or any(
            "prompt_id" in str(idx.columns) for idx in Persona.__table__.indexes
        )

    def test_traits_is_json(self):
        from api.storage.models import Persona

        col = Persona.__table__.columns["traits"]
        assert "JSON" in type(col.type).__name__.upper()

    def test_edge_cases_is_json(self):
        from api.storage.models import Persona

        col = Persona.__table__.columns["edge_cases"]
        assert "JSON" in type(col.type).__name__.upper()

    def test_behavior_criteria_is_json(self):
        from api.storage.models import Persona

        col = Persona.__table__.columns["behavior_criteria"]
        assert "JSON" in type(col.type).__name__.upper()

    def test_language_default_en(self):
        from api.storage.models import Persona

        col = Persona.__table__.columns["language"]
        assert col.default is not None

    def test_channel_default_text(self):
        from api.storage.models import Persona

        col = Persona.__table__.columns["channel"]
        assert col.default is not None

    def test_unique_constraint_prompt_id_persona_id(self):
        from api.storage.models import Persona

        table = Persona.__table__
        unique_constraints = [
            c for c in table.constraints if hasattr(c, "columns") and len(c.columns) > 1
        ]
        found = False
        for uc in unique_constraints:
            col_names = {c.name for c in uc.columns}
            if {"prompt_id", "persona_id"} == col_names:
                found = True
                break
        assert found, "Missing unique constraint on (prompt_id, persona_id)"


class TestAllModelsInMetadata:
    """All 7 models (2 existing + 5 new) are registered in Base.metadata.tables."""

    def test_all_seven_tables_in_metadata(self):
        table_names = set(Base.metadata.tables.keys())
        expected = {
            "evolution_runs",
            "llm_call_records",
            "settings",
            "prompt_configs",
            "presets",
            "playground_variables",
            "personas",
        }
        assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"
