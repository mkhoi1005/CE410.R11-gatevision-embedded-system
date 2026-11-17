"""Server GATE VISION (phần phục vụ web). Chạy: uvicorn server.main:app --host 0.0.0.0 --port 8000
Hợp đồng: web/API_CONTRACT_WEB.md. Phần ESP32 (v2 mục 6.1) CHƯA làm."""
import asyncio
import random
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db, logic, media, security
from .hub import hub
from .logic import ApiError, alert_out, device_out, event_out, norm, session_out

FAILS: dict = {}  # ip -> [thời điểm sai mật khẩu]


# ---------- khởi động ----------
def user_out(r) -> dict:
    return {"id": r["id"], "username": r["username"], "display_name": r["display_name"], "role": r["role"], "must_change_password": bool(r["must_change_password"])}


def add_user(username, display, role, pw, must_change=True):
    with db.conn:
        db.conn.execute("INSERT INTO users(username,display_name,role,must_change_password,pw_hash) VALUES (?,?,?,?,?)",
                        (username, display, role, int(must_change), security.hash_password(pw)))


def seed_first_run():
    if db.one("SELECT 1 FROM users LIMIT 1"):
        return
    now = db.iso(db.now_utc())
    for did, gate, ip, rssi in (("cam-a", "IN", "192.168.4.11", -58), ("cam-b", "OUT", "192.168.4.12", -66)):
        with db.conn:
            db.conn.execute("INSERT INTO devices(device_id,gate,ip,rssi,state,online,last_seen,boot_at,stream_url) VALUES (?,?,?,?,?,?,?,?,NULL)",
                            (did, gate, ip, rssi, "IDLE" if config.dev() else "OFFLINE", int(config.dev()), now, time.time() - 86400))
    if config.dev():
        add_user("admin", "Quản trị", "admin", "admin123")
        add_user("truc1", "Nhân viên trực 1", "staff", "truc1234", must_change=False)
        seed_demo()
    else:
        pw = secrets.token_urlsafe(9)
        add_user("admin", "Quản trị", "admin", pw)
        print("=" * 60 + f"\nLẦN CHẠY ĐẦU. Tài khoản quản trị: admin / {pw}\nMật khẩu này chỉ hiện một lần; đăng nhập sẽ bị buộc đổi.\n" + "=" * 60)


def seed_demo():
    """Dữ liệu mẫu như bản server giả trong trình duyệt (chỉ khi GV_DEV=1)."""
    plates = ["59X1-12345", "59C2-67890", "51F1-24680", "59B1-10805", "50Z1-11223", "59H1-45678"]
    t0 = db.now_utc()
    for i, p in enumerate(plates):
        logic.process_capture("IN", p, random.uniform(0.8, 0.96), make_images=media.fake_images, when=t0 - timedelta(minutes=180 - i * 25), silent=True)
    m = logic.process_capture("OUT", "59Q9-00000", 0.88, make_images=media.fake_images, when=t0 - timedelta(minutes=40), silent=True)
    res = {"action": "DENY", "operator_id": 2, "operator_name": "Nhân viên trực 1", "time": db.iso(t0 - timedelta(minutes=39)), "manual_plate": None}
    with db.conn:
        db.conn.execute("UPDATE events SET resolution=?, hold_expires_at=NULL WHERE event_id=?", (db.dumps(res), m["event_id"]))
        db.conn.execute("INSERT INTO alerts(type,event_id,device_id,time,status,message) VALUES ('MISMATCH',?,NULL,?,'RESOLVED','Biển ra không khớp phiên nào đang mở')", (m["event_id"], m["time"]))
    logic.process_capture("OUT", plates[5], 0.91, make_images=media.fake_images, when=t0 - timedelta(minutes=12), silent=True)


async def expiry_loop():
    while True:
        try:
            logic.expire_due()
            for d in db.all_("SELECT * FROM devices WHERE online=1"):
                if d["last_seen"] < db.iso(db.now_utc() - timedelta(seconds=config.OFFLINE_AFTER_S)):
                    with db.conn:
                        db.conn.execute("UPDATE devices SET online=0, state='OFFLINE' WHERE device_id=?", (d["device_id"],))
                    hub.emit({"type": "device_status", "data": device_out(db.one("SELECT * FROM devices WHERE device_id=?", (d["device_id"],)))})
                    logic.create_alert("DEVICE_OFFLINE", f"Thiết bị {d['device_id']} mất kết nối", device_id=d["device_id"])
        except Exception as e:  # không để vòng lặp chết
            print("expiry_loop lỗi:", e)
        await asyncio.sleep(1)


async def dev_heartbeat_loop():
    """Chỉ ở chế độ thử: giả lập heartbeat của camera đang 'online'."""
    while True:
        await asyncio.sleep(10)
        for d in db.all_("SELECT * FROM devices WHERE online=1"):
            rssi = max(-80, min(-45, (d["rssi"] or -60) + random.randint(-2, 2)))
            with db.conn:
                db.conn.execute("UPDATE devices SET rssi=?, last_seen=? WHERE device_id=?", (rssi, db.iso(db.now_utc()), d["device_id"]))
            hub.emit({"type": "device_status", "data": device_out(db.one("SELECT * FROM devices WHERE device_id=?", (d["device_id"],)))})


@asynccontextmanager
async def lifespan(app):
    config.data_dir().mkdir(parents=True, exist_ok=True)
    db.init(config.data_dir() / "gatevision.db")
    media.write_idle()
    hub.blocked = False
    hub.start()
    seed_first_run()
    logic.expire_due()  # fail-safe: lượt HOLD đã quá hạn trong lúc server tắt thì đánh dấu hết hạn, không mở
    tasks = [asyncio.create_task(expiry_loop())]
    if config.dev():
        tasks.append(asyncio.create_task(dev_heartbeat_loop()))
    yield
    for t in tasks:
        t.cancel()
    await hub.stop()


app = FastAPI(title="GATE VISION", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ---------- lỗi theo hợp đồng ----------
def err(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(_, e: ApiError):
    return err(e.status, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def _invalid(_, e):
    return err(422, "INVALID", "Dữ liệu gửi lên không hợp lệ.")


@app.exception_handler(StarletteHTTPException)
async def _http(_, e: StarletteHTTPException):
    return err(e.status_code, "NOT_FOUND" if e.status_code == 404 else "ERROR", "Không có đường dẫn này." if e.status_code == 404 else "Có lỗi xảy ra.")


@app.middleware("http")
async def _headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- xác thực ----------
def _user_from_token(token: Optional[str]):
    if not token:
        return None
    r = db.one("SELECT u.*, a.expires_at FROM auth_sessions a JOIN users u ON u.id=a.user_id WHERE a.token_hash=?", (security.token_hash(token),))
    if not r:
        return None
    if r["expires_at"] <= db.iso(db.now_utc()):
        with db.conn:
            db.conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (security.token_hash(token),))
        return None
    return r


async def user_any(request: Request):
    u = _user_from_token(request.cookies.get(config.COOKIE_NAME))
    if not u:
        raise ApiError(401, "UNAUTHORIZED", "Bạn cần đăng nhập.")
    return u


async def user_ok(u=Depends(user_any)):
    if u["must_change_password"]:
        raise ApiError(403, "PASSWORD_CHANGE_REQUIRED", "Hãy đổi mật khẩu trước khi tiếp tục.")
    return u


async def admin_ok(u=Depends(user_ok)):
    if u["role"] != "admin":
        raise ApiError(403, "FORBIDDEN", "Chỉ quản trị mới dùng được chức năng này.")
    return u


api = APIRouter(prefix="/api/v1")


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    display_name: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str
    display_name: str = ""
    role: str = "staff"
    password: str


class UserPatch(BaseModel):
    role: Optional[str] = None


class OverrideIn(BaseModel):
    event_id: int
    action: str
    manual_plate: Optional[str] = None
    session_id: Optional[int] = None


@api.get("/healthz")
async def healthz():
    return {"status": "ok"}


@api.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in FAILS.get(ip, []) if now - t < config.LOGIN_WINDOW_S]
    FAILS[ip] = recent
    if len(recent) >= config.LOGIN_MAX_FAILS:
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "Thử quá nhiều lần. Hãy đợi một lát rồi thử lại.")
    u = db.one("SELECT * FROM users WHERE username=?", (body.username,))
    ok = security.verify_password(body.password, u["pw_hash"] if u else security.DUMMY)
    if not (u and ok):
        recent.append(now)
        raise ApiError(401, "BAD_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu.")
    FAILS.pop(ip, None)
    token = security.new_token()
    with db.conn:
        db.conn.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (db.iso(db.now_utc()),))
        db.conn.execute("INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES (?,?,?)",
                        (security.token_hash(token), u["id"], db.iso(db.now_utc() + timedelta(seconds=config.SESSION_TTL_S))))
    response.set_cookie(config.COOKIE_NAME, token, max_age=config.SESSION_TTL_S, httponly=True, samesite="lax", path="/")
    return user_out(u)


@api.post("/auth/logout")
async def logout(request: Request, response: Response):
    t = request.cookies.get(config.COOKIE_NAME)
    if t:
        with db.conn:
            db.conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (security.token_hash(t),))
    response.delete_cookie(config.COOKIE_NAME, path="/")
    return {}


@api.get("/users/me")
async def me(u=Depends(user_any)):
    return user_out(u)


@api.patch("/users/me")
async def patch_me(body: ProfileIn, u=Depends(user_ok)):
    n = body.display_name.strip()
    if not n or len(n) > 60:
        raise ApiError(422, "INVALID", "Tên hiển thị không được để trống (tối đa 60 ký tự).")
    with db.conn:
        db.conn.execute("UPDATE users SET display_name=? WHERE id=?", (n, u["id"]))
    return user_out(db.one("SELECT * FROM users WHERE id=?", (u["id"],)))


@api.post("/users/me/password")
async def change_password(body: PasswordIn, request: Request, u=Depends(user_any)):
    if not security.verify_password(body.old_password, u["pw_hash"]):
        raise ApiError(422, "BAD_OLD_PASSWORD", "Mật khẩu hiện tại không đúng.")
    if len(body.new_password) < 8:
        raise ApiError(422, "WEAK_PASSWORD", "Mật khẩu mới cần ít nhất 8 ký tự.")
    cur = security.token_hash(request.cookies.get(config.COOKIE_NAME, ""))
    with db.conn:
        db.conn.execute("UPDATE users SET pw_hash=?, must_change_password=0 WHERE id=?", (security.hash_password(body.new_password), u["id"]))
        db.conn.execute("DELETE FROM auth_sessions WHERE user_id=? AND token_hash<>?", (u["id"], cur))  # đăng xuất các nơi khác
    return user_out(db.one("SELECT * FROM users WHERE id=?", (u["id"],)))


@api.get("/users")
async def list_users(_=Depends(admin_ok)):
    return {"items": [user_out(r) for r in db.all_("SELECT * FROM users ORDER BY id")], "next_cursor": None}


@api.post("/users")
async def create_user(body: UserCreate, _=Depends(admin_ok)):
    import re
    un = body.username.strip()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", un):
        raise ApiError(422, "INVALID", "Tên đăng nhập gồm 3–20 ký tự thường, số hoặc dấu gạch dưới.")
    if db.one("SELECT 1 FROM users WHERE username=?", (un,)):
        raise ApiError(409, "EXISTS", "Tên đăng nhập đã tồn tại.")
    if len(body.password) < 8:
        raise ApiError(422, "WEAK_PASSWORD", "Mật khẩu cần ít nhất 8 ký tự.")
    add_user(un, body.display_name.strip()[:60] or un, "admin" if body.role == "admin" else "staff", body.password)
    return user_out(db.one("SELECT * FROM users WHERE username=?", (un,)))


@api.patch("/users/{uid}")
async def patch_user(uid: int, body: UserPatch, me_=Depends(admin_ok)):
    u = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(404, "NOT_FOUND", "Không có người dùng này.")
    if body.role and uid == me_["id"]:
        raise ApiError(409, "SELF_ROLE", "Không đổi được vai trò của chính mình.")
    if body.role:
        with db.conn:
            db.conn.execute("UPDATE users SET role=? WHERE id=?", ("admin" if body.role == "admin" else "staff", uid))
    return user_out(db.one("SELECT * FROM users WHERE id=?", (uid,)))


def _page(rows, key, limit, conv):
    items = rows[:limit]
    return {"items": [conv(r) for r in items], "next_cursor": str(items[-1][key]) if len(rows) > limit and items else None}


@api.get("/events/{eid}")
async def get_event(eid: int, _=Depends(user_ok)):
    ev = logic.get_event(eid)
    if not ev:
        raise ApiError(404, "EVENT_NOT_FOUND", "Không có sự kiện này.")
    return ev


@api.get("/sessions")
async def list_sessions(status: str = "", plate: str = "", cursor: str = "", limit: int = 500, _=Depends(user_ok)):
    w, a = [], []
    if status in ("IN", "OUT"):
        w.append("status=?"); a.append(status)
    if plate:
        w.append("plate_norm LIKE ?"); a.append(f"%{norm(plate)}%")
    if cursor.isdigit():
        w.append("id<?"); a.append(int(cursor))
    limit = max(1, min(limit, 1000))
    rows = db.all_(f"SELECT * FROM lot_sessions {'WHERE ' + ' AND '.join(w) if w else ''} ORDER BY id DESC LIMIT ?", (*a, limit + 1))
    return _page(rows, "id", limit, session_out)


@api.get("/alerts")
async def list_alerts(status: str = "", limit: int = 200, _=Depends(user_ok)):
    rows = db.all_(f"SELECT * FROM alerts {'WHERE status=?' if status in ('OPEN', 'RESOLVED') else ''} ORDER BY id DESC LIMIT ?",
                   ((status,) if status in ("OPEN", "RESOLVED") else ()) + (max(1, min(limit, 500)),))
    return {"items": [alert_out(r) for r in rows], "next_cursor": None}


@api.get("/devices")
async def list_devices(_=Depends(user_ok)):
    return {"items": [device_out(r) for r in db.all_("SELECT * FROM devices ORDER BY CASE gate WHEN 'IN' THEN 0 ELSE 1 END, device_id")], "next_cursor": None}


@api.get("/stats")
async def stats(_=Depends(user_ok)):
    s, e = db.vn_day_range(db.now_utc().astimezone(db.VN).strftime("%Y-%m-%d"))
    c = lambda sql: db.one(sql, (s, e))[0]
    return {
        "inside_now": db.one("SELECT COUNT(*) FROM lot_sessions WHERE status='IN'")[0],
        "in_today": c("SELECT COUNT(*) FROM lot_sessions WHERE time_in>=? AND time_in<?"),
        "out_today": c("SELECT COUNT(*) FROM lot_sessions WHERE time_out>=? AND time_out<?"),
        "hold_today": c("SELECT COUNT(*) FROM events WHERE decision='HOLD' AND time>=? AND time<?"),
        "unreadable_today": c("SELECT COUNT(*) FROM events WHERE status='UNREADABLE' AND time>=? AND time<?"),
    }


@api.post("/gate/{gate}/override")
async def gate_override(gate: str, body: OverrideIn, u=Depends(user_ok)):
    if gate not in ("IN", "OUT"):
        raise ApiError(404, "NOT_FOUND", "Không có cổng này.")
    return {"event": logic.override(gate, body.event_id, body.action, body.manual_plate, body.session_id, u)}


@api.get("/events")
async def list_events(gate: str = "", status: str = "", plate: str = "", from_: str = Query("", alias="from"), to: str = "",
                       cursor: str = "", limit: int = 50, _=Depends(user_ok)):
    w, a = [], []
    if gate in ("IN", "OUT"):
        w.append("gate=?"); a.append(gate)
    if status in ("OK", "DUPLICATE_IN", "MISMATCH", "UNREADABLE", "FUZZY"):
        w.append("status=?"); a.append(status)
    if plate:
        w.append("plate_norm LIKE ?"); a.append(f"%{norm(plate)}%")
    try:
        if from_:
            w.append("time>=?"); a.append(db.vn_day_range(from_)[0])
        if to:
            w.append("time<?"); a.append(db.vn_day_range(to)[1])
    except ValueError:
        raise ApiError(422, "INVALID", "Ngày không đúng định dạng YYYY-MM-DD.")
    if cursor.isdigit():
        w.append("event_id<?"); a.append(int(cursor))
    limit = max(1, min(limit, 200))
    rows = db.all_(f"SELECT * FROM events {'WHERE ' + ' AND '.join(w) if w else ''} ORDER BY event_id DESC LIMIT ?", (*a, limit + 1))
    return _page(rows, "event_id", limit, event_out)


@api.api_route("/{rest:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"], include_in_schema=False)
async def api_404(rest: str):
    raise ApiError(404, "NOT_FOUND", "Không có đường dẫn này.")


app.include_router(api)


# ---------- WebSocket ----------
@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    origin = ws.headers.get("origin")
    if origin and urlparse(origin).netloc != ws.headers.get("host"):
        await ws.close(code=4403)
        return
    u = _user_from_token(ws.cookies.get(config.COOKIE_NAME))
    if not u or u["must_change_password"] or hub.blocked:
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # không dùng nội dung, chỉ để biết khi nào đóng
    except Exception:
        pass
    finally:
        hub.clients.discard(ws)


# ---------- ảnh ----------
@app.get("/media/{path:path}")
async def media_file(path: str, _=Depends(user_any)):
    base = (config.data_dir() / "media").resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():  # chặn ../ và file ngoài thư mục ảnh
        raise ApiError(404, "NOT_FOUND", "Không có ảnh này.")
    return FileResponse(f, headers={"Cache-Control": "private, max-age=3600"})


# ---------- công cụ thử (chỉ khi GV_DEV=1) ----------
def reset_demo_data():
    import shutil
    with db.conn:
        for t in ("events", "lot_sessions", "alerts"):
            db.conn.execute(f"DELETE FROM {t}")
        db.conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('events','lot_sessions','alerts')")
        db.conn.execute("UPDATE devices SET online=1, state='IDLE', last_seen=?, boot_at=?", (db.iso(db.now_utc()), time.time() - 86400))
    shutil.rmtree(config.data_dir() / "media" / "events", ignore_errors=True)
    hub.blocked = False
    seed_demo()

CONF_SWAP = logic.CONFUSABLE


@app.post("/dev/sim/{kind}")
async def dev_sim(kind: str, _=Depends(user_ok)):
    if not config.dev():
        raise ApiError(404, "NOT_FOUND", "Không có đường dẫn này.")
    inside = db.all_("SELECT * FROM lot_sessions WHERE status='IN'")
    conf = lambda: random.uniform(0.78, 0.96)

    def fresh():
        while True:
            p = random.choice(["59A", "59D", "51G", "50M", "62E", "75C"]) + random.choice("123456789") + "-" + str(random.randint(10000, 99999))
            if not logic.in_lot(p):
                return p

    cap = lambda g, p, c: logic.process_capture(g, p, c, make_images=media.fake_images)
    if kind == "in_ok":
        cap("IN", fresh(), conf())
    elif kind == "out_ok" and inside:
        cap("OUT", random.choice(inside)["plate"], conf())
    elif kind == "dup_in" and inside:
        cap("IN", random.choice(inside)["plate"], conf())
    elif kind == "unreadable_in":
        cap("IN", None, 0)
    elif kind == "unreadable_out":
        cap("OUT", None, 0)
    elif kind == "mismatch_out":
        cap("OUT", fresh(), conf())
    elif kind == "fuzzy_out":
        s = next((x for x in inside if any(c in CONF_SWAP for c in x["plate_norm"])), None)
        if not s:
            ev = cap("IN", "59B1-10805", 0.9)
            s = db.one("SELECT * FROM lot_sessions WHERE id=?", (ev["session_id"],))
        r = list(s["plate_norm"])
        i = next(i for i, c in enumerate(r) if c in CONF_SWAP)
        r[i] = CONF_SWAP[r[i]]
        t = "".join(r)
        cap("OUT", t[:4] + "-" + t[4:], 0.82)
    elif kind in ("cam_toggle", "cam_a_toggle"):
        gate = "IN" if kind == "cam_a_toggle" else "OUT"
        d = db.one("SELECT * FROM devices WHERE gate=?", (gate,))
        on = not d["online"]
        with db.conn:
            db.conn.execute("UPDATE devices SET online=?, state=?, last_seen=? WHERE device_id=?", (int(on), "IDLE" if on else "OFFLINE", db.iso(db.now_utc()), d["device_id"]))
        hub.emit({"type": "device_status", "data": device_out(db.one("SELECT * FROM devices WHERE device_id=?", (d["device_id"],)))})
        if on:
            logic.resolve_alerts("type='DEVICE_OFFLINE' AND device_id=?", (d["device_id"],))
        else:
            logic.create_alert("DEVICE_OFFLINE", f"Camera {'A' if gate == 'IN' else 'B'} mất kết nối", device_id=d["device_id"])
    elif kind == "hold_short":  # lượt giữ chỉ 15 giây, để thử hết hạn
        logic.process_capture("OUT", fresh(), conf(), make_images=media.fake_images, hold_s=15)
    elif kind == "multi_hold":  # ba lượt giữ cùng lúc, để thử hàng chờ
        cap("IN", None, 0)
        cap("OUT", fresh(), conf())
        if inside:
            cap("IN", random.choice(inside)["plate"], conf())
        else:
            cap("OUT", None, 0)
    elif kind == "burst":  # 30 xe vào rồi ra, để thử phân trang
        for _ in range(30):
            p = fresh()
            cap("IN", p, conf())
            cap("OUT", p, conf())
    elif kind == "reset":  # xóa lượt xe/cảnh báo, nạp lại dữ liệu mẫu; giữ nguyên tài khoản
        reset_demo_data()
    elif kind == "ws_toggle":
        hub.blocked = not hub.blocked
        if hub.blocked:
            await hub.drop_all()
    else:
        raise ApiError(404, "NOT_FOUND", "Không có kịch bản này.")
    return {}


# ---------- web tĩnh ----------
@app.get("/js/config.js", include_in_schema=False)
async def web_config():
    js = ("window.GV_CONFIG = {USE_MOCK:false, DEV_TOOLS:%s, API_BASE:'/api/v1', WS_PATH:'/ws/events', HOLD_MAX_S:%d, TZ:'Asia/Ho_Chi_Minh'};"
          % ("true" if config.dev() else "false", config.hold_max_s()))
    return Response(js, media_type="application/javascript", headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=str(config.web_dir()), html=True), name="web")
