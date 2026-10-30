import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = os.environ.get("MR_DB", str(BASE / "meeting.db"))
KST = timezone(timedelta(hours=9))
SLOTS = [f"{9 + i // 2:02d}:{'30' if i % 2 else '00'}" for i in range(18)]

app = FastAPI()


def now():
    """서버 시계(KST). 테스트에서 교체 가능."""
    return datetime.now(KST)


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mr_rooms (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                capacity INTEGER
            );
            CREATE TABLE IF NOT EXISTS mr_users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mr_bookings (
                id INTEGER PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES mr_rooms(id),
                user_id INTEGER NOT NULL REFERENCES mr_users(id),
                booking_date TEXT NOT NULL,
                slot_start TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('ACTIVE','CANCELLED')),
                title TEXT,
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_mr_bookings_active
                ON mr_bookings(room_id, booking_date, slot_start)
                WHERE status = 'ACTIVE';
            """
        )
        if conn.execute("SELECT COUNT(*) FROM mr_rooms").fetchone()[0] == 0 and \
           conn.execute("SELECT COUNT(*) FROM mr_users").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO mr_rooms(id, name, capacity) VALUES (?,?,?)",
                [(1, "회의실 A", 4), (2, "회의실 B", 8), (3, "회의실 C", 12)],
            )
            conn.executemany(
                "INSERT INTO mr_users(id, name) VALUES (?,?)",
                [(1, "김가온"), (2, "이나래"), (3, "박도윤"), (4, "최서연"), (5, "정하람")],
            )
            t = now()
            today, ts = t.strftime("%Y-%m-%d"), t.isoformat(timespec="seconds")
            conn.executemany(
                "INSERT INTO mr_bookings(room_id,user_id,booking_date,slot_start,status,created_at)"
                " VALUES (?,?,?,?,'ACTIVE',?)",
                [(2, 1, today, "09:00", ts), (2, 1, today, "09:30", ts), (3, 2, today, "17:30", ts)],
            )
    conn.close()


init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def booking_dict(row):
    return {k: row[k] for k in row.keys()}


def slot_started(date_str, slot, t):
    start = datetime.strptime(f"{date_str} {slot}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    return start <= t


def to_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v)
    return None


def table(name):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {name} ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/rooms")
def rooms():
    return table("mr_rooms")


@app.get("/api/users")
def users():
    return table("mr_users")


@app.get("/api/schedule")
def schedule(date: str = None):
    today = now().strftime("%Y-%m-%d")
    if date is None:
        date = today
    if date != today:
        return err(400, "오늘 날짜만 조회·예약할 수 있습니다")
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM mr_bookings WHERE booking_date=? AND status='ACTIVE' ORDER BY slot_start, room_id",
            (date,),
        ).fetchall()
        return [booking_dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/bookings")
async def create_booking(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        body = {}
    conn = connect()
    try:
        user_id = to_int(body.get("user_id"))
        if user_id is None or not conn.execute("SELECT 1 FROM mr_users WHERE id=?", (user_id,)).fetchone():
            return err(400, "사용자를 선택해 주세요")
        room_id = to_int(body.get("room_id"))
        if room_id is None or not conn.execute("SELECT 1 FROM mr_rooms WHERE id=?", (room_id,)).fetchone():
            return err(404, "존재하지 않는 회의실입니다")
        t = now()
        today = t.strftime("%Y-%m-%d")
        d = body.get("booking_date", body.get("date"))
        if d is not None and d != today:
            return err(400, "오늘 날짜만 조회·예약할 수 있습니다")
        slot = body.get("slot_start")
        if not isinstance(slot, str) or slot not in SLOTS:
            return err(400, "예약할 수 없는 시간입니다")
        if slot_started(today, slot, t):
            return err(400, "이미 지난 시간은 예약할 수 없습니다")
        try:
            with conn:
                if conn.execute(
                    "SELECT 1 FROM mr_bookings WHERE room_id=? AND booking_date=? AND slot_start=? AND status='ACTIVE'",
                    (room_id, today, slot),
                ).fetchone():
                    return err(409, "이미 예약된 시간입니다")
                cur = conn.execute(
                    "INSERT INTO mr_bookings(room_id,user_id,booking_date,slot_start,status,created_at)"
                    " VALUES (?,?,?,?,'ACTIVE',?)",
                    (room_id, user_id, today, slot, t.isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            return err(409, "이미 예약된 시간입니다")
        row = conn.execute("SELECT * FROM mr_bookings WHERE id=?", (cur.lastrowid,)).fetchone()
        return JSONResponse(booking_dict(row), status_code=201)
    finally:
        conn.close()


@app.delete("/api/bookings/{booking_id}")
def cancel_booking(booking_id: int, user_id: str = None):
    conn = connect()
    try:
        uid = to_int(user_id)
        if uid is None or not conn.execute("SELECT 1 FROM mr_users WHERE id=?", (uid,)).fetchone():
            return err(400, "사용자를 선택해 주세요")
        t = now()
        with conn:
            row = conn.execute("SELECT * FROM mr_bookings WHERE id=?", (booking_id,)).fetchone()
            if not row:
                return err(404, "예약을 찾을 수 없습니다")
            if row["user_id"] != uid:
                return err(403, "본인 예약만 취소할 수 있습니다")
            if row["status"] == "CANCELLED":
                return err(409, "이미 취소된 예약입니다")
            if slot_started(row["booking_date"], row["slot_start"], t):
                return err(400, "이미 시작된 예약은 취소할 수 없습니다")
            conn.execute(
                "UPDATE mr_bookings SET status='CANCELLED', cancelled_at=? WHERE id=?",
                (t.isoformat(timespec="seconds"), booking_id),
            )
        row = conn.execute("SELECT * FROM mr_bookings WHERE id=?", (booking_id,)).fetchone()
        return booking_dict(row)
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
