"""SQLite đơn giản. Một kết nối duy nhất, mọi truy vấn chạy trên luồng của vòng lặp sự kiện."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

conn: sqlite3.Connection = None  # type: ignore
VN = timezone(timedelta(hours=7))  # Việt Nam không có giờ mùa hè

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','staff')), must_change_password INTEGER NOT NULL DEFAULT 1,
  pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices(
  device_id TEXT PRIMARY KEY, gate TEXT NOT NULL, ip TEXT, rssi INTEGER, state TEXT NOT NULL,
  online INTEGER NOT NULL, last_seen TEXT NOT NULL, boot_at REAL NOT NULL, stream_url TEXT);
CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, gate TEXT NOT NULL, device_id TEXT NOT NULL,
  plate TEXT, plate_norm TEXT, confidence REAL, decision TEXT NOT NULL, status TEXT NOT NULL,
  image_url TEXT, plate_image_url TEXT, session_id INTEGER, fuzzy TEXT NOT NULL DEFAULT '[]',
  resolution TEXT, hold_expires_at TEXT);
CREATE INDEX IF NOT EXISTS ix_events_time ON events(time);
CREATE TABLE IF NOT EXISTS lot_sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL, plate_norm TEXT NOT NULL,
  time_in TEXT NOT NULL, image_in_url TEXT, confidence_in REAL,
  time_out TEXT, image_out_url TEXT, confidence_out REAL,
  status TEXT NOT NULL CHECK(status IN ('IN','OUT')), flagged INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_lot_status ON lot_sessions(status, plate_norm);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, event_id INTEGER, device_id TEXT,
  time TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL);
"""


def init(path):
    global conn
    if conn is not None:
        conn.close()
    path = str(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def vn_day_range(day: str):
    """'2026-11-17' (ngày theo giờ Việt Nam) -> (đầu ngày, đầu ngày kế) dạng ISO UTC."""
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=VN)
    return iso(d), iso(d + timedelta(days=1))


def one(sql, args=()):
    return conn.execute(sql, args).fetchone()


def all_(sql, args=()):
    return conn.execute(sql, args).fetchall()


def dumps(o):
    return json.dumps(o, ensure_ascii=False)
