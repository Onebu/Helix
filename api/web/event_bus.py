"""EventBus for fan-out event distribution with replay support.

Provides per-run event publishing to multiple subscriber asyncio.Queues,
with a ring buffer per run for reconnection replay. Designed for
single-process, in-memory use (local-first tool, not multi-tenant).

Exports:
    EventBus: Fan-out event distribution with replay support.
    RING_BUFFER_SIZE: Maximum number of events stored per run for replay.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

from api.web.events import EvolutionEvent

# Maximum events stored per run for reconnection replay.
RING_BUFFER_SIZE: int = 1000


class EventBus:
    """Fan-out event distribution with replay support.

    Maintains per-run ring buffers of recent events and per-client
    asyncio.Queues for live event delivery. Subscribers that fall
    behind (QueueFull) are automatically removed.
    """

    def __init__(self) -> None:
        # run_id -> monotonic event counter
        self._counters: dict[str, int] = {}
        # run_id -> ring buffer of recent events
        self._buffers: dict[str, deque[EvolutionEvent]] = {}
        # run_id -> set of subscriber queues
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # run_id -> timestamp when cleanup_run was called (for expiry)
        self._completed_at: dict[str, float] = {}
        # Lock for publish() to ensure monotonic event_ids under concurrency
        self._lock = asyncio.Lock()

    def create_run(self, run_id: str) -> None:
        """Initialize tracking structures for a new run.

        Args:
            run_id: Unique identifier for the evolution run.
        """
        self._counters[run_id] = 0
        self._buffers[run_id] = deque(maxlen=RING_BUFFER_SIZE)
        self._subscribers[run_id] = set()

    async def publish(self, run_id: str, event_type: str, data: dict) -> None:
        """Publish an event to all subscribers and the ring buffer.

        Creates an EvolutionEvent with a monotonically increasing event_id,
        appends it to the run's ring buffer, and pushes it to all subscriber
        queues. Queues that are full are automatically removed.

        Args:
            run_id: The run to publish to.
            event_type: Event type string (e.g., "generation_started").
            data: Arbitrary event payload dict.
        """
        async with self._lock:
            self._counters[run_id] = self._counters.get(run_id, 0) + 1
            event = EvolutionEvent(
                event_id=self._counters[run_id],
                run_id=run_id,
                type=event_type,
                data=data,
            )

            # Store in ring buffer
            if run_id in self._buffers:
                self._buffers[run_id].append(event)

            # Fan-out to all subscribers
            dead_queues: set[asyncio.Queue] = set()
            for queue in self._subscribers.get(run_id, set()):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead_queues.add(queue)

            # Remove dead queues
            if dead_queues:
                self._subscribers[run_id] -= dead_queues

    def subscribe(
        self, run_id: str, last_event_id: int = 0
    ) -> tuple[asyncio.Queue, list[EvolutionEvent]]:
        """Subscribe to a run's events, returning missed events and a live queue.

        The queue is added to subscribers BEFORE replaying from the buffer,
        ensuring no events are missed between subscribe and the first queue.get().
        Clients should deduplicate by event_id if needed.

        Args:
            run_id: The run to subscribe to.
            last_event_id: Only replay events with event_id greater than this.
                Use 0 to receive all buffered events.

        Returns:
            Tuple of (asyncio.Queue for live events, list of missed events).
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        if run_id not in self._subscribers:
            self._subscribers[run_id] = set()
        self._subscribers[run_id].add(queue)

        # Replay missed events from ring buffer
        missed: list[EvolutionEvent] = []
        if run_id in self._buffers:
            for event in self._buffers[run_id]:
                if event.event_id > last_event_id:
                    missed.append(event)

        return queue, missed

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue.

        Args:
            run_id: The run to unsubscribe from.
            queue: The queue to remove.
        """
        if run_id in self._subscribers:
            self._subscribers[run_id].discard(queue)

    def cleanup_run(self, run_id: str) -> None:
        """Remove subscriber set for a completed run.

        Keeps the ring buffer for late reconnectors, but removes
        the subscriber set so no new events are delivered.
        Buffers are automatically purged after 30 minutes by purge_stale().

        Args:
            run_id: The run to clean up.
        """
        self._subscribers.pop(run_id, None)
        self._completed_at[run_id] = time.monotonic()

    def purge_stale(self, max_age_seconds: float = 1800) -> int:
        """Remove ring buffers and counters for runs completed more than max_age_seconds ago.

        Call periodically to prevent unbounded memory growth.

        Returns:
            Number of runs purged.
        """
        now = time.monotonic()
        stale = [
            rid for rid, completed in self._completed_at.items()
            if now - completed > max_age_seconds
        ]
        for rid in stale:
            self._buffers.pop(rid, None)
            self._counters.pop(rid, None)
            self._completed_at.pop(rid, None)
        return len(stale)
