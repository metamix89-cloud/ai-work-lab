import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB = BASE / "rooms.db"
OPEN_MIN, CLOSE_MIN = 9 * 60, 18 * 60  # 09:00 ~ 18:00
STEP = 30

app = FastAPI(title="다온소프트 회의실 예약")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def init_db():
    with closing(conn()) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS rooms(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                day TEXT NOT NULL, start_min INTEGER NOT NULL, end_min INTEGER NOT NULL,
                user TEXT NOT NULL, title TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_res ON reservations(day, room_id);
            """
        )
        if c.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]:
            return
        c.executemany(
            "INSERT INTO rooms VALUES(?,?,?)",
            [(1, "대회의실 (한강)", 12), (2, "중회의실 (남산)", 6), (3, "소회의실 (북악)", 4)],
        )
        today, tmr = date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()
        seed = [
            (1, today, "09:30", "10:30", "김민준", "주간 전체 회의"),
            (1, today, "14:00", "16:00", "이서연", "신제품 기획 워크숍"),
            (2, today, "10:00", "11:00", "박지호", "백엔드 스프린트 리뷰"),
            (2, today, "13:00", "14:30", "최유진", "고객사 미팅"),
            (3, today, "09:00", "09:30", "정하윤", "1:1 면담"),
            (3, today, "11:00", "12:00", "김민준", "디자인 검토"),
            (3, today, "15:30", "17:00", "강도현", "채용 면접"),
            (1, tmr, "10:00", "12:00", "박지호", "분기 계획 발표"),
            (2, tmr, "14:00", "15:00", "이서연", "QA 회고"),
            (3, tmr, "09:30", "10:30", "최유진", "계약 검토"),
        ]
        c.executemany(
            "INSERT INTO reservations(room_id,day,start_min,end_min,user,title) VALUES(?,?,?,?,?,?)",
            [(r, d, to_min(s), to_min(e), u, t) for r, d, s, e, u, t in seed],
        )
        c.commit()


init_db()


class NewReservation(BaseModel):
    room_id: int
    day: str
    start: str  # HH:MM
    end: str
    title: str


def row_out(r):
    return {
        "id": r["id"], "room_id": r["room_id"], "day": r["day"],
        "start": hhmm(r["start_min"]), "end": hhmm(r["end_min"]),
        "user": r["user"], "title": r["title"],
    }


@app.get("/api/config")
def config():
    return {"open": hhmm(OPEN_MIN), "close": hhmm(CLOSE_MIN), "step": STEP,
            "today": date.today().isoformat(),
            "users": ["김민준", "이서연", "박지호", "최유진", "정하윤", "강도현"]}


@app.get("/api/rooms")
def rooms():
    with closing(conn()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM rooms ORDER BY id")]


@app.get("/api/reservations")
def list_reservations(day: str):
    with closing(conn()) as c:
        rows = c.execute("SELECT * FROM reservations WHERE day=? ORDER BY start_min", (day,))
        return [row_out(r) for r in rows]


def user_of(x_user: str | None) -> str:
    # 데모용 간이 식별: 실제 서비스에서는 로그인/SSO로 대체
    if not x_user:
        raise HTTPException(401, "사용자를 선택하세요")
    from urllib.parse import unquote
    return unquote(x_user)


@app.post("/api/reservations", status_code=201)
def create(body: NewReservation, x_user: str | None = Header(None)):
    user = user_of(x_user)
    try:
        date.fromisoformat(body.day)
        s, e = to_min(body.start), to_min(body.end)
    except ValueError:
        raise HTTPException(400, "날짜/시간 형식이 올바르지 않습니다")
    if not body.title.strip():
        raise HTTPException(400, "회의 제목을 입력하세요")
    if s % STEP or e % STEP or not (OPEN_MIN <= s < e <= CLOSE_MIN):
        raise HTTPException(400, "예약 가능 시간은 09:00~18:00 (30분 단위)입니다")
    with closing(conn()) as c:
        if not c.execute("SELECT 1 FROM rooms WHERE id=?", (body.room_id,)).fetchone():
            raise HTTPException(404, "회의실이 없습니다")
        c.execute("BEGIN IMMEDIATE")
        clash = c.execute(
            "SELECT 1 FROM reservations WHERE room_id=? AND day=? AND start_min<? AND end_min>?",
            (body.room_id, body.day, e, s),
        ).fetchone()
        if clash:
            raise HTTPException(409, "이미 예약된 시간과 겹칩니다")
        cur = c.execute(
            "INSERT INTO reservations(room_id,day,start_min,end_min,user,title) VALUES(?,?,?,?,?,?)",
            (body.room_id, body.day, s, e, user, body.title.strip()[:50]),
        )
        c.commit()
        return row_out(c.execute("SELECT * FROM reservations WHERE id=?", (cur.lastrowid,)).fetchone())


@app.delete("/api/reservations/{rid}")
def cancel(rid: int, x_user: str | None = Header(None)):
    user = user_of(x_user)
    with closing(conn()) as c:
        r = c.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
        if not r:
            raise HTTPException(404, "예약이 없습니다")
        if r["user"] != user:
            raise HTTPException(403, "본인의 예약만 취소할 수 있습니다")
        c.execute("DELETE FROM reservations WHERE id=?", (rid,))
        c.commit()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
