"""Lớp biên GATE VISION chạy trên Raspberry Pi 4.

Gắn vào server web sẵn có bằng ĐÚNG MỘT DÒNG trong server/main.py:

    from .edge import install
    ...
    app = FastAPI(title="GATE VISION", lifespan=lifespan, ...)
    install(app)                      # <-- thêm dòng này ngay sau khi tạo app

Không cần sửa lifespan: hàng đợi và model tự khởi động ở lượt ảnh đầu tiên.
Muốn khởi động sớm (nạp model lúc bật máy cho lượt xe đầu không bị chậm) thì thêm
`await edge.pipeline.start()` vào lifespan, sau `seed_first_run()`.

Phân vai rõ ràng:
  - server/logic.py  giữ toàn bộ luật nghiệp vụ vào - ra. Lớp biên KHÔNG viết lại.
  - edge/            lo phần vật lý: ảnh từ nút làn, AI đọc biển, thanh chắn, cảm biến C2.
"""
from . import barrier, config, gpio, images, pipeline as _pipeline_mod, recognizer, routes
from .pipeline import pipeline

__all__ = ["install", "pipeline", "barrier", "config", "gpio", "recognizer", "routes"]

_log = print


def install(app):
    """Gắn endpoint của nút làn và nối lệnh mở chắn thủ công của người trực."""
    app.include_router(routes.router)
    _wrap_override()
    _log("[edge] đã gắn /esp32/capture, /esp32/event, /esp32/heartbeat, /esp32/command, /esp32/status")
    return app


_wrapped = False


def _wrap_override():
    """Người trực bấm "cho qua" trên web -> logic.override() -> mở thanh chắn.

    Bọc hàm thay vì sửa logic.py để phần web giữ nguyên, nâng cấp web không bị xung đột.
    Chỉ chạy thêm phần điều khiển phần cứng SAU KHI nghiệp vụ đã quyết định xong.
    """
    global _wrapped
    if _wrapped:
        return
    import asyncio

    from .. import logic

    original = logic.override

    def override(gate, event_id, action, *a, **kw):
        ev = original(gate, event_id, action, *a, **kw)
        if action == "PASS":
            p = _pipeline_mod.pipeline
            loop = p.loop
            if loop is None or loop.is_closed():
                _log(f"[edge:{gate}] lớp biên chưa chạy, bỏ qua mở chắn cho lượt #{event_id}")
                return ev
            dev = _device_id_of(gate)
            coro = p._open_and_wait(gate, event_id, dev)
            try:
                # cùng luồng với vòng lặp (endpoint async def)
                if asyncio.get_running_loop() is loop:
                    loop.create_task(coro)
                else:
                    asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                # gọi từ luồng khác (endpoint def thường, tác vụ nền) - vẫn mở được
                asyncio.run_coroutine_threadsafe(coro, loop)
            _log(f"[edge:{gate}] người trực cho qua lượt #{event_id} -> mở chắn")
        return ev

    logic.override = override
    _wrapped = True


def _device_id_of(gate: str) -> str:
    from .. import db
    r = db.one("SELECT device_id FROM devices WHERE gate=?", (gate,))
    return r["device_id"] if r else ("cam-a" if gate == "IN" else "cam-b")
