import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "reservations.db"
KST = timezone(timedelta(hours=9))
SLOTS = [f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 30)]  # 09:00~17:30, 18칸

app = FastAPI(title="다온소프트 회의실 예약")


def now_kst() -> datetime:
    return datetime.now(KST)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS rr_user (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rr_room (
                room_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS rr_reservation (
                reservation_id INTEGER PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES rr_room(room_id),
                user_id INTEGER NOT NULL REFERENCES rr_user(user_id),
                rsv_date TEXT NOT NULL,
                slot_start TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_rr_active_slot
                ON rr_reservation (room_id, rsv_date, slot_start)
                WHERE status = 'active';
            """
        )
        if c.execute("SELECT COUNT(*) FROM rr_user").fetchone()[0] == 0:
            c.executemany(
                "INSERT INTO rr_user (user_id, name) VALUES (?, ?)",
                [(1, "김다온"), (2, "이소프트"), (3, "박예약"), (4, "최회의"), (5, "정시간")],
            )
        if c.execute("SELECT COUNT(*) FROM rr_room").fetchone()[0] == 0:
            c.executemany(
                "INSERT INTO rr_room (room_id, name) VALUES (?, ?)",
                [(1, "회의실 A"), (2, "회의실 B"), (3, "회의실 C")],
            )
        if c.execute("SELECT COUNT(*) FROM rr_reservation").fetchone()[0] == 0:
            today = now_kst().strftime("%Y-%m-%d")
            stamp = now_kst().strftime("%Y-%m-%d %H:%M:%S")
            demo = [(2, 3, "09:00"), (2, 3, "09:30"), (1, 2, "13:00"), (1, 2, "13:30"),
                    (3, 4, "15:00"), (3, 5, "16:30")]
            c.executemany(
                "INSERT INTO rr_reservation (room_id, user_id, rsv_date, slot_start, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(r, u, today, s, stamp) for r, u, s in demo],
            )


init_db()


def slot_started(rsv_date: str, slot: str) -> bool:
    start = datetime.strptime(f"{rsv_date} {slot}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    return start <= now_kst()


class ReservationIn(BaseModel):
    room_id: int
    slot_start: str
    user_id: int


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.get("/api/users")
def users():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT user_id, name FROM rr_user ORDER BY user_id")]


@app.get("/api/timetable")
def timetable(date: str | None = Query(None)):
    # Phase 1: 오늘만 제공
    today = now_kst().strftime("%Y-%m-%d")
    if date not in (None, today):
        raise HTTPException(400, "오늘 날짜만 조회할 수 있습니다")
    with db() as c:
        rooms = [dict(r) for r in c.execute("SELECT room_id, name FROM rr_room ORDER BY room_id")]
        rows = c.execute(
            "SELECT r.reservation_id, r.room_id, r.slot_start, r.user_id, u.name AS user_name"
            " FROM rr_reservation r JOIN rr_user u ON u.user_id = r.user_id"
            " WHERE r.rsv_date = ? AND r.status = 'active'",
            (today,),
        ).fetchall()
    booked = {(r["room_id"], r["slot_start"]): r for r in rows}
    out_rooms = []
    for room in rooms:
        slots = []
        for s in SLOTS:
            b = booked.get((room["room_id"], s))
            slots.append({
                "slot_start": s,
                "past": slot_started(today, s),
                "reservation_id": b["reservation_id"] if b else None,
                "user_id": b["user_id"] if b else None,
                "user_name": b["user_name"] if b else None,
            })
        out_rooms.append({**room, "slots": slots})
    return {"date": today, "now": now_kst().strftime("%H:%M"), "rooms": out_rooms}


@app.post("/api/reservations", status_code=201)
def create_reservation(body: ReservationIn):
    today = now_kst().strftime("%Y-%m-%d")
    if body.slot_start not in SLOTS:  # R-02
        raise HTTPException(400, "예약할 수 없는 시간입니다 (09:00~17:30, 30분 단위)")
    if slot_started(today, body.slot_start):  # R-03
        raise HTTPException(400, "이미 지난 시간은 예약할 수 없습니다")
    with db() as c:
        if not c.execute("SELECT 1 FROM rr_user WHERE user_id = ?", (body.user_id,)).fetchone():
            raise HTTPException(400, "알 수 없는 사용자입니다")
        if not c.execute("SELECT 1 FROM rr_room WHERE room_id = ?", (body.room_id,)).fetchone():
            raise HTTPException(400, "알 수 없는 회의실입니다")
        try:  # R-01, R-08: 부분 유니크 인덱스가 최종 판정
            cur = c.execute(
                "INSERT INTO rr_reservation (room_id, user_id, rsv_date, slot_start, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (body.room_id, body.user_id, today, body.slot_start,
                 now_kst().strftime("%Y-%m-%d %H:%M:%S")),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "이미 예약된 시간입니다")
        return {"reservation_id": cur.lastrowid}


@app.delete("/api/reservations/{reservation_id}")
def cancel_reservation(reservation_id: int, user_id: int = Query(...)):
    with db() as c:
        r = c.execute(
            "SELECT * FROM rr_reservation WHERE reservation_id = ? AND status = 'active'",
            (reservation_id,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "예약을 찾을 수 없습니다")
        if r["user_id"] != user_id:  # R-04
            raise HTTPException(403, "본인의 예약만 취소할 수 있습니다")
        if slot_started(r["rsv_date"], r["slot_start"]):  # R-05
            raise HTTPException(400, "이미 시작된 시간의 예약은 취소할 수 없습니다")
        c.execute(
            "UPDATE rr_reservation SET status = 'cancelled', cancelled_at = ?"
            " WHERE reservation_id = ?",
            (now_kst().strftime("%Y-%m-%d %H:%M:%S"), reservation_id),
        )
    return {"ok": True}
