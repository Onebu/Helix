"""Tests for RunManager + EventBus integration.

Tests verify:
- RunManager.start_run with event_bus creates event_callback and passes to coro_factory
- evolution_complete event published on successful completion (from engine, not RunManager)
- evolution_complete event published on error (from RunManager)
- evolution_complete event published on cancellation (from RunManager)
- EventBus is created in app lifespan and available at app.state.event_bus
- Existing RunManager tests still pass (backward compatible)
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.config.models import GenerationConfig
from api.exceptions import BudgetExhaustedError
from api.web.event_bus import EventBus
from api.web.run_manager import RunInfo, RunManager


async def _await_run(rm: RunManager, run_id: str) -> None:
    with suppress(asyncio.CancelledError, Exception):
        await asyncio.wait_for(asyncio.shield(rm._runs[run_id].task), timeout=1)


# ---------------------------------------------------------------------------
# Tests: RunManager + EventBus integration
# ---------------------------------------------------------------------------


async def test_start_run_with_event_bus_creates_callback():
    """RunManager.start_run with event_bus creates an event_callback and passes it to coro_factory."""
    rm = RunManager()
    bus = EventBus()

    received_callback = None

    async def coro_factory(event_callback=None):
        nonlocal received_callback
        received_callback = event_callback
        if event_callback is not None:
            await event_callback("test_event", {"key": "value"})

    run_id = await rm.start_run("test-prompt", coro_factory, event_bus=bus)
    await _await_run(rm, run_id)

    # The factory should have received a non-None callback
    assert received_callback is not None

    # The event should have been published to the bus
    _queue, missed = bus.subscribe(run_id)
    assert len(missed) >= 1
    assert missed[0].type == "test_event"


async def test_start_run_without_event_bus_passes_none_callback():
    """RunManager.start_run without event_bus passes event_callback=None to coro_factory."""
    rm = RunManager()

    received_callback = "not_set"

    async def coro_factory(event_callback=None):
        nonlocal received_callback
        received_callback = event_callback

    run_id = await rm.start_run("test-prompt", coro_factory)
    await _await_run(rm, run_id)

    assert received_callback is None


async def test_evolution_complete_emitted_on_error():
    """When evolution task fails, RunManager emits evolution_complete with error info."""
    rm = RunManager()
    bus = EventBus()

    async def coro_factory(event_callback=None):
        raise RuntimeError("test error")

    run_id = await rm.start_run("test-prompt", coro_factory, event_bus=bus)
    queue, _ = bus.subscribe(run_id)
    event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event.type == "evolution_complete"
    assert event.data.get("termination_reason") == "error"
    assert "test error" in event.data.get("error", "")


async def test_evolution_complete_emitted_on_cancel():
    """When evolution task is cancelled, RunManager emits evolution_complete with cancelled status."""
    rm = RunManager()
    bus = EventBus()

    running = asyncio.Event()

    async def coro_factory(event_callback=None):
        running.set()
        await asyncio.Event().wait()

    run_id = await rm.start_run("test-prompt", coro_factory, event_bus=bus)
    queue, _ = bus.subscribe(run_id)
    await asyncio.wait_for(running.wait(), timeout=1)

    await rm.stop_run(run_id)
    event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event.type == "evolution_complete"
    assert event.data.get("termination_reason") == "cancelled"


async def test_shutdown_awaits_terminal_event_publication():
    rm = RunManager()
    publication_started = asyncio.Event()
    allow_publication = asyncio.Event()
    publication_completed = asyncio.Event()

    class BlockingBus:
        def create_run(self, run_id):
            pass

        async def publish(self, run_id, event_type, data):
            publication_started.set()
            await allow_publication.wait()
            publication_completed.set()

    async def coro_factory(event_callback=None):
        raise RuntimeError("broken")

    await rm.start_run("test-prompt", coro_factory, event_bus=BlockingBus())
    await asyncio.wait_for(publication_started.wait(), timeout=1)

    shutdown = asyncio.create_task(rm.shutdown())
    checkpoint = asyncio.Event()
    asyncio.get_running_loop().call_soon(checkpoint.set)
    await checkpoint.wait()
    assert not shutdown.done()

    allow_publication.set()
    await asyncio.wait_for(shutdown, timeout=1)
    assert publication_completed.is_set()
    assert not rm._event_tasks


async def test_no_duplicate_evolution_complete_on_success():
    """On success, RunManager does NOT emit evolution_complete (engine already did)."""
    rm = RunManager()
    bus = EventBus()

    async def coro_factory(event_callback=None):
        # Simulate what the engine does: emit evolution_complete itself
        if event_callback is not None:
            await event_callback(
                "evolution_complete",
                {
                    "termination_reason": "generations_complete",
                    "best_fitness": 0.9,
                },
            )

    run_id = await rm.start_run("test-prompt", coro_factory, event_bus=bus)
    await _await_run(rm, run_id)

    _queue, missed = bus.subscribe(run_id)
    evo_complete = [e for e in missed if e.type == "evolution_complete"]
    # Should have exactly 1 evolution_complete (from engine, not from RunManager)
    assert len(evo_complete) == 1
    assert evo_complete[0].data.get("termination_reason") == "generations_complete"


# ---------------------------------------------------------------------------
# Tests: EventBus on app.state
# ---------------------------------------------------------------------------


async def test_event_bus_on_app_state():
    """EventBus is created in app lifespan and available at app.state.event_bus."""
    from api.web.app import create_app

    app = create_app()

    # Simulate lifespan by using the async context manager directly
    async with app.router.lifespan_context(app):
        assert hasattr(app.state, "event_bus")
        assert isinstance(app.state.event_bus, EventBus)


# ---------------------------------------------------------------------------
# Tests: Error-terminated runs still persist via success path (BUG-05)
# ---------------------------------------------------------------------------


async def test_error_terminated_run_uses_success_path():
    """When IslandEvolver catches GatewayError and returns EvolutionResult(termination_reason='error'),
    RunManager._on_complete sees a successful task (no exception) and sets info.result.

    This proves that catching GatewayError inside IslandEvolver means the success
    branch of _on_complete runs, which triggers _persist_result.
    """
    rm = RunManager()
    bus = EventBus()

    # Simulate what IslandEvolver now does: catch GatewayError and return
    # an EvolutionResult with termination_reason="error" (instead of raising)
    class FakeResult:
        termination_reason = "error"

    async def coro_factory(event_callback=None):
        # Emit evolution_complete like the engine does
        if event_callback is not None:
            await event_callback(
                "evolution_complete",
                {
                    "termination_reason": "error",
                    "best_fitness": 0.5,
                },
            )
        return FakeResult()

    run_id = await rm.start_run("test-prompt", coro_factory, event_bus=bus)
    await _await_run(rm, run_id)

    info = rm._runs[run_id]
    # Success path: result is set, error is None
    assert info.result is not None
    assert info.error is None
    assert info.result.termination_reason == "error"

    # Task completed normally (no exception)
    assert info.task.exception() is None


@pytest.mark.parametrize(
    ("termination_reason", "expected_status"),
    [
        ("generations_complete", "completed"),
        ("error", "failed"),
        ("budget_exhausted", "budget_exhausted"),
        ("cancelled", "cancelled"),
    ],
)
async def test_result_termination_reason_controls_status(
    termination_reason: str,
    expected_status: str,
):
    rm = RunManager()

    class FakeResult:
        pass

    async def coro_factory(event_callback=None):
        result = FakeResult()
        result.termination_reason = termination_reason
        return result

    run_id = await rm.start_run("test-prompt", coro_factory)
    await _await_run(rm, run_id)

    status = rm.get_status(run_id)
    assert status["status"] == expected_status


@pytest.mark.parametrize(
    ("termination_reason", "expected_status"),
    [
        ("error", "failed"),
        ("budget_exhausted", "budget_exhausted"),
        ("cancelled", "cancelled"),
    ],
)
async def test_get_status_reads_completed_task_before_done_callback(
    termination_reason: str,
    expected_status: str,
):
    async def completed_result():
        return SimpleNamespace(termination_reason=termination_reason)

    task = asyncio.create_task(completed_result())
    await task
    info = RunInfo(
        run_id="race",
        prompt_id="test-prompt",
        task=task,
        started_at=datetime.now(UTC),
    )
    rm = RunManager()
    rm._runs[info.run_id] = info

    assert rm.get_status(info.run_id)["status"] == expected_status
    assert info.result is None
    assert info.termination_reason is None


@pytest.mark.parametrize(
    ("raised", "expected_status", "expected_reason"),
    [
        (BudgetExhaustedError("spent"), "budget_exhausted", "budget_exhausted"),
        (RuntimeError("broken"), "failed", "error"),
    ],
)
async def test_raised_terminal_error_is_statused_and_persisted(
    monkeypatch,
    raised: Exception,
    expected_status: str,
    expected_reason: str,
):
    rm = RunManager()
    persisted = asyncio.Event()
    persisted_info = None

    async def persist(info):
        nonlocal persisted_info
        persisted_info = info
        persisted.set()

    monkeypatch.setattr(rm, "_persist_result", persist)

    async def coro_factory(event_callback=None):
        raise raised

    run_id = await rm.start_run(
        "test-prompt",
        coro_factory,
        config=SimpleNamespace(),
        evolution_config=SimpleNamespace(),
    )
    await asyncio.wait_for(persisted.wait(), timeout=1)

    assert rm.get_status(run_id)["status"] == expected_status
    assert persisted_info.termination_reason == expected_reason
    assert persisted_info.result is None


async def test_outer_task_cancellation_is_statused_and_persisted(monkeypatch):
    rm = RunManager()
    running = asyncio.Event()
    persisted = asyncio.Event()
    persisted_info = None

    async def persist(info):
        nonlocal persisted_info
        persisted_info = info
        persisted.set()

    monkeypatch.setattr(rm, "_persist_result", persist)

    async def coro_factory(event_callback=None):
        running.set()
        await asyncio.Event().wait()

    run_id = await rm.start_run(
        "test-prompt",
        coro_factory,
        config=SimpleNamespace(),
        evolution_config=SimpleNamespace(),
    )
    await asyncio.wait_for(running.wait(), timeout=1)
    assert await rm.stop_run(run_id)
    await asyncio.wait_for(persisted.wait(), timeout=1)

    assert rm.get_status(run_id)["status"] == "cancelled"
    assert persisted_info.termination_reason == "cancelled"
    assert persisted_info.result is None


async def test_terminal_run_without_persistence_config_stays_in_memory(monkeypatch):
    rm = RunManager()
    persisted = asyncio.Event()

    async def persist(info):
        persisted.set()

    monkeypatch.setattr(rm, "_persist_result", persist)

    async def coro_factory(event_callback=None):
        raise BudgetExhaustedError("spent")

    run_id = await rm.start_run("test-prompt", coro_factory)
    await _await_run(rm, run_id)

    assert rm.get_status(run_id)["status"] == "budget_exhausted"
    assert not persisted.is_set()


async def test_shutdown_awaits_pending_persistence(monkeypatch):
    rm = RunManager()
    persistence_started = asyncio.Event()
    allow_persistence = asyncio.Event()
    persistence_completed = asyncio.Event()

    async def persist(info):
        persistence_started.set()
        await allow_persistence.wait()
        persistence_completed.set()

    monkeypatch.setattr(rm, "_persist_result", persist)

    async def coro_factory(event_callback=None):
        return SimpleNamespace(termination_reason="generations_complete")

    await rm.start_run(
        "test-prompt",
        coro_factory,
        config=SimpleNamespace(),
        evolution_config=SimpleNamespace(),
    )
    await asyncio.wait_for(persistence_started.wait(), timeout=1)

    shutdown = asyncio.create_task(rm.shutdown())
    checkpoint = asyncio.Event()
    asyncio.get_running_loop().call_soon(checkpoint.set)
    await checkpoint.wait()
    assert not shutdown.done()
    allow_persistence.set()
    await asyncio.wait_for(shutdown, timeout=1)

    assert persistence_completed.is_set()
    assert not rm._persistence_tasks


@pytest.mark.parametrize(
    ("termination_reason", "error", "expected_status"),
    [
        ("error", "broken", "failed"),
        ("budget_exhausted", "spent", "budget_exhausted"),
        ("cancelled", "cancelled", "cancelled"),
    ],
)
async def test_persistence_boundary_records_terminal_metadata_without_result(
    monkeypatch,
    termination_reason: str,
    error: str,
    expected_status: str,
):
    records = []

    class FakeEvolutionRun:
        id = None

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            records.append(self)

    class FakeSession:
        def add(self, record):
            pass

        async def commit(self):
            pass

        async def close(self):
            pass

    class FakeDatabase:
        def __init__(self, database_url):
            self.session = FakeSession()

        async def get_session(self):
            return self.session

        async def close(self):
            pass

    monkeypatch.setattr("api.storage.database.Database", FakeDatabase)
    monkeypatch.setattr("api.storage.models.EvolutionRun", FakeEvolutionRun)

    async def completed_task():
        return None

    task = asyncio.create_task(completed_task())
    await task
    generation_config = GenerationConfig(temperature=0.3, max_tokens=987, top_p=0.6)
    thinking_config = {"meta": {"thinking_budget": 42}}
    info = RunInfo(
        run_id="persist-terminal",
        prompt_id="test-prompt",
        task=task,
        started_at=datetime.now(UTC),
        error=error,
        termination_reason=termination_reason,
        config=SimpleNamespace(
            database_url="fake://",
            meta_model="meta",
            target_model="target",
            judge_model="judge",
        ),
        evolution_config=SimpleNamespace(model_dump=lambda: {"generations": 2}),
        effective_models={
            "meta_model": "effective-meta",
            "target_model": "effective-target",
            "judge_model": "effective-judge",
        },
        generation_config=generation_config,
        thinking_config=thinking_config,
    )

    await RunManager()._persist_result(info)

    assert len(records) == 1
    record = records[0]
    assert record.status == expected_status
    assert record.extra_metadata == {
        "termination_reason": termination_reason,
        "error": error,
    }
    assert record.best_fitness_score is None
    assert record.generations_completed == 0
    assert record.total_input_tokens == 0
    assert record.total_output_tokens == 0
    assert record.total_cost_usd == 0.0
    assert record.total_api_calls == 0
    assert record.hyperparameters == {
        "generations": 2,
        "inference": generation_config.model_dump(),
        "thinking": thinking_config,
    }


# ---------------------------------------------------------------------------
# Tests: Backward compatibility
# ---------------------------------------------------------------------------


async def test_run_manager_basic_operations_still_work():
    """Existing RunManager operations (status, list, stop, shutdown) work with coro_factory pattern."""
    rm = RunManager()

    running = asyncio.Event()

    async def coro_factory(event_callback=None):
        running.set()
        await asyncio.Event().wait()
        return "result"

    run_id = await rm.start_run("test-prompt", coro_factory)
    await asyncio.wait_for(running.wait(), timeout=1)

    # Check status
    status = rm.get_status(run_id)
    assert status is not None
    assert status["status"] == "running"
    assert status["prompt_id"] == "test-prompt"

    # List runs
    runs = rm.list_runs()
    assert len(runs) == 1

    # Stop run
    stopped = await rm.stop_run(run_id)
    assert stopped is True

    await _await_run(rm, run_id)
    status = rm.get_status(run_id)
    assert status["status"] == "cancelled"

    # Shutdown
    await rm.shutdown()
