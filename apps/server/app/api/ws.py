"""WebSocket: stream live run events (logs / case progress) to the UI."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.logging_setup import get_logger
from app.services.events import event_hub

log = get_logger("api.ws")
router = APIRouter(tags=["ws"])


@router.websocket("/ws/runs/{run_id}")
async def run_events(websocket: WebSocket, run_id: int) -> None:
    await websocket.accept()
    queue = await event_hub.subscribe(run_id)
    log.info("ws subscribed run_id=%s", run_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        log.info("ws disconnected run_id=%s", run_id)
    finally:
        await event_hub.unsubscribe(run_id, queue)
        log.debug("ws unsubscribed run_id=%s", run_id)
