import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "rooms.db"
OPEN_HOUR, CLOSE_HOUR = 9, 18
SLOTS = (CLOSE_HOUR - OPEN_HOUR) * 2  # 18 slots of 30 minutes

app = FastAPI(title="다온소프트 회의실 예약")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(db()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rooms(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL, note TEXT);
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bookings(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              room_id INTEGER NOT NULL REFERENCES rooms(id),
              user_id INTEGER NOT NULL REFERENCES users(id),
              day TEXT NOT NULL, start_slot INTEGER NOT NULL, end_slot INTEGER NOT NULL,
              title TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_b ON bookings(day, room_id);
            """
        )
        if conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]:
            return
        conn.executemany("INSERT INTO rooms VALUES(?,?,?,?)", [
            (1, "다온룸", 6, "4인 이상 소규모 회의 · 화이트보드"),
            (2, "한강룸", 10, "중형 · 모니터 / 화상회의"),
            (3, "남산룸", 20, "대형 · 프로젝터 / 전체 회의"),
        ])
        conn.executemany("INSERT INTO users VALUES(?,?,?)", [
            (1, "김민준", "개발팀"), (2, "이서연", "디자인팀"), (3, "박지후", "영업팀"),
            (4, "최유나", "인사팀"), (5, "정도현", "개발팀"), (6, "한소희", "기획팀"),
        ])
        today = date.today()
        # (일 오프셋, 방, 사용자, 시작 "HH:MM", 종료 "HH:MM", 제목)
        seed = [
            (0, 1, 1, "09:30", "10:30", "스프린트 계획"),
            (0, 1, 6, "14:00", "15:00", "신규 서비스 기획 리뷰"),
            (0, 2, 3, "10:00", "11:30", "고객사 미팅"),
            (0, 2, 2, "15:30", "16:30", "디자인 시안 공유"),
            (0, 3, 4, "11:00", "12:00", "분기 전체 회의"),
            (0, 3, 5, "16:00", "17:30", "기술 세미나"),
            (1, 1, 5, "10:00", "11:00", "코드 리뷰"),
            (1, 2, 1, "13:00", "14:30", "아키텍처 논의"),
            (1, 3, 3, "09:00", "10:00", "영업 주간 회의"),
            (2, 1, 2, "11:00", "12:00", "브랜드 가이드 점검"),
            (2, 3, 4, "14:00", "16:00", "신입 사원 교육"),
        ]
        for off, room, user, s, e, title in seed:
            conn.execute(
                "INSERT INTO bookings(room_id,user_id,day,start_slot,end_slot,title) VALUES(?,?,?,?,?,?)",
                (room, user, (today + timedelta(days=off)).isoformat(), to_slot(s), to_slot(e), title))
        conn.commit()


def to_slot(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return (h - OPEN_HOUR) * 2 + m // 30


def parse_day(day: str) -> date:
    try:
        return date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).")


class BookingIn(BaseModel):
    room_id: int
    user_id: int
    day: str
    start_slot: int = Field(ge=0, lt=SLOTS)
    slots: int = Field(ge=1, le=SLOTS)
    title: str = Field(min_length=1, max_length=60)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/meta")
def meta():
    with closing(db()) as conn:
        return {
            "open_hour": OPEN_HOUR, "slots": SLOTS,
            "rooms": [dict(r) for r in conn.execute("SELECT * FROM rooms ORDER BY id")],
            "users": [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id")],
        }


@app.get("/api/bookings")
def list_bookings(day: str):
    parse_day(day)
    with closing(db()) as conn:
        rows = conn.execute(
            """SELECT b.id, b.room_id, b.user_id, b.day, b.start_slot, b.end_slot, b.title,
                      u.name AS user_name, u.dept
               FROM bookings b JOIN users u ON u.id = b.user_id
               WHERE b.day = ? ORDER BY b.start_slot""", (day,)).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/bookings", status_code=201)
def create_booking(b: BookingIn):
    d = parse_day(b.day)
    end = b.start_slot + b.slots
    if end > SLOTS:
        raise HTTPException(400, "운영 시간(9:00~18:00)을 벗어납니다.")
    if d < date.today():
        raise HTTPException(400, "지난 날짜는 예약할 수 없습니다.")
    if d == date.today():
        now = datetime.now()
        if b.start_slot < (now.hour - OPEN_HOUR) * 2 + now.minute // 30:
            raise HTTPException(400, "이미 지난 시간은 예약할 수 없습니다.")
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")  # 동시 예약 경쟁 방지
        if not conn.execute("SELECT 1 FROM rooms WHERE id=?", (b.room_id,)).fetchone():
            raise HTTPException(404, "회의실이 없습니다.")
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (b.user_id,)).fetchone():
            raise HTTPException(404, "사용자가 없습니다.")
        clash = conn.execute(
            "SELECT 1 FROM bookings WHERE room_id=? AND day=? AND start_slot < ? AND end_slot > ?",
            (b.room_id, b.day, end, b.start_slot)).fetchone()
        if clash:
            raise HTTPException(409, "이미 예약된 시간과 겹칩니다.")
        cur = conn.execute(
            "INSERT INTO bookings(room_id,user_id,day,start_slot,end_slot,title) VALUES(?,?,?,?,?,?)",
            (b.room_id, b.user_id, b.day, b.start_slot, end, b.title.strip()))
        conn.commit()
        return {"id": cur.lastrowid}


@app.delete("/api/bookings/{booking_id}")
def cancel_booking(booking_id: int, user_id: int):
    with closing(db()) as conn:
        row = conn.execute("SELECT user_id FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not row:
            raise HTTPException(404, "예약을 찾을 수 없습니다.")
        if row["user_id"] != user_id:
            raise HTTPException(403, "본인의 예약만 취소할 수 있습니다.")
        conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        conn.commit()
        return {"ok": True}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
