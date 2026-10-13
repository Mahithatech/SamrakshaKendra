"""Connection manager for live alert notifications."""
from __future__ import annotations

import asyncio
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: dict) -> int:
        async with self._lock:
            peers = list(self._connections)
        delivered = 0
        dead: list[WebSocket] = []
        for websocket in peers:
            try:
                await websocket.send_json(payload)
                delivered += 1
            except (RuntimeError, WebSocketDisconnect):
                dead.append(websocket)
            except Exception:
                dead.append(websocket)
        if dead:
            async with self._lock:
                for websocket in dead:
                    self._connections.discard(websocket)
        return delivered

    @property
    def active_connections(self) -> int:
        return len(self._connections)


manager = ConnectionManager()
