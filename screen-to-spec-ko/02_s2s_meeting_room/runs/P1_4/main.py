"""다온소프트 회의실 예약 웹앱 - Phase 1 (F-01 ~ F-06)."""
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "meeting_rooms.db"
STATIC_DIR = BASE_DIR / "static"

DAY_START = "09:00"
DAY_END = "18:00"
MAX_MINUTES = 120
TITLE_MAX = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS mr_users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    dept TEXT
);
CREATE TABLE IF NOT EXISTS mr_rooms (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    capacity INTEGER
);
CREATE TABLE IF NOT EXISTS mr_reservations (
    id INTEGER PRIMARY KEY,
    room_id INTEGER NOT NULL REFERENCES mr_rooms(id),
    user_id INTEGER NOT NULL REFERENCES mr_users(id),
    rsv_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cancelled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mr_rsv_room_date_status
    ON mr_reservations (room_id, rsv_date, status);
"""

# 모두 가상 데이터
SEED_USERS = [
    ("김가온", "개발팀"),
    ("이나래", "디자인팀"),
    ("박다솔", "기획팀"),
    ("최라온", "영업팀"),
    ("정마루", "운영팀"),
]
SEED_ROOMS = [("회의실 A", 4), ("회의실 B", 8), ("회의실 C", 12)]
# (room_id, user_id, start, end, title)
SEED_RESERVATIONS = [
    (2, 1, "09:00", "10:00", "주간회의"),
    (1, 2, "11:00", "12:00", "디자인 리뷰"),
    (3, 3, "13:30", "15:00", "기획 워크숍"),
    (2, 4, "14:00", "15:00", "영업 전략 점검"),
    (1, 5, "16:00", "17:00", "운영 정례 보고"),
]


def now() -> datetime:
    """서버 시계 기준 현재 시각 (테스트에서 교체 가능)."""
    return datetime.now()


def connect() -> sqlite3.Connection:
    # isolation_level=None: 트랜잭션을 직접 BEGIN IMMEDIATE 로 제어한다 (R-09)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM mr_users").fetchone()[0] == 0:
            conn.executemany("INSERT INTO mr_users (name, dept) VALUES (?, ?)", SEED_USERS)
            conn.executemany("INSERT INTO mr_rooms (name, capacity) VALUES (?, ?)", SEED_ROOMS)
            today = now().strftime("%Y-%m-%d")
            stamp = now().strftime("%Y-%m-%d %H:%M:%S")
            conn.executemany(
                "INSERT INTO mr_reservations (room_id, user_id, rsv_date, start_time, end_time,"
                " title, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
                [(r, u, today, s, e, t, stamp) for r, u, s, e, t in SEED_RESERVATIONS],
            )
    finally:
        conn.close()


def to_minutes(hhmm: str) -> int | None:
    """'HH:MM' -> 분. 형식이 틀리거나 30분 단위가 아니면 None."""
    try:
        if len(hhmm) != 5 or hhmm[2] != ":":
            return None
        h, m = int(hhmm[:2]), int(hhmm[3:])
    except (ValueError, TypeError):
        return None
    if not (0 <= h <= 23 and m in (0, 30)):
        return None
    return h * 60 + m


def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


class ReservationIn(BaseModel):
    room_id: int
    user_id: int
    rsv_date: str
    start_time: str
    end_time: str
    title: str


class CancelIn(BaseModel):
    user_id: int


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(title="회의실 예약", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def _http_error(_, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/api/users")
def list_users():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, dept FROM mr_users ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/rooms")
def list_rooms():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, capacity FROM mr_rooms ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/reservations")
def list_reservations(date: str | None = None):
    n = now()
    today = n.strftime("%Y-%m-%d")
    date = date or today
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT r.id, r.room_id, r.user_id, u.name AS user_name, r.rsv_date,"
            " r.start_time, r.end_time, r.title"
            " FROM mr_reservations r JOIN mr_users u ON u.id = r.user_id"
            " WHERE r.rsv_date = ? AND r.status = 'active'"
            " ORDER BY r.room_id, r.start_time",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    # 서버 시각을 함께 내려 화면의 '지난 시간' 판정도 서버 기준으로 맞춘다
    return {
        "date": date,
        "today": today,
        "server_time": n.strftime("%H:%M"),
        "reservations": [dict(r) for r in rows],
    }


@app.post("/api/reservations", status_code=201)
def create_reservation(body: ReservationIn):
    n = now()
    today = n.strftime("%Y-%m-%d")
    title = body.title.strip()

    # --- 입력 검증 (422) ---
    if not title:
        fail(422, "제목을 입력해 주세요.")
    if len(title) > TITLE_MAX:
        fail(422, f"제목은 {TITLE_MAX}자 이하로 입력해 주세요.")
    if body.rsv_date != today:
        fail(422, "오늘 날짜만 예약할 수 있습니다.")
    start, end = to_minutes(body.start_time), to_minutes(body.end_time)
    if start is None or end is None:
        fail(422, "시각은 정각 또는 30분 단위(HH:MM)로 입력해 주세요.")
    if start < to_minutes(DAY_START) or end > to_minutes(DAY_END):
        fail(422, f"예약은 {DAY_START}~{DAY_END} 사이에서만 가능합니다.")
    if end <= start:
        fail(422, "종료 시각은 시작 시각보다 늦어야 합니다.")
    if end - start > MAX_MINUTES:
        fail(422, "한 번에 최대 2시간까지만 예약할 수 있습니다.")
    if start < n.hour * 60 + n.minute:
        fail(422, "이미 지난 시간은 예약할 수 없습니다.")

    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM mr_rooms WHERE id = ?", (body.room_id,)).fetchone() is None:
            fail(422, "존재하지 않는 회의실입니다.")
        if conn.execute("SELECT 1 FROM mr_users WHERE id = ?", (body.user_id,)).fetchone() is None:
            fail(422, "존재하지 않는 사용자입니다.")

        # R-09: 쓰기 락을 먼저 잡고 겹침 검사 + 저장을 한 트랜잭션으로 처리
        conn.execute("BEGIN IMMEDIATE")
        try:
            clash = conn.execute(
                "SELECT title, start_time, end_time FROM mr_reservations"
                " WHERE room_id = ? AND rsv_date = ? AND status = 'active'"
                " AND ? < end_time AND ? > start_time",
                (body.room_id, body.rsv_date, body.start_time, body.end_time),
            ).fetchone()
            if clash:
                conn.execute("ROLLBACK")
                fail(
                    409,
                    f"이미 예약된 시간과 겹칩니다. ({clash['start_time']}~{clash['end_time']} {clash['title']})",
                )
            cur = conn.execute(
                "INSERT INTO mr_reservations (room_id, user_id, rsv_date, start_time, end_time,"
                " title, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
                (body.room_id, body.user_id, body.rsv_date, body.start_time, body.end_time,
                 title, n.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.execute("COMMIT")
        except HTTPException:
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/reservations/{rsv_id}/cancel")
def cancel_reservation(rsv_id: int, body: CancelIn):
    n = now()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT user_id, rsv_date, end_time, status FROM mr_reservations WHERE id = ?",
                (rsv_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                fail(404, "예약을 찾을 수 없습니다.")
            if row["status"] != "active":
                conn.execute("ROLLBACK")
                fail(409, "이미 취소된 예약입니다.")
            if row["user_id"] != body.user_id:
                conn.execute("ROLLBACK")
                fail(403, "본인의 예약만 취소할 수 있습니다.")
            end_at = datetime.strptime(f"{row['rsv_date']} {row['end_time']}", "%Y-%m-%d %H:%M")
            if end_at < n:
                conn.execute("ROLLBACK")
                fail(422, "이미 끝난 예약은 취소할 수 없습니다.")
            conn.execute(
                "UPDATE mr_reservations SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (n.strftime("%Y-%m-%d %H:%M:%S"), rsv_id),
            )
            conn.execute("COMMIT")
        except HTTPException:
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return {"id": rsv_id, "status": "cancelled"}
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
