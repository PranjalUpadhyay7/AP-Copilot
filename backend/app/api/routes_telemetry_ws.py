"""WS /telemetry -- live vehicle telemetry stream."""
from __future__ import annotations

import asyncio
import logging
import threading
from types import SimpleNamespace

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.session_manager import session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/telemetry")
async def telemetry_ws(websocket: WebSocket, session_id: str) -> None:
    """Stream live telemetry, plus LINK up/down events, over a WebSocket."""
    await websocket.accept()
    try:
        session = session_manager.get(session_id)
    except KeyError:
        await websocket.close(code=4404, reason="no such session")
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop_event = threading.Event()

    def push(event) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def producer() -> None:
        link_up: bool | None = None
        while not stop_event.is_set():
            try:
                client = session.context.vehicle_client
                if not client.is_connected:
                    raise ConnectionError("link down")
                for event in client.stream_telemetry(timeout=1.0):
                    if stop_event.is_set():
                        return
                    if link_up is not True:
                        link_up = True
                        push(SimpleNamespace(field="LINK", value={"up": True}))
                    push(event)
            except Exception as e:  # noqa: BLE001 -- connection dropped or being replaced: retry below
                logger.debug("telemetry stream interrupted, retrying: %s", e)
            if link_up is not False:
                link_up = False
                push(SimpleNamespace(field="LINK", value={"up": False}))
            # Retry: a reboot replaces the vehicle client under this thread
            stop_event.wait(1.0)

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()

    try:
        while True:
            event = await queue.get()
            await websocket.send_json({"field": event.field, "value": event.value})
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
