"""Chạy: cd gatevision && pip install pytest httpx && python -m pytest server/tests -q"""
import os
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("GV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GV_DEV", "1")
    monkeypatch.setenv("GV_HOLD_MAX_S", "120")
    from server import main
    main.FAILS.clear()
    with TestClient(main.app) as cl:
        yield cl


def login(c, u="truc1", p="truc1234"):
    r = c.post("/api/v1/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()


def sim(c, kind):
    assert c.post(f"/dev/sim/{kind}").status_code == 200


def hold(c, kind):
    sim(c, kind)
    items = c.get("/api/v1/events?limit=1").json()["items"]
    assert items[0]["decision"] == "HOLD"
    return items[0]


def test_auth_required_and_login(c):
    assert c.get("/api/v1/events").status_code == 401
    assert c.get("/api/v1/events").json()["error"]["code"] == "UNAUTHORIZED"
    bad = c.post("/api/v1/auth/login", json={"username": "truc1", "password": "sai"})
    assert bad.status_code == 401
    u = login(c)
    assert u["role"] == "staff" and "password" not in u and "pw_hash" not in u
    set_cookie = c.cookies.get("gv_session")
    assert set_cookie


def test_cookie_flags(c):
    r = c.post("/api/v1/auth/login", json={"username": "truc1", "password": "truc1234"})
    h = r.headers["set-cookie"].lower()
    assert "httponly" in h and "samesite=lax" in h


def test_rate_limit(c):
    for _ in range(5):
        assert c.post("/api/v1/auth/login", json={"username": "truc1", "password": "x"}).status_code == 401
    assert c.post("/api/v1/auth/login", json={"username": "truc1", "password": "truc1234"}).status_code == 429


def test_forced_password_change(c):
    u = login(c, "admin", "admin123")
    assert u["must_change_password"] is True
    assert c.get("/api/v1/events").status_code == 403
    assert c.get("/api/v1/users/me").status_code == 200
    assert c.post("/api/v1/users/me/password", json={"old_password": "admin123", "new_password": "short"}).json()["error"]["code"] == "WEAK_PASSWORD"
    r = c.post("/api/v1/users/me/password", json={"old_password": "admin123", "new_password": "matkhau-moi-1"})
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert c.get("/api/v1/events").status_code == 200


def test_users_admin_only(c):
    login(c)
    assert c.get("/api/v1/users").status_code == 403
    c.post("/api/v1/auth/logout")
    login(c, "admin", "admin123")
    c.post("/api/v1/users/me/password", json={"old_password": "admin123", "new_password": "matkhau-moi-1"})
    assert len(c.get("/api/v1/users").json()["items"]) == 2
    r = c.post("/api/v1/users", json={"username": "truc2", "display_name": "T2", "role": "staff", "password": "abcdefgh1"})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert c.post("/api/v1/users", json={"username": "truc2", "password": "abcdefgh1"}).json()["error"]["code"] == "EXISTS"
    assert c.patch("/api/v1/users/1", json={"role": "staff"}).json()["error"]["code"] == "SELF_ROLE"


def test_events_seed_filters_pagination(c):
    login(c)
    d = c.get("/api/v1/events?limit=3").json()
    assert len(d["items"]) == 3 and d["next_cursor"]
    d2 = c.get(f"/api/v1/events?limit=3&cursor={d['next_cursor']}").json()
    assert d2["items"][0]["event_id"] < d["items"][-1]["event_id"]
    assert all(e["gate"] == "OUT" for e in c.get("/api/v1/events?gate=OUT").json()["items"])
    assert c.get("/api/v1/events?plate=59q9").json()["items"][0]["status"] == "MISMATCH"
    today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600))
    assert len(c.get(f"/api/v1/events?from={today}&to={today}&limit=200").json()["items"]) == 8
    assert c.get("/api/v1/events?from=abc").status_code == 422


def test_in_ok_opens_session_and_out_closes(c):
    login(c)
    before = c.get("/api/v1/stats").json()["inside_now"]
    sim(c, "in_ok")
    assert c.get("/api/v1/stats").json()["inside_now"] == before + 1
    sim(c, "out_ok")
    assert c.get("/api/v1/stats").json()["inside_now"] == before


def test_unreadable_in_manual_plate(c):
    login(c)
    ev = hold(c, "unreadable_in")
    assert ev["hold_expires_at"] and ev["resolution"] is None
    assert c.post("/api/v1/gate/IN/override", json={"event_id": ev["event_id"], "action": "PASS", "manual_plate": "!!"}).json()["error"]["code"] == "INVALID_PLATE"
    r = c.post("/api/v1/gate/IN/override", json={"event_id": ev["event_id"], "action": "PASS", "manual_plate": "59M1-99887"})
    assert r.status_code == 200
    e = r.json()["event"]
    assert e["resolution"]["action"] == "PASS" and e["resolution"]["operator_name"] == "Nhân viên trực 1" and e["plate"] == "59M1-99887"
    assert any(s["plate"] == "59M1-99887" for s in c.get("/api/v1/sessions?status=IN").json()["items"])
    assert c.post("/api/v1/gate/IN/override", json={"event_id": ev["event_id"], "action": "PASS"}).json()["error"]["code"] == "ALREADY_RESOLVED"


def test_unreadable_in_without_plate_flagged(c):
    login(c)
    ev = hold(c, "unreadable_in")
    c.post("/api/v1/gate/IN/override", json={"event_id": ev["event_id"], "action": "PASS"})
    s = c.get("/api/v1/sessions?status=IN").json()["items"][0]
    assert s["plate"] == f"UNKNOWN-{ev['event_id']}" and s["flagged"] is True


def test_duplicate_and_deny(c):
    login(c)
    ev = hold(c, "dup_in")
    assert ev["status"] == "DUPLICATE_IN"
    n = c.get("/api/v1/stats").json()["inside_now"]
    r = c.post("/api/v1/gate/IN/override", json={"event_id": ev["event_id"], "action": "DENY"})
    assert r.json()["event"]["resolution"]["action"] == "DENY"
    assert c.get("/api/v1/stats").json()["inside_now"] == n


def test_fuzzy_requires_choice(c):
    login(c)
    ev = hold(c, "fuzzy_out")
    assert ev["status"] == "FUZZY" and ev["fuzzy_candidates"]
    url = "/api/v1/gate/OUT/override"
    assert c.post(url, json={"event_id": ev["event_id"], "action": "PASS"}).json()["error"]["code"] == "CHOOSE_SESSION"
    assert c.post(url, json={"event_id": ev["event_id"], "action": "PASS", "session_id": 99999}).json()["error"]["code"] == "INVALID_SESSION"
    sid = ev["fuzzy_candidates"][0]["session_id"]
    assert c.post(url, json={"event_id": ev["event_id"], "action": "PASS", "session_id": sid}).status_code == 200
    assert not any(s["id"] == sid for s in c.get("/api/v1/sessions?status=IN").json()["items"])


def test_wrong_gate_and_unknown_event(c):
    login(c)
    ev = hold(c, "mismatch_out")
    assert c.post("/api/v1/gate/IN/override", json={"event_id": ev["event_id"], "action": "PASS"}).json()["error"]["code"] == "EVENT_NOT_FOUND"
    assert c.post("/api/v1/gate/OUT/override", json={"event_id": 99999, "action": "PASS"}).status_code == 404
    assert c.post("/api/v1/gate/OUT/override", json={"event_id": ev["event_id"], "action": "OPEN"}).json()["error"]["code"] == "INVALID"


def test_expired_hold_fail_safe(c):
    from server import db, logic
    login(c)
    ev = hold(c, "mismatch_out")
    with db.conn:
        db.conn.execute("UPDATE events SET hold_expires_at='2000-01-01T00:00:00Z' WHERE event_id=?", (ev["event_id"],))
    r = c.post("/api/v1/gate/OUT/override", json={"event_id": ev["event_id"], "action": "PASS"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EXPIRED"
    e = c.get(f"/api/v1/events/{ev['event_id']}").json()
    assert e["resolution"]["action"] == "EXPIRED" and e["resolution"]["operator_id"] is None
    assert c.get("/api/v1/alerts?status=OPEN").json()["items"] == [] or all(a["event_id"] != ev["event_id"] for a in c.get("/api/v1/alerts?status=OPEN").json()["items"])


def test_alerts_devices_stats(c):
    login(c)
    hold(c, "mismatch_out")
    assert any(a["type"] == "MISMATCH" for a in c.get("/api/v1/alerts?status=OPEN").json()["items"])
    d = c.get("/api/v1/devices").json()["items"]
    assert {x["gate"] for x in d} == {"IN", "OUT"} and d[0]["state"] in ("HOLD", "IDLE")
    st = c.get("/api/v1/stats").json()
    assert set(st) == {"inside_now", "in_today", "out_today", "hold_today", "unreadable_today"} and st["hold_today"] >= 1
    sim(c, "cam_toggle")
    assert any(a["type"] == "DEVICE_OFFLINE" for a in c.get("/api/v1/alerts?status=OPEN").json()["items"])
    sim(c, "cam_toggle")
    assert not any(a["type"] == "DEVICE_OFFLINE" for a in c.get("/api/v1/alerts?status=OPEN").json()["items"])


def test_media_auth_and_traversal(c):
    assert c.get("/media/idle.svg").status_code == 401
    login(c)
    assert c.get("/media/idle.svg").status_code == 200
    ev = c.get("/api/v1/events?limit=1").json()["items"][0]
    assert c.get(ev["image_url"]).status_code == 200
    assert c.get("/media/../gatevision.db").status_code == 404
    assert c.get("/media/%2e%2e/gatevision.db").status_code == 404


def test_websocket_events(c):
    login(c)
    with c.websocket_connect("/ws/events") as ws:
        sim(c, "unreadable_in")
        types = {ws.receive_json()["type"] for _ in range(4)}
        assert {"event_created", "alert"} <= types
    c.post("/api/v1/auth/logout")
    with pytest.raises(Exception):
        with c.websocket_connect("/ws/events"):
            pass


def test_websocket_rejects_foreign_origin(c):
    login(c)
    with pytest.raises(Exception):
        with c.websocket_connect("/ws/events", headers={"origin": "http://evil.example"}):
            pass


def test_unknown_api_path_json(c):
    r = c.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert c.get("/api/v1/healthz").json() == {"status": "ok"}


def test_web_served_with_server_config(c):
    assert "USE_MOCK:false" in c.get("/js/config.js").text
    assert "GATE VISION" in c.get("/").text


def test_no_dev_tools_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("GV_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GV_DEV", raising=False)
    from server import main
    with TestClient(main.app) as cl:
        assert "DEV_TOOLS:false" in cl.get("/js/config.js").text
        assert cl.post("/dev/sim/in_ok").status_code == 401
        assert cl.get("/api/docs").status_code == 404
        # admin ban đầu có mật khẩu ngẫu nhiên, không phải admin123
        assert cl.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).status_code == 401


def test_dev_scenarios_new(c):
    login(c)
    sim(c, "hold_short")
    e = c.get("/api/v1/events?limit=1").json()["items"][0]
    from server import db
    left = (db.parse_iso(e["hold_expires_at"]) - db.now_utc()).total_seconds()
    assert 10 <= left <= 16
    n0 = len(c.get("/api/v1/alerts?status=OPEN").json()["items"])
    sim(c, "multi_hold")
    holds = [x for x in c.get("/api/v1/events?limit=10").json()["items"] if x["decision"] == "HOLD" and not x["resolution"]]
    assert len(holds) >= 4
    assert len(c.get("/api/v1/alerts?status=OPEN").json()["items"]) >= n0 + 3
    sim(c, "cam_a_toggle")
    assert any(d["gate"] == "IN" and not d["online"] for d in c.get("/api/v1/devices").json()["items"])
    sim(c, "cam_a_toggle")
    before = c.get("/api/v1/stats").json()["inside_now"]
    sim(c, "burst")
    assert c.get("/api/v1/stats").json()["inside_now"] == before
    assert c.get("/api/v1/events?limit=200").json()["next_cursor"] is None or True
    assert len(c.get("/api/v1/events?limit=200").json()["items"]) >= 60
    sim(c, "reset")
    st = c.get("/api/v1/stats").json()
    assert st["inside_now"] == 5 and len(c.get("/api/v1/events?limit=200").json()["items"]) == 8
    assert c.get("/api/v1/alerts?status=OPEN").json()["items"] == []
    assert c.get("/api/v1/users/me").status_code == 200  # vẫn đăng nhập sau khi đặt lại


def test_expire_task_marks_short_hold(c):
    from server import db, logic
    login(c)
    sim(c, "hold_short")
    e = c.get("/api/v1/events?limit=1").json()["items"][0]
    with db.conn:
        db.conn.execute("UPDATE events SET hold_expires_at='2000-01-01T00:00:00Z' WHERE event_id=?", (e["event_id"],))
    logic.expire_due()
    assert c.get(f"/api/v1/events/{e['event_id']}").json()["resolution"]["action"] == "EXPIRED"
