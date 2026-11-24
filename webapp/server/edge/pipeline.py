"""Vận hành MỘT LƯỢT XE, từ lúc nút làn gửi ảnh về tới lúc thanh chắn hạ xuống.

Trình tự (khớp Hình 3 và bảng ngân sách thời gian - Bảng 8 của báo cáo W3-4):

    nút làn POST ảnh
        -> GHI ĐĨA rồi mới trả mã xác nhận      (mục 3.6: ACK nghĩa là ảnh đã an toàn)
        -> xếp hàng đợi của đúng cổng            (nhận ảnh tách khỏi nhận dạng)
        -> bước 3+4+5: recognizer.read_frames()  (luồng riêng, tuần tự giữa hai cổng)
        -> bước 6: logic.process_capture()       (nghiệp vụ vào-ra của phần web, KHÔNG viết lại)
        -> quyết định OPEN  : mở chắn, chờ C2, hạ chắn
           quyết định HOLD  : giữ chắn hạ, người trực xử lý trên web

Hai cổng có hàng đợi riêng và chạy độc lập, nên xe ở làn này không phải chờ làn kia
(chỉ tiêu "≥ 30 lượt liên tục"). Riêng phần suy luận AI dùng chung một giấy phép
(AI_CONCURRENCY = 1) để hai làn không giành nhau 4 nhân của Pi.
"""
import asyncio
import csv
import time
from pathlib import Path

from .. import db, logic
from . import barrier, config, images
from .recognizer import decode_files, recognizer

_log = print


class Pipeline:
    def __init__(self):
        self.queues: dict[str, asyncio.Queue] = {}
        self.tasks: list[asyncio.Task] = []
        self.sem = asyncio.Semaphore(config.AI_CONCURRENCY)
        self.loop = None            # vòng lặp sự kiện của server, để gọi được từ luồng khác
        self.started = False
        self.stats = {"nhan": 0, "tu_choi_day_hang": 0, "lay_lai_sau_mat_dien": 0,
                      "mo": 0, "giu": 0, "loi": 0}

    # ------------------------------------------------------------ vòng đời
    async def start(self):
        if self.started:
            return
        self.started = True
        loop = self.loop = asyncio.get_running_loop()
        barrier.start(loop)
        for gate in ("IN", "OUT"):
            self.queues[gate] = asyncio.Queue(maxsize=config.QUEUE_MAX)
            self.tasks.append(asyncio.create_task(self._worker(gate), name=f"edge-{gate}"))
        self._recover_spool()
        # nạp model ở luồng riêng để không chặn lúc server khởi động
        asyncio.create_task(asyncio.to_thread(self._safe_load))
        _log(f"[edge] đã chạy. chế độ chắn={config.BARRIER_MODE}, nguồn C2={config.C2_SOURCE}, "
             f"nhiều khung={'bật' if config.MULTIFRAME else 'tắt'}")

    def _safe_load(self):
        try:
            recognizer.load()
        except Exception as e:
            _log(f"[edge] LỖI nạp model: {type(e).__name__}: {e}")

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        self.tasks.clear()
        self.started = False
        barrier.panic_open()

    def is_full(self, gate: str) -> bool:
        q = self.queues.get(gate)
        return q is not None and q.full()

    # ------------------------------------------------------------ lấy lại ảnh sót
    def _recover_spool(self):
        """Ảnh đã trả mã xác nhận nhưng chưa xử lý xong trước khi mất điện thì xử lý tiếp.

        Đây là nửa sau của cam kết ở mục 3.6, và là phần làm cho kịch bản 9 (mất điện khối
        trung tâm) không mất lượt nào đã được xác nhận.
        """
        for gate in ("IN", "OUT"):
            d = config.spool_dir() / gate
            if not d.is_dir():
                continue
            for tmp in d.glob(".*.tmp"):          # ghi dở lúc mất điện, không dùng được
                tmp.unlink(missing_ok=True)
            groups: dict[str, list[Path]] = {}
            for p in sorted(d.glob("*.jpg")):
                groups.setdefault(p.stem.rsplit("_", 1)[0], []).append(p)
            for stamp in sorted(groups):
                paths = sorted(groups[stamp])
                self.queues[gate].put_nowait(
                    {"gate": gate, "paths": paths, "device_id": "",
                     "when": db.now_utc(), "t_recv": time.perf_counter()})
                self.stats["lay_lai_sau_mat_dien"] += 1
            if groups:
                _log(f"[edge:{gate}] lấy lại {len(groups)} lượt còn sót trong thư mục chờ")

    # ------------------------------------------------------------ nhận ảnh
    async def submit(self, gate: str, paths, device_id: str = "", when=None) -> dict:
        """routes.capture gọi vào đây SAU KHI ảnh đã ghi xuống đĩa. Trả ngay, không chờ nhận dạng."""
        await self.start()
        q = self.queues[gate]
        if q.full():                       # routes đã kiểm tra trước, đây là chốt chặn cuối
            self.stats["tu_choi_day_hang"] += 1
            for p in paths:
                Path(p).unlink(missing_ok=True)
            raise logic.ApiError(503, "QUEUE_FULL", "Hàng đợi đầy, nút gửi lại sau.")
        q.put_nowait({"gate": gate, "paths": [Path(p) for p in paths], "device_id": device_id,
                      "when": when or db.now_utc(), "t_recv": time.perf_counter()})
        self.stats["nhan"] += 1
        return {"queued": q.qsize()}

    # ------------------------------------------------------------ vòng xử lý
    async def _worker(self, gate: str):
        q = self.queues[gate]
        while True:
            item = await q.get()
            try:
                await self._one_pass(item)
                for p in item["paths"]:        # xử lý xong thì dọn thư mục chờ
                    p.unlink(missing_ok=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.stats["loi"] += 1
                _log(f"[edge:{gate}] lỗi xử lý lượt xe: {type(e).__name__}: {e}")
                self._quarantine(item["paths"])
            finally:
                q.task_done()

    @staticmethod
    def _quarantine(paths):
        """Lượt lỗi thì chuyển ảnh sang thư mục riêng, không bỏ và cũng không thử lại vô hạn."""
        for p in paths:
            try:
                bad = p.parent / "loi"
                bad.mkdir(exist_ok=True)
                p.replace(bad / p.name)
            except OSError:
                pass

    async def _one_pass(self, item):
        gate, t_recv = item["gate"], item["t_recv"]
        dev = db.one("SELECT * FROM devices WHERE gate=?", (gate,))
        device_id = item["device_id"] or (dev["device_id"] if dev else gate)
        if dev:
            logic.set_state(device_id, "WAITING_SERVER")

        # ---- bước 3, 4, 5 -------------------------------------------------
        t0 = time.perf_counter()
        frames = await asyncio.to_thread(decode_files, item["paths"])
        if not frames:
            raise ValueError(f"không giải mã được khung nào trong {len(item['paths'])} tệp")
        async with self.sem:
            r, frame = await asyncio.to_thread(recognizer.read_frames, frames)
        t_ai = time.perf_counter()

        if not r.readable:
            _log(f"[edge:{gate}] không đọc được ({r.decided_by}): {r.reason}")

        # ---- bước 6: nghiệp vụ vào - ra (của phần web) ---------------------
        ev = logic.process_capture(
            gate,
            r.plate,
            r.conf if r.readable else None,
            make_images=images.saver(frame, r.crop, r.box),
            when=item["when"],
        )
        t_db = time.perf_counter()

        timings = {
            "cho_hang_doi_ms": round((t0 - t_recv) * 1000, 1),
            "giai_ma_va_ai_ms": round((t_ai - t0) * 1000, 1),
            **{f"{k}_ms": v for k, v in r.ms.items()},
            "nghiep_vu_ms": round((t_db - t_ai) * 1000, 1),
            "tong_tren_pi_ms": round((t_db - t_recv) * 1000, 1),
        }
        _log(f"[edge:{gate}] #{ev['event_id']} {ev['status']}/{ev['decision']} "
             f"biển={ev['plate']} conf={ev['confidence']} | {r.decided_by} | "
             f"{timings['tong_tren_pi_ms']} ms "
             f"(detect {r.ms.get('detect', 0)} + ocr {r.ms.get('ocr', 0)})")
        self._write_timing(ev, r, timings)

        # ---- điều khiển thanh chắn ----------------------------------------
        if ev["decision"] == "OPEN":
            self.stats["mo"] += 1
            await self._open_and_wait(gate, ev["event_id"], device_id)
        else:
            self.stats["giu"] += 1
            # HOLD: thanh chắn vẫn ở vị trí hạ, không làm gì thêm.
            # Người trực bấm "cho qua" trên web -> logic.override -> hook ở __init__ mở chắn.

    async def _open_and_wait(self, gate: str, event_id: int, device_id: str):
        def on_timeout(g):
            logic.create_alert(
                "C2_TIMEOUT",
                f"Cổng {g}: cảm biến C2 không báo xe đã qua sau {config.C2_TIMEOUT_S:.0f} giây. "
                f"Thanh chắn đang GIỮ MỞ, cần kiểm tra tại chỗ.",
                event_id=event_id, device_id=device_id)

        res = await barrier.get(gate).pass_vehicle(on_timeout=on_timeout)
        if res == "OK" and db.one("SELECT 1 FROM devices WHERE device_id=?", (device_id,)):
            logic.set_state(device_id, "IDLE")

    # ------------------------------------------------------------ số đo
    COLS = ["thoi_diem", "event_id", "cong", "bien_so", "ocr_conf", "det_conf", "agree",
            "so_khung_doc", "so_box_thu", "quyet_dinh_boi", "quyet_dinh", "trang_thai",
            "detect_ms", "ocr_ms", "nghiep_vu_ms", "tong_tren_pi_ms"]

    def _write_timing(self, ev, r, timings):
        if not config.TIMING_CSV:
            return
        p = Path(config.TIMING_CSV)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # Tệp cũ có tiêu đề khác (thêm cột ở phiên bản này) thì sang tệp mới, khỏi lẫn cột.
            if p.exists():
                with p.open(encoding="utf-8") as f:
                    if (f.readline().strip().split(",") or []) != self.COLS:
                        p = p.with_name(p.stem + "-v2" + p.suffix)
            new = not p.exists()
            with p.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(self.COLS)
                w.writerow([ev["time"], ev["event_id"], ev["gate"], ev["plate"] or "",
                            f"{r.conf:.3f}", f"{r.det_conf:.3f}", f"{r.agree:.2f}",
                            r.frames_read, r.boxes_tried, r.decided_by,
                            ev["decision"], ev["status"], r.ms.get("detect", ""),
                            r.ms.get("ocr", ""), timings["nghiep_vu_ms"],
                            timings["tong_tren_pi_ms"]])
        except Exception as e:
            _log(f"[edge] không ghi được {config.TIMING_CSV}: {e}")


pipeline = Pipeline()
