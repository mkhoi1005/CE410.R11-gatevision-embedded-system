"""Các endpoint mà nút ESP32-CAM gọi: capture, event, heartbeat, command.

Đây chính là phần "v2 mục 6.1" mà README_SERVER.md ghi là CHƯA làm.
Không đụng tới các endpoint của web (v2 mục 6.3).

Bảo vệ: các endpoint này không dùng cookie đăng nhập của người trực mà dùng một mã
chia sẻ đặt trong biến môi trường GV_NODE_TOKEN. Mạng ở cổng là mạng riêng do Pi tự
phát, nhưng có mã vẫn hơn, tránh một thiết bị lạ vào mạng rồi bơm ảnh giả.
Không đặt GV_NODE_TOKEN thì bỏ qua kiểm tra (tiện lúc chạy thử trên bàn).
"""
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, Request, UploadFile

from .. import db, logic
from ..logic import ApiError, device_out
from . import barrier, config
from .pipeline import pipeline

router = APIRouter(prefix="/esp32", tags=["esp32"])
MAX_JPEG = 2 * 1024 * 1024      # ảnh ESP32-CAM cỡ vài chục KB; 2 MB là rộng rãi


def _auth(token):
    want = os.environ.get("GV_NODE_TOKEN", "")
    if want and token != want:
        raise ApiError(401, "UNAUTHORIZED", "Mã thiết bị không đúng.")


def _touch_device(device_id: str, gate: str, ip: str = None, rssi: int = None, state: str = None):
    """Cập nhật bảng devices: có heartbeat thì coi là online. Thiếu thì tạo mới."""
    now = db.iso(db.now_utc())
    row = db.one("SELECT * FROM devices WHERE device_id=?", (device_id,))
    with db.conn:
        if row is None:
            db.conn.execute(
                "INSERT INTO devices(device_id,gate,ip,rssi,state,online,last_seen,boot_at,stream_url)"
                " VALUES (?,?,?,?,?,1,?,?,NULL)",
                (device_id, gate, ip, rssi, state or "IDLE", now, time.time()))
        else:
            db.conn.execute(
                "UPDATE devices SET gate=?, ip=COALESCE(?,ip), rssi=COALESCE(?,rssi),"
                " state=COALESCE(?,state), online=1, last_seen=? WHERE device_id=?",
                (gate, ip, rssi, state, now, device_id))
    row = db.one("SELECT * FROM devices WHERE device_id=?", (device_id,))
    from ..hub import hub
    hub.emit({"type": "device_status", "data": device_out(row)})
    logic.resolve_alerts("device_id=? AND type='DEVICE_OFFLINE'", (device_id,))
    return row


# ---------------------------------------------------------------- ghi ảnh xuống đĩa
def _spool(gate: str, blobs) -> list[Path]:
    """Ghi các khung của MỘT lượt xuống thư mục chờ, rồi mới cho phép trả mã xác nhận.

    Mục 3.6 của báo cáo: "mã xác nhận chỉ được trả về sau khi ảnh đã ghi xuống bộ nhớ chứ
    không phải ngay khi nhận". Nên ở đây ghi thật, gọi fsync, rồi đổi tên nguyên tử - mất
    điện giữa đường thì chỉ còn lại tệp .tmp, không bao giờ còn một tệp .jpg dở dang.
    """
    d = config.spool_dir() / gate
    d.mkdir(parents=True, exist_ok=True)
    stamp = f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    paths = []
    for i, data in enumerate(blobs):
        tmp, final = d / f".{stamp}_{i}.tmp", d / f"{stamp}_{i}.jpg"
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
        paths.append(final)
    try:                                  # fsync cả thư mục để tên tệp chắc chắn lên đĩa
        fd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, AttributeError):
        pass                              # hệ tệp không cho fsync thư mục thì bỏ qua
    return paths


# ---------------------------------------------------------------- 1. nộp ảnh
@router.post("/capture")
async def capture(request: Request,
                  image: list[UploadFile] = File(...),
                  gate: str = Form(...),
                  device_id: str = Form(""),
                  ts: float = Form(0.0),
                  x_node_token: str = Header(default="")):
    """Nút làn gửi ảnh khi cảm biến C1 báo có xe.

    multipart/form-data:
        image     - MỘT hoặc NHIỀU phần cùng tên "image", mỗi phần là một khung JPEG.
                    Nút gửi khung nét nhất TRƯỚC, tối đa GV_MAX_FRAMES khung (mặc định 3).
                    Khối trung tâm đọc khung đầu, chỉ đọc tiếp khi khung đó trượt chốt chặn.
        gate      - IN | OUT  (chấp nhận cả VAO/RA/A/B)
        device_id - mã thiết bị, ví dụ cam-a
        ts        - mốc thời gian của nút (giây, epoch). Bỏ trống thì lấy giờ của Pi.

    Trả mã 200 sau khi ảnh ĐÃ GHI XUỐNG ĐĨA, chưa chờ nhận dạng xong. Nút nhận được 200
    là ảnh đã an toàn và ngừng gửi lại (Bảng 5, đường W1/W2).
    Hàng đợi đầy thì trả 503 và KHÔNG giữ ảnh, để nút gửi lại theo đúng ba lần ở bước 2.
    """
    _auth(x_node_token)
    try:
        g = config.gate_of(gate)
    except ValueError as e:
        raise ApiError(422, "INVALID_GATE", str(e))

    blobs = []
    for up in image[:max(config.MAX_FRAMES, 1)]:
        data = await up.read()
        if not data:
            continue
        if len(data) > MAX_JPEG:
            raise ApiError(413, "IMAGE_TOO_LARGE", f"Ảnh {len(data)} byte, vượt {MAX_JPEG} byte.")
        blobs.append(data)
    if not blobs:
        raise ApiError(422, "EMPTY_IMAGE", "Không có khung ảnh nào hợp lệ.")

    did = device_id or ("cam-a" if g == "IN" else "cam-b")
    ip = request.client.host if request.client else None
    _touch_device(did, g, ip=ip, state="CAPTURING")

    when = None
    if ts:
        from datetime import datetime, timezone
        # Đồng hồ của nút có thể lệch; chỉ nhận nếu trong khoảng ±5 phút so với giờ Pi.
        dt = datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0)
        if abs((dt - db.now_utc()).total_seconds()) <= 300:
            when = dt

    await pipeline.start()
    if pipeline.is_full(g):
        raise ApiError(503, "QUEUE_FULL",
                       "Khối trung tâm đang xử lý hết công suất, nút gửi lại sau.")

    paths = _spool(g, blobs)              # ghi đĩa TRƯỚC
    r = await pipeline.submit(g, paths, device_id=did, when=when)   # rồi mới xếp hàng
    return {"ok": True, "gate": g, "device_id": did,
            "frames": len(blobs), "bytes": sum(len(b) for b in blobs), **r}


# ---------------------------------------------------------------- 2. sự kiện cảm biến
@router.post("/event")
async def node_event(gate: str = Form(...),
                     type: str = Form(...),
                     device_id: str = Form(""),
                     x_node_token: str = Header(default="")):
    """Sự kiện rời rạc từ nút làn.

    type = C2_PASSED : cảm biến C2 báo xe đã qua hẳn thanh chắn -> được phép hạ chắn.
    type = C1_TRIGGER: chỉ để ghi nhận, ảnh sẽ tới ngay sau đó bằng /esp32/capture.
    """
    _auth(x_node_token)
    try:
        g = config.gate_of(gate)
    except ValueError as e:
        raise ApiError(422, "INVALID_GATE", str(e))
    kind = str(type).strip().upper()

    if kind == "C2_PASSED":
        if config.C2_SOURCE == "gpio":
            return {"ok": True, "ignored": "đang cấu hình đọc C2 bằng GPIO của Pi"}
        barrier.get(g).c2_passed()
        return {"ok": True, "gate": g, "type": kind}

    if kind == "C1_TRIGGER":
        did = device_id or ("cam-a" if g == "IN" else "cam-b")
        _touch_device(did, g, state="DETECTED")
        return {"ok": True, "gate": g, "type": kind}

    raise ApiError(422, "UNKNOWN_EVENT", f"Loại sự kiện không hiểu: {type!r}")


# ---------------------------------------------------------------- 3. heartbeat
@router.post("/heartbeat")
async def heartbeat(request: Request,
                    device_id: str = Form(...),
                    gate: str = Form(...),
                    state: str = Form("IDLE"),
                    rssi: int = Form(None),
                    x_node_token: str = Header(default="")):
    """Nút gửi đều đặn (khuyến nghị 10 giây/lần). Quá 30 giây không có thì server báo mất kết nối."""
    _auth(x_node_token)
    try:
        g = config.gate_of(gate)
    except ValueError as e:
        raise ApiError(422, "INVALID_GATE", str(e))
    ip = request.client.host if request.client else None
    row = _touch_device(device_id, g, ip=ip, rssi=rssi, state=state)
    return {"ok": True, "server_time": db.iso(db.now_utc()), "state": row["state"]}


# ---------------------------------------------------------------- 4. lệnh cho nút
@router.get("/command")
async def command(device_id: str, x_node_token: str = Header(default="")):
    """Nút hỏi xem có việc gì phải làm không.

    Hiện chỉ trả trạng thái thanh chắn do Pi điều khiển, để nút biết mà hiển thị đèn.
    Thanh chắn do Pi giữ (Bảng 5, đường D4/D5), nút KHÔNG tự điều khiển.
    """
    _auth(x_node_token)
    row = db.one("SELECT * FROM devices WHERE device_id=?", (device_id,))
    if row is None:
        raise ApiError(404, "DEVICE_NOT_FOUND", "Chưa biết thiết bị này.")
    b = barrier.get(row["gate"])
    return {"ok": True, "gate": row["gate"], "barrier_open": b.is_open,
            "await_c2": b.is_open, "max_frames": config.MAX_FRAMES,
            "server_time": db.iso(db.now_utc())}


# ---------------------------------------------------------------- 5. tự kiểm tra
@router.get("/status")
async def status(x_node_token: str = Header(default="")):
    """Xem nhanh tình trạng lớp biên - tiện khi chạy thử và khi đo ở tuần 9."""
    _auth(x_node_token)
    return {
        "ok": True,
        "che_do_chan": config.BARRIER_MODE,
        "nguon_C2": config.C2_SOURCE,
        "nguong": {"det_conf": config.DET_CONF, "ocr_conf": config.OCR_MIN_CONF,
                   "ocr_agree": config.OCR_MIN_AGREE},
        "nhieu_khung": {"bat": config.MULTIFRAME, "toi_da": config.MAX_FRAMES,
                        "can_bao_nhieu_khung_dong_thuan": config.VOTE_MIN_FRAMES},
        "chon_box": {"thu_tu": config.DET_PICK, "so_box_toi_da": config.DET_MAX_BOXES},
        "hang_doi": {g: q.qsize() for g, q in pipeline.queues.items()},
        "thanh_chan": {g: ("MỞ" if b.is_open else "HẠ") for g, b in barrier.all_().items()},
        "thong_ke": pipeline.stats,
    }
