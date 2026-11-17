"""Phát thông điệp thời gian thực tới các WebSocket. Dùng một hàng đợi để giữ đúng thứ tự."""
import asyncio

from . import config


class Hub:
    def __init__(self):
        self.clients = set()
        self.queue = None
        self.task = None
        self.blocked = False  # chỉ dùng cho công cụ thử (ngắt kết nối giả)

    def start(self):
        self.queue = asyncio.Queue()
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
        self.queue = None
        self.clients.clear()

    def emit(self, msg: dict):
        if self.queue is not None:
            self.queue.put_nowait(msg)

    async def _run(self):
        while True:
            msg = await self.queue.get()
            for ws in list(self.clients):
                try:
                    await ws.send_json(msg)
                except Exception:
                    self.clients.discard(ws)

    async def drop_all(self):
        for ws in list(self.clients):
            try:
                await ws.close(code=1012)
            except Exception:
                pass
        self.clients.clear()


hub = Hub()
