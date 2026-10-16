"""WebSocket stream of job/project events for the dashboard.

Messages: {"type": "job", "job": {...JobOut}} and {"type": "project", "project": {...}}.
A {"type": "ping"} is sent every 20 s so idle connections stay alive.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)
router = APIRouter(tags=["events"])


@router.websocket("/ws")
async def events(websocket: WebSocket) -> None:
    bus = websocket.app.state.bus
    await websocket.accept()
    queue = bus.subscribe()

    async def reader() -> None:
        # Clients don't send anything meaningful; this just detects disconnects.
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    reader_task = asyncio.create_task(reader())
    try:
        await websocket.send_json({"type": "hello"})
        while not reader_task.done():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                event = {"type": "ping"}
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(queue)
        reader_task.cancel()
