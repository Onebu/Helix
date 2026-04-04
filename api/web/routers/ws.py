"""WebSocket endpoints for evolution and synthesis event streaming.

Provides real-time event streaming with reconnection replay support.
Protocol:
1. Server sends {"type": "connected", "run_id": X}
2. Client sends {"type": "subscribe", "last_event_id": N}
3. Server replays missed events (event_id > N) from ring buffer
4. Server streams live events until terminal event

Routes:
    WS /ws/evolution/{run_id}   Connect to evolution event stream
    WS /ws/synthesis/{run_id}   Connect to synthesis event stream
"""

from __future__ import annotations

import asyncio

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.web.auth import decode_access_token, is_auth_disabled

router = APIRouter()


@router.websocket("/ws/evolution/{run_id}")
async def evolution_ws(websocket: WebSocket, run_id: str, token: str | None = None) -> None:
    """Stream evolution events over WebSocket with replay support.

    Accepts the connection, sends a connected message, waits for a
    subscribe message with optional last_event_id, replays missed
    events from the ring buffer, then streams live events until
    evolution_complete is received or the client disconnects.

    Args:
        websocket: The WebSocket connection.
        run_id: Unique identifier for the evolution run to stream.
        token: Optional JWT token for authentication.
    """
    if not is_auth_disabled():
        if token is None:
            await websocket.close(code=4001, reason="Missing auth token")
            return
        try:
            decode_access_token(token)
        except jwt.PyJWTError:
            await websocket.close(code=4001, reason="Invalid token")
            return
    await websocket.accept()
    event_bus = websocket.app.state.event_bus

    # 1. Send connected message
    await websocket.send_json({"type": "connected", "run_id": run_id})

    # 2. Wait for subscribe message
    try:
        raw = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    last_event_id = raw.get("last_event_id", 0)

    # 3. Subscribe to EventBus (queue added to subscribers before replay)
    queue, missed = event_bus.subscribe(run_id, last_event_id)

    try:
        # 4. Replay missed events from ring buffer
        for event in missed:
            await websocket.send_json(event.model_dump())

        # 5. Stream live events until evolution_complete.
        # Uses short timeout + retry to handle cross-thread queue
        # puts that may not wake asyncio.Queue.get() immediately
        # (e.g., when events are published from non-ASGI threads).
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                # Check if the queue has items (cross-thread put_nowait
                # may have placed an item without waking the waiter)
                if not queue.empty():
                    event = queue.get_nowait()
                else:
                    continue
            await websocket.send_json(event.model_dump())
            if event.type == "evolution_complete":
                break
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(run_id, queue)


@router.websocket("/ws/synthesis/{run_id}")
async def synthesis_ws(websocket: WebSocket, run_id: str, token: str | None = None) -> None:
    """Stream synthesis events over WebSocket with replay support.

    Follows the same protocol as evolution_ws: connected -> subscribe ->
    replay -> stream. Terminal event is "synthesis_complete" or "synthesis_failed".

    Args:
        websocket: The WebSocket connection.
        run_id: Unique identifier for the synthesis run to stream.
        token: Optional JWT token for authentication.
    """
    if not is_auth_disabled():
        if token is None:
            await websocket.close(code=4001, reason="Missing auth token")
            return
        try:
            decode_access_token(token)
        except jwt.PyJWTError:
            await websocket.close(code=4001, reason="Invalid token")
            return
    await websocket.accept()
    event_bus = websocket.app.state.event_bus

    # 1. Send connected message
    await websocket.send_json({"type": "connected", "run_id": run_id})

    # 2. Wait for subscribe message
    try:
        raw = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    last_event_id = raw.get("last_event_id", 0)

    # 3. Subscribe to EventBus
    queue, missed = event_bus.subscribe(run_id, last_event_id)

    try:
        # 4. Replay missed events
        for event in missed:
            await websocket.send_json(event.model_dump())

        # 5. Stream live events until synthesis_complete or synthesis_failed
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                if not queue.empty():
                    event = queue.get_nowait()
                else:
                    continue
            await websocket.send_json(event.model_dump())
            if event.type in ("synthesis_complete", "synthesis_failed"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(run_id, queue)
