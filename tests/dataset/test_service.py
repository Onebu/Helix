"""Tests for DatasetService: add, list, get, import, delete, summary."""

import json

import pytest
import yaml
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dataset.models import DatasetSummary, PriorityTier, TestCase
from api.dataset.service import DatasetService
from api.exceptions import PromptNotFoundError
from api.registry.models import PromptRegistration, VariableDefinition
from api.registry.service import PromptRegistry
from api.storage.models import Base


@pytest.fixture
async def session_factory():
    """Create an in-memory SQLite engine with all tables and return a session factory."""
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
async def registry(session_factory):
    """Create a PromptRegistry for registering prompts needed by DatasetService."""
    return PromptRegistry(session_factory)


@pytest.fixture
async def service(session_factory, registry) -> DatasetService:
    """Create a DatasetService and register a test prompt in the DB."""
    # Register a test prompt so DatasetService can find it
    await registry.register(
        PromptRegistration(
            id="test-prompt",
            purpose="Test prompt",
            template="Hello {{ name }}",
        )
    )
    return DatasetService(session_factory)


@pytest.fixture
def sample_case() -> TestCase:
    """Create a sample TestCase for testing."""
    return TestCase(
        name="Sample case",
        description="A test case for testing",
        chat_history=[{"role": "user", "content": "Hello"}],
        variables={"name": "Alice"},
        tools=[{"type": "function", "function": {"name": "greet"}}],
        expected_output={"content": "Hello Alice!"},
        tier=PriorityTier.CRITICAL,
        tags=["sample", "test"],
    )


class TestAddCase:
    """Tests for DatasetService.add_case."""

    @pytest.mark.asyncio
    async def test_add_case_stores_in_db(self, service, sample_case):
        await service.add_case("test-prompt", sample_case)
        # Verify by listing cases
        cases = await service.list_cases("test-prompt")
        assert len(cases) == 1
        assert cases[0].name == "Sample case"
        assert cases[0].tier == PriorityTier.CRITICAL

    @pytest.mark.asyncio
    async def test_add_case_returns_tuple(self, service, sample_case):
        result, warnings = await service.add_case("test-prompt", sample_case)
        assert isinstance(result, TestCase)
        assert result.id == sample_case.id
        assert result.name == sample_case.name
        assert isinstance(warnings, list)

    @pytest.mark.asyncio
    async def test_add_case_raises_prompt_not_found(self, service, sample_case):
        with pytest.raises(PromptNotFoundError):
            await service.add_case("nonexistent-prompt", sample_case)

    @pytest.mark.asyncio
    async def test_add_case_persists(self, service, sample_case):
        await service.add_case("test-prompt", sample_case)
        cases = await service.list_cases("test-prompt")
        assert len(cases) == 1

    @pytest.mark.asyncio
    async def test_add_multiple_cases(self, service):
        case1 = TestCase(name="Case 1")
        case2 = TestCase(name="Case 2")
        await service.add_case("test-prompt", case1)
        await service.add_case("test-prompt", case2)
        cases = await service.list_cases("test-prompt")
        assert len(cases) == 2

    @pytest.mark.asyncio
    async def test_source_metadata_round_trips(self, service):
        case = TestCase(
            id="source-case",
            variables={"input": "hello"},
            source_metadata={"type": "observability", "external_id": "item-1"},
        )

        await service.add_case("test-prompt", case)

        stored = await service.get_case("test-prompt", case.id)
        assert stored.source_metadata == case.source_metadata

    @pytest.mark.asyncio
    async def test_add_cases_returns_warnings_by_case_id(self, service):
        cases = [
            TestCase(id="one", variables={"name": "One"}),
            TestCase(id="two", variables={"name": "Two"}),
        ]

        created, warnings = await service.add_cases("test-prompt", cases)

        assert created == cases
        assert warnings == {"one": [], "two": []}

    @pytest.mark.asyncio
    async def test_add_cases_loads_prompt_schema_once(
        self, service, session_factory
    ):
        engine = session_factory.kw["bind"]
        prompt_selects: list[str] = []

        def capture_prompt_select(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ):
            if statement.lstrip().upper().startswith("SELECT") and "prompts" in statement:
                prompt_selects.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", capture_prompt_select)
        try:
            await service.add_cases(
                "test-prompt",
                [TestCase(id="one"), TestCase(id="two"), TestCase(id="three")],
            )
        finally:
            event.remove(
                engine.sync_engine, "before_cursor_execute", capture_prompt_select
            )

        assert len(prompt_selects) == 1

    @pytest.mark.asyncio
    async def test_add_cases_rolls_back_the_whole_batch(
        self, service, monkeypatch
    ):
        original = service._validate_variables
        calls = 0

        async def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("invalid second case")
            return await original(*args, **kwargs)

        monkeypatch.setattr(service, "_validate_variables", fail_second)

        with pytest.raises(ValueError, match="invalid second case"):
            await service.add_cases(
                "test-prompt", [TestCase(id="one"), TestCase(id="two")]
            )

        assert await service.list_cases("test-prompt") == []


class TestListCases:
    """Tests for DatasetService.list_cases."""

    @pytest.mark.asyncio
    async def test_list_cases_returns_all(self, service):
        case1 = TestCase(name="Case 1")
        case2 = TestCase(name="Case 2")
        await service.add_case("test-prompt", case1)
        await service.add_case("test-prompt", case2)
        cases = await service.list_cases("test-prompt")
        assert len(cases) == 2
        assert all(isinstance(c, TestCase) for c in cases)

    @pytest.mark.asyncio
    async def test_list_cases_sorted_by_id(self, service):
        # Add cases with known IDs to verify sorting
        case_a = TestCase(id="aaa-case")
        case_b = TestCase(id="bbb-case")
        case_c = TestCase(id="ccc-case")
        # Add in reverse order
        await service.add_case("test-prompt", case_c)
        await service.add_case("test-prompt", case_a)
        await service.add_case("test-prompt", case_b)
        cases = await service.list_cases("test-prompt")
        assert [c.id for c in cases] == ["aaa-case", "bbb-case", "ccc-case"]

    @pytest.mark.asyncio
    async def test_list_cases_empty(self, service):
        cases = await service.list_cases("test-prompt")
        assert cases == []

    @pytest.mark.asyncio
    async def test_list_cases_nonexistent_prompt_returns_empty(self, service):
        # Non-existent prompt returns empty list (no cases found)
        cases = await service.list_cases("nonexistent-prompt")
        assert cases == []


class TestGetCase:
    """Tests for DatasetService.get_case."""

    @pytest.mark.asyncio
    async def test_get_case_returns_specific_case(self, service, sample_case):
        await service.add_case("test-prompt", sample_case)
        result = await service.get_case("test-prompt", sample_case.id)
        assert result.id == sample_case.id
        assert result.name == sample_case.name
        assert result.tier == PriorityTier.CRITICAL

    @pytest.mark.asyncio
    async def test_get_case_not_found_raises_value_error(self, service):
        with pytest.raises(ValueError):
            await service.get_case("test-prompt", "nonexistent-id")


class TestImportCases:
    """Tests for DatasetService.import_cases."""

    @pytest.mark.asyncio
    async def test_import_from_json_list(self, service, tmp_path):
        import_data = [
            {"name": "Imported 1", "tier": "critical"},
            {"name": "Imported 2", "tier": "low"},
        ]
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data))

        imported = await service.import_cases("test-prompt", import_file)
        assert len(imported) == 2
        assert all(isinstance(c, TestCase) for c in imported)
        assert imported[0].name == "Imported 1"
        assert imported[0].tier == PriorityTier.CRITICAL

    @pytest.mark.asyncio
    async def test_import_from_json_wrapper(self, service, tmp_path):
        import_data = {
            "cases": [
                {"name": "Wrapped 1"},
                {"name": "Wrapped 2"},
            ]
        }
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data))

        imported = await service.import_cases("test-prompt", import_file)
        assert len(imported) == 2

    @pytest.mark.asyncio
    async def test_import_from_yaml(self, service, tmp_path):
        import_data = [
            {"name": "YAML Case 1", "tier": "normal"},
            {"name": "YAML Case 2", "variables": {"key": "value"}},
        ]
        import_file = tmp_path / "import.yaml"
        import_file.write_text(yaml.dump(import_data))

        imported = await service.import_cases("test-prompt", import_file)
        assert len(imported) == 2
        assert imported[0].name == "YAML Case 1"

    @pytest.mark.asyncio
    async def test_import_from_yml_extension(self, service, tmp_path):
        import_data = [{"name": "YML Case"}]
        import_file = tmp_path / "import.yml"
        import_file.write_text(yaml.dump(import_data))

        imported = await service.import_cases("test-prompt", import_file)
        assert len(imported) == 1

    @pytest.mark.asyncio
    async def test_import_returns_test_case_objects(self, service, tmp_path):
        import_data = [{"name": "Check type"}]
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data))

        imported = await service.import_cases("test-prompt", import_file)
        assert len(imported) == 1
        case = imported[0]
        assert isinstance(case, TestCase)
        # Imported case should have auto-generated ID
        assert len(case.id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_import_cases_persisted(self, service, tmp_path):
        """Imported cases should be persisted in the DB."""
        import_data = [{"name": "Persisted"}]
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data))

        await service.import_cases("test-prompt", import_file)
        # Verify they exist in DB
        cases = await service.list_cases("test-prompt")
        assert len(cases) == 1
        assert cases[0].name == "Persisted"

    @pytest.mark.asyncio
    async def test_import_preserves_source_metadata(self, service, tmp_path):
        import_file = tmp_path / "import.json"
        import_file.write_text(
            json.dumps(
                [
                    {
                        "id": "imported-source",
                        "source_metadata": {
                            "type": "observability",
                            "external_id": "item-1",
                        },
                    }
                ]
            )
        )

        imported = await service.import_cases("test-prompt", import_file)

        assert imported[0].source_metadata == {
            "type": "observability",
            "external_id": "item-1",
        }


class TestDeleteCase:
    """Tests for DatasetService.delete_case."""

    @pytest.mark.asyncio
    async def test_delete_case_removes_from_db(self, service, sample_case):
        await service.add_case("test-prompt", sample_case)
        cases = await service.list_cases("test-prompt")
        assert len(cases) == 1

        await service.delete_case("test-prompt", sample_case.id)
        cases = await service.list_cases("test-prompt")
        assert len(cases) == 0

    @pytest.mark.asyncio
    async def test_delete_case_not_found_raises_value_error(self, service):
        with pytest.raises(ValueError):
            await service.delete_case("test-prompt", "nonexistent-id")


class TestSummary:
    """Tests for DatasetService.summary."""

    @pytest.mark.asyncio
    async def test_summary_with_cases(self, service):
        await service.add_case("test-prompt", TestCase(tier=PriorityTier.CRITICAL))
        await service.add_case("test-prompt", TestCase(tier=PriorityTier.CRITICAL))
        await service.add_case("test-prompt", TestCase(tier=PriorityTier.NORMAL))
        await service.add_case("test-prompt", TestCase(tier=PriorityTier.LOW))

        summary = await service.summary("test-prompt")
        assert isinstance(summary, DatasetSummary)
        assert summary.prompt_id == "test-prompt"
        assert summary.total_cases == 4
        assert summary.critical_count == 2
        assert summary.normal_count == 1
        assert summary.low_count == 1

    @pytest.mark.asyncio
    async def test_summary_empty_dataset(self, service):
        summary = await service.summary("test-prompt")
        assert summary.total_cases == 0
        assert summary.critical_count == 0
        assert summary.normal_count == 0
        assert summary.low_count == 0


class TestAddCaseValidation:
    """Tests for DatasetService.add_case validation warnings."""

    @pytest.mark.asyncio
    async def test_add_case_no_schema_empty_warnings(self, session_factory):
        """When prompt has no variable schema, warnings is empty list."""
        registry = PromptRegistry(session_factory)
        # Register a prompt without explicit variables
        await registry.register(
            PromptRegistration(
                id="no-vars-prompt",
                purpose="No vars",
                template="Static text with no variables",
            )
        )
        svc = DatasetService(session_factory)
        case = TestCase(name="no-schema", variables={"x": "hello"})
        result, warnings = await svc.add_case("no-vars-prompt", case)
        assert warnings == []
        assert isinstance(result, TestCase)

    @pytest.mark.asyncio
    async def test_add_case_with_schema_valid_variables(self, session_factory):
        """When variables match schema, warnings is empty list."""
        registry = PromptRegistry(session_factory)
        await registry.register(
            PromptRegistration(
                id="schema-prompt",
                purpose="With schema",
                template="Hello {{ name }}",
                variables=[
                    VariableDefinition(name="name", var_type="string", required=True),
                ],
            )
        )
        svc = DatasetService(session_factory)
        case = TestCase(name="valid-case", variables={"name": "Alice"})
        _result, warnings = await svc.add_case("schema-prompt", case)
        assert warnings == []

    @pytest.mark.asyncio
    async def test_add_case_with_schema_type_mismatch(self, session_factory):
        """When variable type mismatches schema, warnings are produced but case is still created."""
        registry = PromptRegistry(session_factory)
        await registry.register(
            PromptRegistration(
                id="type-prompt",
                purpose="Type mismatch test",
                template="Hello {{ name }}",
                variables=[
                    VariableDefinition(name="name", var_type="string", required=True),
                ],
            )
        )
        svc = DatasetService(session_factory)
        case = TestCase(name="type-mismatch", variables={"name": 42})
        _result, warnings = await svc.add_case("type-prompt", case)
        assert len(warnings) >= 1
        assert any("string" in w for w in warnings)
        # Case should still be created (warn-but-allow)
        cases = await svc.list_cases("type-prompt")
        assert len(cases) == 1

    @pytest.mark.asyncio
    async def test_add_case_with_schema_missing_required(self, session_factory):
        """When required variable missing, warning is produced but case is created."""
        registry = PromptRegistry(session_factory)
        await registry.register(
            PromptRegistration(
                id="required-prompt",
                purpose="Missing required test",
                template="Hello {{ name }}",
                variables=[
                    VariableDefinition(name="name", var_type="string", required=True),
                ],
            )
        )
        svc = DatasetService(session_factory)
        case = TestCase(name="missing-required", variables={})
        _result, warnings = await svc.add_case("required-prompt", case)
        assert len(warnings) >= 1
        assert any("required" in w.lower() or "missing" in w.lower() for w in warnings)
        # Case is still created
        cases = await svc.list_cases("required-prompt")
        assert len(cases) == 1
