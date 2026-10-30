"""회의실 예약 웹앱 - Phase 1 (F-01~F-04)."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "reservation.db"
KST = timezone(timedelta(hours=9))
SLOTS = 18          # 09:00 ~ 18:00, 30분 단위
MAX_SLOTS = 8       # 최대 4시간 (R-03)

app = FastAPI(title="회의실 예약")


def now_kst() -> datetime:
    return datetime.now(KST)


def slot_start(date_str: str, slot: int) -> datetime:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=KST)
    return d + timedelta(hours=9, minutes=30 * slot)


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS rsv_user (
            user_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rsv_room (
            room_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rsv_booking (
            booking_id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL REFERENCES rsv_room(room_id),
            user_id INTEGER NOT NULL REFERENCES rsv_user(user_id),
            book_date TEXT NOT NULL,
            start_slot INTEGER NOT NULL,
            end_slot INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL);
        """)
        if con.execute("SELECT COUNT(*) FROM rsv_user").fetchone()[0] == 0:
            con.executemany("INSERT INTO rsv_user(name) VALUES (?)",
                            [(f"사용자{c}",) for c in "ABCDE"])
            con.executemany("INSERT INTO rsv_room(name) VALUES (?)",
                            [(f"회의실 {i}",) for i in (1, 2, 3)])
            today = now_kst().strftime("%Y-%m-%d")
            ts = now_kst().isoformat(timespec="seconds")
            samples = [  # room, user, start, end, title (전부 가상)
                (1, 1, 2, 4, "주간 스탠드업"),
                (1, 2, 12, 15, "기획 리뷰"),
                (2, 3, 4, 6, "디자인 논의"),
                (2, 1, 14, 16, "고객 데모 준비"),
                (3, 4, 8, 10, "팀 워크숍"),
                (3, 5, 16, 17, "회고"),
            ]
            con.executemany(
                "INSERT INTO rsv_booking(room_id,user_id,book_date,start_slot,end_slot,"
                "title,status,created_at) VALUES (?,?,?,?,?,?, 'ACTIVE', ?)",
                [(r, u, today, s, e, t, ts) for r, u, s, e, t in samples])


init_db()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/schedule")
def schedule():
    """오늘의 시간표: 사용자·회의실·ACTIVE 예약 + 서버 현재 시각."""
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    with db() as con:
        users = [dict(r) for r in con.execute("SELECT * FROM rsv_user ORDER BY user_id")]
        rooms = [dict(r) for r in con.execute("SELECT * FROM rsv_room ORDER BY room_id")]
        bookings = [dict(r) for r in con.execute(
            "SELECT b.booking_id, b.room_id, b.user_id, u.name AS user_name, "
            "b.start_slot, b.end_slot, b.title "
            "FROM rsv_booking b JOIN rsv_user u ON u.user_id=b.user_id "
            "WHERE b.book_date=? AND b.status='ACTIVE'", (today,))]
    mins = now.hour * 60 + now.minute - 9 * 60   # 09:00 기준 경과 분 (칸 시작 < mins 이면 지난 칸)
    return {"date": today, "now": now.isoformat(timespec="seconds"), "minutes": mins,
            "users": users, "rooms": rooms, "bookings": bookings}


class BookingIn(BaseModel):
    user_id: int
    room_id: int
    start_slot: int
    end_slot: int
    title: str


class CancelIn(BaseModel):
    user_id: int


@app.post("/api/bookings", status_code=201)
def create_booking(b: BookingIn):
    title = b.title.strip()
    if not 1 <= len(title) <= 30:                                   # R-05
        raise HTTPException(400, "제목은 1~30자로 입력해 주세요.")
    if not (0 <= b.start_slot < b.end_slot <= SLOTS):               # R-01
        raise HTTPException(400, "예약 가능 시간은 09:00~18:00 입니다.")
    if b.end_slot - b.start_slot > MAX_SLOTS:                       # R-03
        raise HTTPException(400, "예약은 최대 4시간까지 가능합니다.")
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    if slot_start(today, b.start_slot) < now:                       # R-04
        raise HTTPException(400, "이미 지난 시간에는 예약할 수 없습니다.")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")  # 검사~저장 사이 경합 방지
        if not con.execute("SELECT 1 FROM rsv_user WHERE user_id=?", (b.user_id,)).fetchone():
            raise HTTPException(400, "알 수 없는 사용자입니다.")
        if not con.execute("SELECT 1 FROM rsv_room WHERE room_id=?", (b.room_id,)).fetchone():
            raise HTTPException(400, "알 수 없는 회의실입니다.")
        clash = con.execute(                                        # R-02
            "SELECT 1 FROM rsv_booking WHERE room_id=? AND book_date=? AND status='ACTIVE' "
            "AND start_slot < ? AND end_slot > ?",
            (b.room_id, today, b.end_slot, b.start_slot)).fetchone()
        if clash:
            raise HTTPException(409, "이미 예약된 시간입니다.")
        cur = con.execute(
            "INSERT INTO rsv_booking(room_id,user_id,book_date,start_slot,end_slot,"
            "title,status,created_at) VALUES (?,?,?,?,?,?, 'ACTIVE', ?)",
            (b.room_id, b.user_id, today, b.start_slot, b.end_slot, title,
             now.isoformat(timespec="seconds")))
        return {"booking_id": cur.lastrowid}


@app.post("/api/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, c: CancelIn):
    with db() as con:
        row = con.execute("SELECT * FROM rsv_booking WHERE booking_id=?", (booking_id,)).fetchone()
        if not row or row["status"] != "ACTIVE":
            raise HTTPException(404, "예약을 찾을 수 없습니다.")
        if row["user_id"] != c.user_id:                             # R-06
            raise HTTPException(403, "본인의 예약만 취소할 수 있습니다.")
        if slot_start(row["book_date"], row["start_slot"]) <= now_kst():  # R-07
            raise HTTPException(400, "이미 시작했거나 지난 예약은 취소할 수 없습니다.")
        con.execute("UPDATE rsv_booking SET status='CANCELED' WHERE booking_id=?", (booking_id,))
        return {"ok": True}
