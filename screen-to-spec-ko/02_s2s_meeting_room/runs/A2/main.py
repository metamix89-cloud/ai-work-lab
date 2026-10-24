"""다온소프트 회의실 예약 - FastAPI + SQLite"""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "rooms.db"
DAY_START, DAY_END = 9 * 60, 18 * 60  # 분 단위
STEP = 30

ROOMS = [
    (1, "회의실 A", 4, "소규모 미팅 (4인)"),
    (2, "회의실 B", 8, "팀 회의 (8인)"),
    (3, "대회의실", 16, "전체 회의 / 세미나 (16인)"),
]
USERS = ["김민준", "이서연", "박지훈", "최유나", "정도현"]


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, isolation_level=None)  # 수동 트랜잭션
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_hm(s: str) -> int:
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        raise HTTPException(400, "시간 형식은 HH:MM 이어야 합니다.")


def init_db():
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS rooms(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                capacity INTEGER NOT NULL, note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                day TEXT NOT NULL,
                start_min INTEGER NOT NULL,
                end_min INTEGER NOT NULL,
                user TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS idx_res_day ON reservations(day, room_id);
            """
        )
        if con.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            con.executemany("INSERT INTO rooms VALUES(?,?,?,?)", ROOMS)
        if con.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0:
            seed(con)


def seed(con):
    """오늘/내일/모레 기준 가상 예약 데이터."""
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    t = lambda s: parse_hm(s)
    rows = [
        (1, d(0), "09:30", "10:30", "김민준", "주간 스프린트 계획"),
        (1, d(0), "14:00", "15:00", "이서연", "디자인 리뷰"),
        (1, d(0), "16:30", "17:30", "박지훈", "1:1 면담"),
        (2, d(0), "10:00", "12:00", "최유나", "신규 서비스 기획 워크숍"),
        (2, d(0), "13:30", "14:30", "정도현", "고객사 미팅 준비"),
        (3, d(0), "11:00", "12:00", "김민준", "전사 월간 조회"),
        (3, d(0), "15:00", "17:00", "이서연", "신입사원 온보딩 교육"),
        (1, d(1), "10:00", "11:00", "정도현", "QA 회고"),
        (2, d(1), "09:00", "10:30", "박지훈", "아키텍처 설계 회의"),
        (2, d(1), "15:00", "16:00", "김민준", "채용 면접"),
        (3, d(1), "13:00", "15:30", "최유나", "분기 전략 세미나"),
        (1, d(2), "11:30", "12:30", "이서연", "마케팅 아이디어 회의"),
        (3, d(2), "09:30", "11:00", "정도현", "파트너사 데모"),
    ]
    con.executemany(
        "INSERT INTO reservations(room_id,day,start_min,end_min,user,title) VALUES(?,?,?,?,?,?)",
        [(r, day, t(s), t(e), u, ti) for r, day, s, e, u, ti in rows],
    )


app = FastAPI(title="다온소프트 회의실 예약")
init_db()


class NewReservation(BaseModel):
    room_id: int
    day: date
    start: str = Field(examples=["09:00"])
    end: str = Field(examples=["10:00"])
    user: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=50)


@app.get("/api/config")
def config():
    return {
        "day_start": hm(DAY_START),
        "day_end": hm(DAY_END),
        "step": STEP,
        "users": USERS,
        "today": date.today().isoformat(),
    }


@app.get("/api/rooms")
def rooms():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM rooms ORDER BY id")]


@app.get("/api/reservations")
def reservations(day: date = Query(...)):
    with db() as con:
        rows = con.execute(
            "SELECT * FROM reservations WHERE day=? ORDER BY start_min", (day.isoformat(),)
        ).fetchall()
    return [
        {
            "id": r["id"], "room_id": r["room_id"], "day": r["day"],
            "start": hm(r["start_min"]), "end": hm(r["end_min"]),
            "user": r["user"], "title": r["title"],
        }
        for r in rows
    ]


@app.post("/api/reservations", status_code=201)
def create(body: NewReservation):
    s, e = parse_hm(body.start), parse_hm(body.end)
    if s % STEP or e % STEP:
        raise HTTPException(400, "30분 단위로만 예약할 수 있습니다.")
    if not (DAY_START <= s < e <= DAY_END):
        raise HTTPException(400, "예약 가능 시간은 09:00~18:00 입니다.")
    now = datetime.now()
    if datetime.combine(body.day, datetime.min.time()) + timedelta(minutes=s) < now:
        raise HTTPException(400, "이미 지난 시간은 예약할 수 없습니다.")
    title = body.title.strip()
    user = body.user.strip()
    if not title or not user:
        raise HTTPException(400, "예약자와 제목을 입력하세요.")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")  # 동시 예약 경쟁 방지
        try:
            if not con.execute("SELECT 1 FROM rooms WHERE id=?", (body.room_id,)).fetchone():
                raise HTTPException(404, "존재하지 않는 회의실입니다.")
            clash = con.execute(
                "SELECT 1 FROM reservations WHERE room_id=? AND day=? AND start_min<? AND end_min>?",
                (body.room_id, body.day.isoformat(), e, s),
            ).fetchone()
            if clash:
                raise HTTPException(409, "해당 시간에 이미 예약이 있습니다.")
            cur = con.execute(
                "INSERT INTO reservations(room_id,day,start_min,end_min,user,title) VALUES(?,?,?,?,?,?)",
                (body.room_id, body.day.isoformat(), s, e, user, title),
            )
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return {"id": cur.lastrowid}


@app.delete("/api/reservations/{rid}")
def cancel(rid: int, user: str = Query(...)):
    with db() as con:
        row = con.execute("SELECT user FROM reservations WHERE id=?", (rid,)).fetchone()
        if not row:
            raise HTTPException(404, "예약을 찾을 수 없습니다.")
        if row["user"] != user:
            raise HTTPException(403, "본인의 예약만 취소할 수 있습니다.")
        con.execute("DELETE FROM reservations WHERE id=?", (rid,))
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
