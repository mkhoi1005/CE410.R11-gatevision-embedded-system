"""Chạy thử các kịch bản của lớp biên, KHÔNG cần model AI và KHÔNG cần phần cứng.

    cd webapp
    python3 server/edge/tools/smoke_edge.py

Chỉ phần ĐỌC MỘT KHUNG được thay bằng hàm giả; mọi thứ còn lại là mã thật: endpoint,
ghi ảnh xuống đĩa trước khi trả mã xác nhận, hàng đợi, bỏ phiếu giữa các khung, nghiệp vụ
vào-ra, thanh chắn, cảm biến C2, ảnh bằng chứng, tệp số đo.

Hàm giả nhận "kịch bản" được mã hoá ngay trong ảnh (độ xám của một ô ở góc), nhờ vậy test
điều khiển được từng khung một mà không phải vá thêm gì vào mã thật.
Dùng cơ sở dữ liệu và thư mục ảnh tạm, không đụng tới dữ liệu đang chạy.
"""
import os, sys, time, tempfile, pathlib

if "server.edge.config" in sys.modules:
    # Bị gọi bằng `-m ...`: lúc đó gói server.edge đã nạp xong trước khi tệp này chạy, nên
    # các biến môi trường đặt bên dưới không còn tác dụng. Chạy lại dưới dạng tệp thường.
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), *sys.argv[1:]])

os.environ["GV_GPIO"] = "mock"
os.environ["GV_C2_SOURCE"] = "http"
os.environ["GV_C2_TIMEOUT_S"] = "3"
os.environ["GV_SERVO_TRAVEL_S"] = "0.05"       # cho test chạy nhanh, không ảnh hưởng logic
os.environ["GV_DATA_DIR"] = tempfile.mkdtemp(prefix="gvdata")
os.environ["GV_TIMING_CSV"] = os.environ["GV_DATA_DIR"] + "/timing.csv"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))   # .../webapp

import types

import cv2, numpy as np
from fastapi.testclient import TestClient

if "plate_ocr" not in sys.modules:
    # Máy chạy test có thể chưa chép plate_ocr.py từ nhánh AI. Chỉ cần đúng một hằng số,
    # và phải đúng 0,06 - con số bộ OCR được đánh giá cùng (không phải 0,08 ở pi_infer.py).
    _m = types.ModuleType("plate_ocr")
    _m.CROP_MARGIN = 0.06
    sys.modules["plate_ocr"] = _m

from server.edge import recognizer as rec_mod
from server.edge.recognizer import Reading

PLATE = "59-P1 664.80"
ALT = "59-P1 884.80"
_mode = {"readable": True, "plate": PLATE}


# ------------------------------------------------------------------ ảnh mang kịch bản
def mk(code=0, idx=0) -> bytes:
    """Ô góc trên trái mã hoá kịch bản, ô kế bên mã hoá số thứ tự lượt."""
    im = np.full((360, 480, 3), 60, np.uint8)
    cv2.putText(im, "59P1-66480", (60, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (240, 240, 240), 3)
    im[0:20, 0:20] = 20 + code * 40
    im[0:20, 30:50] = 20 + idx * 8
    return cv2.imencode(".jpg", im)[1].tobytes()


def _script(img):
    a = float(img[2:18, 2:18].mean())
    b = float(img[2:18, 32:48].mean())
    return int(round((a - 20) / 40)), int(round((b - 20) / 8))


def fake_read(self, img):
    """Thay cho Recognizer.read (đọc MỘT khung). read_frames vẫn là mã thật."""
    code, idx = _script(img)
    r = Reading(frames_read=1, boxes_tried=1)
    r.ms = {"detect": 41.0, "ocr": 88.0}
    r.det_conf, r.box = 0.93, (40.0, 60.0, 300.0, 160.0)
    r.crop = img[60:160, 40:300]

    if code == 1:                      # ảnh mờ: không đúng khuôn biển, trượt hẳn
        r.conf, r.valid, r.text = 0.31, False, ""
        r.reason = "chuỗi đọc được không đúng khuôn biển Việt Nam"
    elif code == 2:                    # đọc ra PLATE nhưng ba phiếu cắt dòng không khớp
        r.conf, r.valid, r.text, r.agree = 0.88, True, PLATE, 0.67
        r.reason = "ba phiếu cắt dòng không thống nhất (agree=0.67)"
    elif code == 3:                    # đọc ra biển KHÁC, cũng không khớp phiếu
        r.conf, r.valid, r.text, r.agree = 0.85, True, ALT, 0.67
        r.reason = "ba phiếu cắt dòng không thống nhất (agree=0.67)"
    elif code == 4:                    # đọc được nhưng chậm, để thử ACK-sau-khi-ghi-đĩa
        time.sleep(1.2)
        r.conf, r.valid, r.agree = 0.90, True, 1.0
        r.plate = r.text = PLATE
        r.readable = True
    elif code == 5:                    # mỗi lượt một biển khác nhau
        r.conf, r.valid, r.agree = 0.90, True, 1.0
        r.plate = r.text = f"59-P1 {600 + idx:03d}.80"
        r.readable = True
    else:                              # code 0: theo _mode
        r.agree, r.valid = 1.0, True
        if _mode["readable"]:
            r.conf, r.plate, r.text, r.readable = 0.91, _mode["plate"], _mode["plate"], True
        else:
            r.conf, r.valid, r.text = 0.31, False, ""
            r.reason = "độ tin cậy 0.31 dưới ngưỡng 0.60"
    return r


REAL_READ = rec_mod.Recognizer.read        # giữ bản thật để test riêng phần chọn box
rec_mod.Recognizer.load = lambda self: None
rec_mod.Recognizer.read = fake_read

from server import db, logic
from server.main import app
from server.edge import barrier, config as econf
from server.edge.pipeline import pipeline

fails = []
DATA = pathlib.Path(os.environ["GV_DATA_DIR"])


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def capture(c, gate, *codes, idx=0):
    """Gửi một lượt gồm len(codes) khung, khung đầu là khung 'nét nhất'."""
    codes = codes or (0,)
    files = [("image", (f"f{i}.jpg", mk(k, idx), "image/jpeg")) for i, k in enumerate(codes)]
    return c.post("/esp32/capture", files=files,
                  data={"gate": gate, "ts": f"{time.time():.3f}"})


def last_event(gate):
    return db.one("SELECT * FROM events WHERE gate=? ORDER BY event_id DESC LIMIT 1", (gate,))


def last_id(gate) -> int:
    e = last_event(gate)
    return e["event_id"] if e else 0


def wait_event(gate, after_id=0, t=10.0):
    end = time.time() + t
    while time.time() < end:
        e = last_event(gate)
        if e and e["event_id"] > after_id:
            return e
        time.sleep(0.05)
    return None


def wait_closed(gate, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if not barrier.get(gate).is_open:
            return True
        time.sleep(0.05)
    return False


def spool_jpgs(gate=None):
    d = econf.spool_dir() / gate if gate else econf.spool_dir()
    return sorted(d.rglob("*.jpg")) if d.is_dir() else []


def wait_spool_empty(gate, t=3.0):
    """Thư mục chờ chỉ được dọn SAU KHI cả lượt xe kết thúc (kể cả lúc hạ chắn), nên chờ."""
    end = time.time() + t
    while time.time() < end:
        if not spool_jpgs(gate):
            return True
        time.sleep(0.05)
    return False


def wait_plate(gate, plate, t=10.0):
    end = time.time() + t
    while time.time() < end:
        e = db.one("SELECT * FROM events WHERE gate=? AND plate=? ORDER BY event_id DESC LIMIT 1",
                   (gate, plate))
        if e:
            return e
        time.sleep(0.05)
    return None


def run_pass(c, gate, *codes, idx=0, c2=True):
    """Một lượt trọn vẹn: chốt mốc sự kiện trước, gửi ảnh, chờ đúng sự kiện của lượt này,
    rồi báo C2 nếu chắn đã mở. Chốt mốc trước là điều kiện để test không đọc lẫn lượt cũ.

    `gate` có thể là mã làn nút gửi lên (IN/VAO/A hoặc OUT/RA/B); phần tra cơ sở dữ liệu
    dùng cổng đã chuẩn hoá, vì CSDL chỉ lưu IN/OUT.
    """
    g = econf.gate_of(gate)
    prev = last_id(g)
    r = capture(c, gate, *codes, idx=idx)
    if r.status_code != 200:
        return r, None
    ev = wait_event(g, prev)
    if c2 and ev is not None and ev["decision"] == "OPEN":
        c.post("/esp32/event", data={"gate": gate, "type": "C2_PASSED"})
        wait_closed(g)
    return r, ev


with TestClient(app) as c:
    print("\n[1] /esp32/status")
    r = c.get("/esp32/status")
    check("status 200", r.status_code == 200, str(r.status_code))
    check("báo đúng nguồn C2", r.json().get("nguon_C2") == "http", r.json().get("nguon_C2"))
    check("báo đúng cấu hình nhiều khung",
          r.json().get("nhieu_khung", {}).get("bat") is econf.MULTIFRAME,
          f"bật={econf.MULTIFRAME}")

    print("\n[2] đầu vào sai bị chặn")
    check("422 cho mã làn lạ", capture(c, "COng-X").status_code == 422)
    r = c.post("/esp32/capture", files=[("image", ("f.jpg", b"", "image/jpeg"))],
               data={"gate": "IN"})
    check("422 cho ảnh rỗng", r.status_code == 422, str(r.status_code))

    print("\n[3] kịch bản 1 - xe vào bình thường")
    r = capture(c, "VAO")
    check("capture 200", r.status_code == 200, str(r.status_code))
    ev = wait_event("IN")
    check("có lượt trong CSDL", ev is not None)
    check("đọc đúng biển", ev and ev["plate"] == PLATE, ev and ev["plate"])
    check("quyết định OPEN", ev and ev["decision"] == "OPEN", ev and f"{ev['status']}/{ev['decision']}")
    p = DATA / "media" / "events" / str(ev["event_id"]) / "full.jpg"
    check("ảnh bằng chứng JPEG thật", p.exists(), str(p))
    check("có ảnh biển đã cắt", (p.parent / "plate.jpg").exists())
    check("thanh chắn ĐANG MỞ (chưa có C2)", barrier.get("IN").is_open)
    check("event C2 200", c.post("/esp32/event", data={"gate": "IN", "type": "C2_PASSED"}).status_code == 200)
    check("C2 báo -> thanh chắn đã HẠ", wait_closed("IN"))
    s = db.one("SELECT * FROM lot_sessions WHERE plate_norm=? ORDER BY id DESC LIMIT 1",
               (logic.norm(PLATE),))
    check("đã mở phiên trong bãi", s is not None and s["status"] == "IN", s and s["status"])
    check("đã dọn thư mục chờ", wait_spool_empty("IN"), str(spool_jpgs("IN")))

    print("\n[4] vào lần hai cùng biển -> DUPLICATE_IN / HOLD")
    _, ev = run_pass(c, "IN")
    check("DUPLICATE_IN / HOLD", ev and ev["status"] == "DUPLICATE_IN" and ev["decision"] == "HOLD",
          ev and f"{ev['status']}/{ev['decision']}")
    check("thanh chắn vẫn HẠ", not barrier.get("IN").is_open)

    print("\n[5] kịch bản 2 - xe ra bình thường")
    _, ev = run_pass(c, "RA")
    check("OUT quyết định OPEN", ev and ev["decision"] == "OPEN", ev and f"{ev['status']}/{ev['decision']}")
    s = db.one("SELECT * FROM lot_sessions WHERE id=?", (s["id"],))
    check("phiên đã đóng, tính được giờ ra", s["status"] == "OUT" and s["time_out"], s["status"])

    print("\n[6] kịch bản 4 - biển bị che, không đọc được")
    _mode["readable"] = False
    _, ev = run_pass(c, "IN")
    check("UNREADABLE / HOLD", ev and ev["status"] == "UNREADABLE" and ev["decision"] == "HOLD",
          ev and f"{ev['status']}/{ev['decision']}")
    check("thanh chắn không mở", not barrier.get("IN").is_open)
    _mode["readable"] = True

    print("\n[7] kịch bản 6 - người trực mở thủ công")
    hold_id = ev["event_id"]
    u = db.one("SELECT * FROM users LIMIT 1")
    logic.override("IN", hold_id, "PASS", "51-F1 234.56", None, u)
    time.sleep(0.4)
    check("chắn mở sau khi cho qua", barrier.get("IN").is_open)
    c.post("/esp32/event", data={"gate": "IN", "type": "C2_PASSED"})
    check("hạ chắn sau C2", wait_closed("IN"))

    print("\n[8] kịch bản 5 - xe ra không khớp phiên nào")
    _mode["plate"] = "72-C1 111.22"
    _, ev = run_pass(c, "OUT")
    check("MISMATCH / HOLD", ev and ev["status"] == "MISMATCH" and ev["decision"] == "HOLD",
          ev and f"{ev['status']}/{ev['decision']}")
    check("chắn làn RA không mở", not barrier.get("OUT").is_open)
    _mode["plate"] = PLATE

    print("\n[9] ⚠️2 - nhiều khung: hai khung đồng thuận cứu được lượt mà một khung không đạt")
    _, ev = run_pass(c, "OUT", 2)                 # MỘT khung, trượt chốt agree
    check("một khung trượt agree -> HOLD", ev and ev["decision"] == "HOLD",
          ev and f"{ev['status']}/{ev['decision']}")
    r, ev = run_pass(c, "IN", 2, 2, 1)            # BA khung: hai khung đọc ra cùng PLATE
    check("gửi 3 khung, server nhận đủ", r.json().get("frames") == 3, str(r.json()))
    if econf.MULTIFRAME:
        check("hai khung đồng thuận -> được nhận", ev and ev["plate"] == PLATE, ev and ev["plate"])
        check("và mở chắn", ev and ev["decision"] == "OPEN",
              ev and f"{ev['status']}/{ev['decision']}")
    else:
        check("tắt nhiều khung -> vẫn giữ chắn (đúng hành vi cũ)",
              ev and ev["decision"] == "HOLD", ev and f"{ev['status']}/{ev['decision']}")

    print("\n[10] ⚠️2 - nhiều khung đọc ra kết quả KHÁC nhau thì vẫn giữ chắn")
    _, ev = run_pass(c, "OUT", 2, 3, 1)           # PLATE vs ALT, không khung nào thắng
    check("không khung nào đạt -> HOLD", ev and ev["decision"] == "HOLD",
          ev and f"{ev['status']}/{ev['decision']}")
    check("chắn làn RA không mở", not barrier.get("OUT").is_open)

    print("\n[11] ⚠️1 - mã xác nhận chỉ trả sau khi ảnh đã nằm trên đĩa")
    prev = last_id("OUT")
    r = capture(c, "OUT", 4)                      # khung này nhận dạng mất 1,2 giây
    check("capture 200", r.status_code == 200, str(r.status_code))
    check("ảnh đã có trên đĩa ngay khi trả 200", len(spool_jpgs("OUT")) >= 1,
          f"{len(spool_jpgs('OUT'))} tệp")
    ev = wait_event("OUT", prev)
    c.post("/esp32/event", data={"gate": "OUT", "type": "C2_PASSED"})
    wait_closed("OUT")
    check("hết lượt thì dọn thư mục chờ", wait_spool_empty("OUT"), str(spool_jpgs("OUT")))

    print("\n[12] ⚠️1 - ảnh còn sót sau mất điện được xử lý tiếp")
    d = econf.spool_dir() / "IN"
    d.mkdir(parents=True, exist_ok=True)
    (d / "20260101-000000-deadbeef_0.jpg").write_bytes(mk(5, idx=29))
    (d / ".20260101-000000-deadbeef_1.tmp").write_bytes(b"ghi do dang")
    prev = last_id("IN")
    before = pipeline.stats["lay_lai_sau_mat_dien"]
    pipeline._recover_spool()
    check("đếm được lượt lấy lại", pipeline.stats["lay_lai_sau_mat_dien"] == before + 1)
    check("tệp ghi dở đã bị bỏ", not list(d.glob(".*.tmp")))
    ev = wait_plate("IN", "59-P1 629.80")
    check("lượt sót được xử lý", ev is not None, ev and ev["plate"])
    if ev is not None and ev["decision"] == "OPEN":
        c.post("/esp32/event", data={"gate": "IN", "type": "C2_PASSED"})
        wait_closed("IN")

    print("\n[13] kịch bản 7 - hai làn chạy cùng lúc")
    pin, pout = last_id("IN"), last_id("OUT")
    r1 = capture(c, "IN", 5, idx=20)
    r2 = capture(c, "OUT", 5, idx=21)
    check("cả hai làn nhận 200", r1.status_code == 200 and r2.status_code == 200)
    e1, e2 = wait_event("IN", pin), wait_event("OUT", pout)
    check("làn VÀO có lượt riêng", e1 is not None and e1["gate"] == "IN")
    check("làn RA có lượt riêng", e2 is not None and e2["gate"] == "OUT")
    check("không lẫn biển giữa hai làn", e1 is not None and e2 is not None
          and e1["plate"] != e2["plate"], f"{e1 and e1['plate']} / {e2 and e2['plate']}")
    for g in ("IN", "OUT"):
        c.post("/esp32/event", data={"gate": g, "type": "C2_PASSED"})
        wait_closed(g)

    print("\n[14] kịch bản 10 - 30 lượt liên tục, xen kẽ vào - ra")
    n_ok, t0 = 0, time.perf_counter()
    for i in range(15):
        good = True
        for g in ("IN", "OUT"):
            _, e = run_pass(c, g, 5, idx=i)
            if e is None or e["decision"] != "OPEN":
                good = False
        n_ok += 1 if good else 0
    dt = time.perf_counter() - t0
    check("15 cặp vào-ra đều mở chắn đúng", n_ok == 15, f"{n_ok}/15 trong {dt:.1f}s")
    done = db.one("SELECT COUNT(*) n FROM lot_sessions WHERE status='OUT'")["n"]
    check("mọi lượt ra khớp đúng lượt vào", done >= 15, f"{done} phiên đã đóng")

    print("\n[15] kịch bản 9 - mất điện khối trung tâm")
    open_before = db.one("SELECT COUNT(*) n FROM lot_sessions WHERE status='IN'")["n"]
    barrier.panic_open()
    from server.edge import gpio
    pulses = {g: gpio.backend().state.get(econf.PIN[g]) for g in ("IN", "OUT")}
    if econf.BARRIER_MODE == "fail_open":
        check("nhả xung -> lò xo nâng cả hai chắn", all(v == 0 for v in pulses.values()), str(pulses))
    else:
        check("cố nâng cả hai chắn trước khi tắt",
              all(v == econf.PULSE_OPEN for v in pulses.values()), str(pulses))
    after = db.one("SELECT COUNT(*) n FROM lot_sessions WHERE status='IN'")["n"]
    check("phiên đang mở vẫn còn trong CSDL", after == open_before, f"{after}/{open_before}")

    print("\n[16] heartbeat, command, mã thiết bị")
    r = c.post("/esp32/heartbeat", data={"device_id": "cam-a", "gate": "IN",
                                         "state": "IDLE", "rssi": "-57"})
    check("heartbeat 200", r.status_code == 200, str(r.status_code))
    check("thiết bị online", db.one("SELECT * FROM devices WHERE device_id='cam-a'")["online"] == 1)
    r = c.get("/esp32/command", params={"device_id": "cam-a"})
    check("command trả trạng thái chắn", r.status_code == 200 and "barrier_open" in r.json())
    os.environ["GV_NODE_TOKEN"] = "bimat"
    check("thiếu mã -> 401", capture(c, "IN").status_code == 401)
    r = c.post("/esp32/capture", files=[("image", ("f.jpg", mk(0), "image/jpeg"))],
               data={"gate": "IN"}, headers={"X-Node-Token": "bimat"})
    check("đúng mã -> 200", r.status_code == 200, str(r.status_code))
    del os.environ["GV_NODE_TOKEN"]
    time.sleep(0.6)
    c.post("/esp32/event", data={"gate": "IN", "type": "C2_PASSED"})
    wait_closed("IN")

    print("\n[17] tệp số đo")
    t = pathlib.Path(os.environ["GV_TIMING_CSV"])
    check("đã ghi CSV", t.exists())
    if t.exists():
        lines = t.read_text(encoding="utf-8").strip().splitlines()
        check("có đủ dòng", len(lines) >= 20, f"{len(lines)} dòng")
        check("có cột số khung đã đọc", "so_khung_doc" in lines[0])
        check("có cột quyết định bởi", "quyet_dinh_boi" in lines[0])
        print("       " + lines[0])
        print("       " + lines[1])
        multi = [l for l in lines if "đồng thuận" in l]
        if econf.MULTIFRAME:
            check("ghi lại được lượt quyết định bằng nhiều khung", len(multi) >= 1,
                  multi[0] if multi else "")

    print("\n[18] ⚠️3 - box đầu trượt thì còn thử box kế tiếp")
    # Thay bộ phát hiện bằng hai box dựng tay: box TO có conf THẤP, box NHỎ có conf CAO.
    # OCR giả chỉ đọc được box nhỏ. Dù xếp theo diện tích hay theo conf, lượt này phải đọc ra.
    class _A:
        def __init__(self, a): self._a = a
        def cpu(self): return self
        def numpy(self): return self._a

    class _Boxes:
        def __init__(self, xyxy, cf): self.xyxy, self.conf = _A(xyxy), _A(cf)
        def __len__(self): return len(self.xyxy.numpy())

    class _Det:
        def __init__(self, xyxy, cf):
            self._r = type("R", (), {"boxes": _Boxes(np.array(xyxy, np.float32),
                                                     np.array(cf, np.float32))})()
        def predict(self, *a, **k): return [self._r]

    def _ocr_stub(crop, votes=3):
        # box nhỏ (rộng ~100 px) mới đọc được; box to (~300 px) thì sai khuôn
        if crop.shape[1] < 160:
            return {"text": PLATE, "conf": 0.90, "valid": True, "agree": 1.0}
        return {"text": "XX", "conf": 0.40, "valid": False, "agree": 1.0}

    frame = cv2.imdecode(np.frombuffer(mk(0), np.uint8), cv2.IMREAD_COLOR)
    for pick in ("area", "conf"):
        econf.DET_PICK = pick
        rec = rec_mod.Recognizer()
        rec._det = _Det([[10, 10, 310, 120], [350, 40, 450, 100]], [0.70, 0.95])
        rec._ocr = _ocr_stub
        out = REAL_READ(rec, frame)
        want = 2 if pick == "area" else 1      # xếp theo conf thì box đọc được đứng đầu luôn
        check(f"DET_PICK={pick}: vẫn đọc ra biển", out.readable and out.plate == PLATE,
              f"box đã thử={out.boxes_tried}, {out.reason}")
        check(f"DET_PICK={pick}: thử đúng {want} box", out.boxes_tried == want, str(out.boxes_tried))
    econf.DET_PICK = "area"

print("\n" + ("TẤT CẢ ĐẠT" if not fails else f"{len(fails)} MỤC KHÔNG ĐẠT: {fails}"))
sys.exit(1 if fails else 0)
