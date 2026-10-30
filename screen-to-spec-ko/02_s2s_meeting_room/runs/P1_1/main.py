import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "meeting_rooms.db"
KST = timezone(timedelta(hours=9))  # R-10: 서버 시각은 한국 표준시

SLOTS = [f"{9 + i // 2:02d}:{'30' if i % 2 else '00'}" for i in range(18)]  # 09:00 ~ 17:30

SEED_ROOMS = ["A", "B", "C"]
SEED_USERS = ["김가온", "이서연", "박도윤", "최하늘", "정나래", "한지호", "오시우", "윤다온"]  # 가상 이름


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mr_rooms (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS mr_users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS mr_reservations (
                id INTEGER PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES mr_rooms(id),
                user_id INTEGER NOT NULL REFERENCES mr_users(id),
                rsv_date TEXT NOT NULL,
                slot_start TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('active', 'cancelled')),
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS mr_uq_active_slot
                ON mr_reservations (room_id, rsv_date, slot_start)
                WHERE status = 'active';
            """
        )
        if conn.execute("SELECT COUNT(*) FROM mr_rooms").fetchone()[0] == 0:
            conn.executemany("INSERT INTO mr_rooms (name) VALUES (?)", [(n,) for n in SEED_ROOMS])
        if conn.execute("SELECT COUNT(*) FROM mr_users").fetchone()[0] == 0:
            conn.executemany("INSERT INTO mr_users (name) VALUES (?)", [(n,) for n in SEED_USERS])
    conn.close()


def slot_start_dt(date_str: str, slot: str) -> datetime:
    return datetime.strptime(f"{date_str} {slot}", "%Y-%m-%d %H:%M")


app = FastAPI(title="회의실 예약")
init_db()


class ReserveIn(BaseModel):
    room_id: int
    user_id: int
    slot_start: str


class CancelIn(BaseModel):
    user_id: int


@app.get("/api/schedule")
def schedule():
    """Phase 1: 오늘 하루 시간표."""
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    conn = get_db()
    try:
        rooms = [dict(r) for r in conn.execute("SELECT id, name FROM mr_rooms ORDER BY id")]
        users = [dict(r) for r in conn.execute("SELECT id, name FROM mr_users ORDER BY id")]
        rsvs = [
            dict(r)
            for r in conn.execute(
                """SELECT r.id, r.room_id, r.user_id, u.name AS user_name, r.slot_start
                   FROM mr_reservations r JOIN mr_users u ON u.id = r.user_id
                   WHERE r.rsv_date = ? AND r.status = 'active'""",
                (today,),
            )
        ]
    finally:
        conn.close()
    return {
        "date": today,
        "now": now.strftime("%H:%M"),
        "slots": SLOTS,
        "rooms": rooms,
        "users": users,
        "reservations": rsvs,
    }


@app.post("/api/reservations", status_code=201)
def create_reservation(body: ReserveIn):
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    if body.slot_start not in SLOTS:  # R-01
        raise HTTPException(400, "예약할 수 없는 시간입니다. (09:00~18:00, 30분 단위)")
    if slot_start_dt(today, body.slot_start) < now:  # R-04
        raise HTTPException(400, "이미 지난 시간은 예약할 수 없습니다.")
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM mr_rooms WHERE id = ?", (body.room_id,)).fetchone():
            raise HTTPException(404, "회의실을 찾을 수 없습니다.")
        if not conn.execute("SELECT 1 FROM mr_users WHERE id = ?", (body.user_id,)).fetchone():
            raise HTTPException(404, "사용자를 찾을 수 없습니다.")
        try:  # R-03: 부분 유니크 인덱스가 최종 방어선
            with conn:
                cur = conn.execute(
                    """INSERT INTO mr_reservations
                       (room_id, user_id, rsv_date, slot_start, status, created_at)
                       VALUES (?, ?, ?, ?, 'active', ?)""",
                    (body.room_id, body.user_id, today, body.slot_start, now.strftime("%Y-%m-%d %H:%M:%S")),
                )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "이미 다른 예약이 있는 시간입니다.")
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/reservations/{rsv_id}/cancel")
def cancel_reservation(rsv_id: int, body: CancelIn):
    now = now_kst()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id, rsv_date, slot_start, status FROM mr_reservations WHERE id = ?", (rsv_id,)
        ).fetchone()
        if not row or row["status"] != "active":
            raise HTTPException(404, "취소할 예약을 찾을 수 없습니다.")
        if row["user_id"] != body.user_id:  # R-05
            raise HTTPException(403, "본인의 예약만 취소할 수 있습니다.")
        if slot_start_dt(row["rsv_date"], row["slot_start"]) <= now:  # R-06
            raise HTTPException(400, "이미 시작했거나 지난 예약은 취소할 수 없습니다.")
        with conn:  # R-07: 삭제하지 않고 상태만 변경
            conn.execute(
                "UPDATE mr_reservations SET status = 'cancelled', cancelled_at = ? WHERE id = ? AND status = 'active'",
                (now.strftime("%Y-%m-%d %H:%M:%S"), rsv_id),
            )
        return {"ok": True}
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
