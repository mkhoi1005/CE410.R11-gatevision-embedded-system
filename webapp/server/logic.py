"""Nghiệp vụ cổng: xử lý một lượt chụp, giữ/hết hạn, người trực xử lý (override).
Nguyên tắc fail-safe: mọi trường hợp không chắc chắn đều là HOLD (cổng đóng); HOLD hết hạn thì thành EXPIRED, cổng KHÔNG tự mở."""
import asyncio
import re
from datetime import timedelta

from . import config, db
from .hub import hub


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


CONFUSABLE = {"0": "O", "O": "0", "1": "I", "I": "1", "8": "B", "B": "8", "5": "S", "S": "5"}


def norm(p) -> str:
    return re.sub(r"[\s.\-]", "", str(p or "").upper())


def valid_plate(p) -> bool:
    return bool(re.fullmatch(r"[0-9A-Z]{6,10}", norm(p)))


# ---------- chuyển hàng DB thành JSON theo hợp đồng ----------
def event_out(r) -> dict:
    import json
    return {
        "event_id": r["event_id"], "time": r["time"], "gate": r["gate"], "device_id": r["device_id"],
        "plate": r["plate"], "confidence": r["confidence"], "decision": r["decision"], "status": r["status"],
        "image_url": r["image_url"], "plate_image_url": r["plate_image_url"], "session_id": r["session_id"],
        "fuzzy_candidates": json.loads(r["fuzzy"]), "resolution": json.loads(r["resolution"]) if r["resolution"] else None,
        "hold_expires_at": r["hold_expires_at"],
    }


def session_out(r) -> dict:
    return {k: r[k] for k in ("id", "plate", "time_in", "image_in_url", "confidence_in", "time_out", "image_out_url", "confidence_out", "status")} | {"flagged": bool(r["flagged"])}


def alert_out(r) -> dict:
    return {k: r[k] for k in ("id", "type", "event_id", "device_id", "time", "status", "message")}


def device_out(r) -> dict:
    import time
    up = int(time.time() - r["boot_at"]) if r["online"] else 0
    return {"device_id": r["device_id"], "gate": r["gate"], "ip": r["ip"], "rssi": r["rssi"], "uptime": up, "state": r["state"],
            "last_seen": r["last_seen"], "online": bool(r["online"]), "stream_url": r["stream_url"]}


def get_event(eid):
    r = db.one("SELECT * FROM events WHERE event_id=?", (eid,))
    return event_out(r) if r else None


# ---------- thiết bị và cảnh báo ----------
def set_state(device_id: str, state: str, reset_after: float = None):
    with db.conn:
        db.conn.execute("UPDATE devices SET state=? WHERE device_id=?", (state, device_id))
    hub.emit({"type": "device_status", "data": device_out(db.one("SELECT * FROM devices WHERE device_id=?", (device_id,)))})
    if reset_after:
        def back():
            r = db.one("SELECT state, online FROM devices WHERE device_id=?", (device_id,))
            if r and r["state"] == state and r["online"]:
                set_state(device_id, "IDLE")
        try:
            asyncio.get_running_loop().call_later(reset_after, back)
        except RuntimeError:
            pass


def create_alert(type_: str, message: str, event_id=None, device_id=None) -> dict:
    with db.conn:
        cur = db.conn.execute("INSERT INTO alerts(type,event_id,device_id,time,status,message) VALUES (?,?,?,?, 'OPEN',?)",
                              (type_, event_id, device_id, db.iso(db.now_utc()), message))
    a = alert_out(db.one("SELECT * FROM alerts WHERE id=?", (cur.lastrowid,)))
    hub.emit({"type": "alert", "data": a})
    return a


def resolve_alerts(where: str, args: tuple):
    rows = db.all_(f"SELECT id FROM alerts WHERE status='OPEN' AND {where}", args)
    for r in rows:
        with db.conn:
            db.conn.execute("UPDATE alerts SET status='RESOLVED' WHERE id=?", (r["id"],))
        hub.emit({"type": "alert", "data": alert_out(db.one("SELECT * FROM alerts WHERE id=?", (r["id"],)))})


# ---------- phiên trong bãi ----------
def in_lot(plate):
    return db.one("SELECT * FROM lot_sessions WHERE status='IN' AND plate_norm=?", (norm(plate),))


def fuzzy_match(read: str):
    r = norm(read)
    out = []
    for s in db.all_("SELECT * FROM lot_sessions WHERE status='IN'"):
        p = s["plate_norm"]
        if len(p) != len(r) or p == r:
            continue
        diff, ok = 0, True
        for a, b in zip(p, r):
            if a != b:
                diff += 1
                if CONFUSABLE.get(a) != b:
                    ok = False
        if diff == 1 and ok:
            out.append(s)
    return out


def _open_session(plate, time_, image, conf, flagged=False) -> int:
    cur = db.conn.execute("INSERT INTO lot_sessions(plate,plate_norm,time_in,image_in_url,confidence_in,status,flagged) VALUES (?,?,?,?,?,'IN',?)",
                          (plate, norm(plate), time_, image, conf, int(flagged)))
    return cur.lastrowid


def _close_session(sid, time_, image, conf):
    db.conn.execute("UPDATE lot_sessions SET status='OUT', time_out=?, image_out_url=?, confidence_out=? WHERE id=?", (time_, image, conf, sid))


# ---------- một lượt chụp ----------
def process_capture(gate: str, plate, conf, *, make_images, when=None, silent=False, hold_s=None) -> dict:
    """Quyết định cho một lượt chụp. Sau này endpoint nhận ảnh từ ESP32 (v2 mục 6.1) gọi hàm này với plate/conf do module AI đọc."""
    when = when or db.now_utc()
    t = db.iso(when)
    dev = db.one("SELECT * FROM devices WHERE gate=?", (gate,))
    readable = bool(plate) and conf is not None and conf >= config.MIN_CONF
    read = plate if readable else None
    status, decision, msg, sid, fuzzy = "OK", "OPEN", "", None, []
    with db.conn:
        eid = db.conn.execute("INSERT INTO events(time,gate,device_id,decision,status) VALUES (?,?,?,'OPEN','OK')", (t, gate, dev["device_id"])).lastrowid
        img, pimg = make_images(eid, read)
        c = round(conf, 2) if readable else None
        if not readable:
            status, decision, msg = "UNREADABLE", "HOLD", "Không đọc được biển số"
        elif gate == "IN":
            if in_lot(read):
                status, decision, msg = "DUPLICATE_IN", "HOLD", "Biển này đã có trong bãi"
            else:
                sid = _open_session(read, t, img, c)
        else:
            m = in_lot(read)
            if m:
                _close_session(m["id"], t, img, c)
                sid = m["id"]
            else:
                f = fuzzy_match(read)
                if f:
                    status, decision, msg = "FUZZY", "HOLD", "Biển gần giống xe trong bãi, cần xác nhận"
                    fuzzy = [{"session_id": s["id"], "plate": s["plate"]} for s in f]
                else:
                    status, decision, msg = "MISMATCH", "HOLD", "Biển ra không khớp phiên nào đang mở"
        hold_exp = db.iso(db.now_utc() + timedelta(seconds=hold_s or config.hold_max_s())) if decision == "HOLD" else None
        db.conn.execute("UPDATE events SET plate=?, plate_norm=?, confidence=?, decision=?, status=?, image_url=?, plate_image_url=?, session_id=?, fuzzy=?, hold_expires_at=? WHERE event_id=?",
                        (read, norm(read) if read else None, c, decision, status, img, pimg, sid, db.dumps(fuzzy), hold_exp, eid))
    ev = get_event(eid)
    if not silent:
        hub.emit({"type": "event_created", "data": ev})
        if decision == "HOLD":
            create_alert(status, msg, event_id=eid, device_id=dev["device_id"])
            set_state(dev["device_id"], "HOLD")
        else:
            set_state(dev["device_id"], "GATE_OPEN", 4)
    return ev


# ---------- hết hạn giữ ----------
def expire_event(eid: int):
    r = db.one("SELECT * FROM events WHERE event_id=?", (eid,))
    if not r or r["resolution"] or r["decision"] != "HOLD":
        return
    res = {"action": "EXPIRED", "operator_id": None, "operator_name": None, "time": db.iso(db.now_utc()), "manual_plate": None}
    with db.conn:
        db.conn.execute("UPDATE events SET resolution=?, hold_expires_at=NULL WHERE event_id=?", (db.dumps(res), eid))
    resolve_alerts("event_id=?", (eid,))
    hub.emit({"type": "event_updated", "data": get_event(eid)})
    set_state(r["device_id"], "IDLE")


def expire_due():
    now = db.iso(db.now_utc())
    for r in db.all_("SELECT event_id FROM events WHERE decision='HOLD' AND resolution IS NULL AND hold_expires_at IS NOT NULL AND hold_expires_at<=?", (now,)):
        expire_event(r["event_id"])


# ---------- người trực xử lý ----------
def override(gate: str, event_id: int, action: str, manual_plate, session_id, user) -> dict:
    r = db.one("SELECT * FROM events WHERE event_id=? AND gate=?", (event_id, gate))
    if not r:
        raise ApiError(404, "EVENT_NOT_FOUND", "Không tìm thấy lượt xe này ở cổng này.")
    if r["decision"] != "HOLD":
        raise ApiError(409, "ALREADY_RESOLVED", "Lượt này không ở trạng thái giữ.")
    if not r["resolution"] and r["hold_expires_at"] and r["hold_expires_at"] <= db.iso(db.now_utc()):
        expire_event(event_id)
        r = db.one("SELECT * FROM events WHERE event_id=?", (event_id,))
    if r["resolution"]:
        import json
        expired = json.loads(r["resolution"])["action"] == "EXPIRED"
        raise ApiError(409, "EXPIRED" if expired else "ALREADY_RESOLVED", "Lượt giữ đã hết hạn." if expired else "Lượt này đã được xử lý.")
    if action not in ("PASS", "DENY"):
        raise ApiError(422, "INVALID", "Hành động không hợp lệ.")
    mp = (manual_plate or "").strip().upper() or None
    plate_set = None
    with db.conn:
        if action == "PASS":
            if gate == "IN" and r["status"] == "UNREADABLE":
                if mp and not valid_plate(mp):
                    raise ApiError(422, "INVALID_PLATE", "Biển số nhập tay chưa đúng định dạng.")
                if mp and in_lot(mp):
                    raise ApiError(409, "DUPLICATE_IN", "Biển này đã có trong bãi.")
                plate = mp or f"UNKNOWN-{event_id}"
                sid = _open_session(plate, r["time"], r["image_url"], r["confidence"], flagged=not mp)
                db.conn.execute("UPDATE events SET session_id=? WHERE event_id=?", (sid, event_id))
                if mp:
                    plate_set = plate
            if gate == "OUT":
                import json
                cands = json.loads(r["fuzzy"])
                if r["status"] == "FUZZY" and not session_id:
                    raise ApiError(422, "CHOOSE_SESSION", "Hãy chọn xe trong bãi tương ứng.")
                if session_id:
                    s = db.one("SELECT * FROM lot_sessions WHERE id=? AND status='IN'", (session_id,))
                    if not s:
                        raise ApiError(422, "INVALID_SESSION", "Phiên không còn trong bãi.")
                    if r["status"] == "FUZZY" and not any(c["session_id"] == s["id"] for c in cands):
                        raise ApiError(422, "INVALID_SESSION", "Phiên không nằm trong các xe gần giống.")
                    _close_session(s["id"], r["time"], r["image_url"], r["confidence"])
                    db.conn.execute("UPDATE events SET session_id=? WHERE event_id=?", (s["id"], event_id))
        res = {"action": action, "operator_id": user["id"], "operator_name": user["display_name"], "time": db.iso(db.now_utc()), "manual_plate": mp}
        db.conn.execute("UPDATE events SET resolution=?, hold_expires_at=NULL WHERE event_id=?", (db.dumps(res), event_id))
        if plate_set:
            db.conn.execute("UPDATE events SET plate=?, plate_norm=? WHERE event_id=?", (plate_set, norm(plate_set), event_id))
    resolve_alerts("event_id=?", (event_id,))
    ev = get_event(event_id)
    hub.emit({"type": "event_updated", "data": ev})
    if action == "PASS":
        set_state(r["device_id"], "GATE_OPEN", 4)
    else:
        set_state(r["device_id"], "IDLE")
    return ev
