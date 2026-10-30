import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "meeting_room.db"
KST = timezone(timedelta(hours=9))  # R-10

SLOTS = [f"{9 + i // 2:02d}:{'30' if i % 2 else '00'}" for i in range(18)]  # R-01

app = FastAPI(title="회의실 예약")


def now_kst() -> datetime:
    return datetime.now(KST)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db()
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
                status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'CANCELLED')),
                title TEXT NULL,
                created_at TEXT NOT NULL,
                cancelled_at TEXT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_mr_bookings_active
                ON mr_bookings (room_id, booking_date, slot_start)
                WHERE status = 'ACTIVE';
            """
        )
        if conn.execute("SELECT COUNT(*) FROM mr_rooms").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO mr_rooms (name, capacity) VALUES (?, ?)",
                [("회의실 A", 4), ("회의실 B", 8), ("회의실 C", 12)],
            )
            conn.executemany(
                "INSERT INTO mr_users (name) VALUES (?)",
                [("김가온",), ("이나래",), ("박도윤",), ("최서연",), ("정하람",)],
            )
            today = now_kst().strftime("%Y-%m-%d")
            stamp = now_kst().isoformat(timespec="seconds")
            seeds = [(2, 1, "09:00"), (2, 1, "09:30"), (3, 2, "17:30"), (1, 3, "14:00")]
            conn.executemany(
                "INSERT INTO mr_bookings (room_id, user_id, booking_date, slot_start,"
                " status, created_at) VALUES (?, ?, ?, ?, 'ACTIVE', ?)",
                [(r, u, today, s, stamp) for r, u, s in seeds],
            )
    conn.close()


init_db()


def require_today(date: str) -> str:
    today = now_kst().strftime("%Y-%m-%d")
    if date != today:  # R-07
        raise HTTPException(400, "오늘 날짜만 이용할 수 있습니다")
    return today


def slot_started(date: str, slot: str) -> bool:
    start = datetime.strptime(f"{date} {slot}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    return start <= now_kst()  # R-04, R-05


class BookingIn(BaseModel):
    room_id: int
    slot_start: str
    user_id: int


@app.get("/api/rooms")
def rooms():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name, capacity FROM mr_rooms ORDER BY id")]


@app.get("/api/users")
def users():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name FROM mr_users ORDER BY id")]


@app.get("/api/schedule")
def schedule(date: str = Query(...)):
    today = require_today(date)
    with db() as conn:
        rows = conn.execute(
            "SELECT b.id, b.room_id, b.slot_start, b.user_id, u.name AS user_name"
            " FROM mr_bookings b JOIN mr_users u ON u.id = b.user_id"
            " WHERE b.booking_date = ? AND b.status = 'ACTIVE'",
            (today,),
        ).fetchall()
    return {
        "date": today,
        "now": now_kst().isoformat(timespec="seconds"),
        "slots": SLOTS,
        "bookings": [dict(r) for r in rows],
    }


@app.post("/api/bookings", status_code=201)
def create_booking(body: BookingIn):
    today = now_kst().strftime("%Y-%m-%d")
    if body.slot_start not in SLOTS:
        raise HTTPException(400, "올바르지 않은 시간입니다")
    if slot_started(today, body.slot_start):
        raise HTTPException(400, "이미 시작된 시간은 예약할 수 없습니다")
    conn = db()
    try:
        if not conn.execute("SELECT 1 FROM mr_rooms WHERE id = ?", (body.room_id,)).fetchone():
            raise HTTPException(404, "회의실을 찾을 수 없습니다")
        if not conn.execute("SELECT 1 FROM mr_users WHERE id = ?", (body.user_id,)).fetchone():
            raise HTTPException(404, "사용자를 찾을 수 없습니다")
        taken = conn.execute(
            "SELECT 1 FROM mr_bookings WHERE room_id = ? AND booking_date = ?"
            " AND slot_start = ? AND status = 'ACTIVE'",
            (body.room_id, today, body.slot_start),
        ).fetchone()
        if taken:
            raise HTTPException(409, "이미 예약된 시간입니다")
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO mr_bookings (room_id, user_id, booking_date, slot_start,"
                    " status, created_at) VALUES (?, ?, ?, ?, 'ACTIVE', ?)",
                    (body.room_id, body.user_id, today, body.slot_start,
                     now_kst().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:  # 동시 요청: 유니크 인덱스가 막음 (F-05)
            raise HTTPException(409, "이미 예약된 시간입니다")
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.delete("/api/bookings/{booking_id}")
def cancel_booking(booking_id: int, user_id: int = Query(...)):
    conn = db()
    try:
        row = conn.execute(
            "SELECT user_id, booking_date, slot_start, status FROM mr_bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "예약을 찾을 수 없습니다")
        if row["status"] != "ACTIVE":  # R-06
            raise HTTPException(409, "이미 취소된 예약입니다")
        if row["user_id"] != user_id:  # R-03
            raise HTTPException(403, "본인 예약만 취소할 수 있습니다")
        if slot_started(row["booking_date"], row["slot_start"]):  # R-05
            raise HTTPException(400, "이미 시작된 예약은 취소할 수 없습니다")
        with conn:
            cur = conn.execute(
                "UPDATE mr_bookings SET status = 'CANCELLED', cancelled_at = ?"
                " WHERE id = ? AND status = 'ACTIVE'",
                (now_kst().isoformat(timespec="seconds"), booking_id),
            )
        if cur.rowcount == 0:
            raise HTTPException(409, "이미 취소된 예약입니다")
        return {"ok": True}
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
