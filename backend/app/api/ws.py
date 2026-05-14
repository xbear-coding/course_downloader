"""WebSocket 进度推送"""
import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理"""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        await ws.send_json({"type": "connected"})

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, message: dict):
        """向所有客户端广播消息"""
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def push_task_update(
        self,
        task_id: int,
        step: str,
        step_index: int,
        step_total: int,
        step_progress: int,
        total_progress: int,
        message: str,
    ):
        await self.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "step": step,
            "step_index": step_index,
            "step_total": step_total,
            "step_progress": step_progress,
            "total_progress": total_progress,
            "message": message,
        })

    async def push_task_done(self, task_id: int):
        await self.broadcast({"type": "task_done", "task_id": task_id})

    async def push_task_error(self, task_id: int, step: str, error: str):
        await self.broadcast({
            "type": "task_error",
            "task_id": task_id,
            "step": step,
            "error": error,
        })


manager = ConnectionManager()


@router.websocket("/ws/progress")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
