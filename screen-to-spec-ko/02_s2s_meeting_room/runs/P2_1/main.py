import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("MR_DB_PATH", os.path.join(BASE_DIR, "meeting_rooms.db"))
KST = ZoneInfo("Asia/Seoul")

SLOTS = [f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 30)]  # 09:00 ~ 17:30
ROOMS = ["A", "B", "C"]
USERS = ["김가온", "이서연", "박도윤", "최하준", "정서윤", "강지호", "윤나래", "한시우"]

MSG_BAD = "잘못된 요청입니다."
MSG_NOT_FOUND = "요청한 정보를 찾을 수 없습니다."
MSG_CONFLICT = "이미 다른 사람이 예약한 시간입니다."
MSG_PAST_RSV = "이미 지난 시간은 예약할 수 없습니다."
MSG_FORBIDDEN = "본인이 만든 예약만 취소할 수 있습니다."
MSG_PAST_CANCEL = "이미 시작했거나 지난 예약은 취소할 수 없습니다."
MSG_CANCELLED = "이미 취소된 예약입니다."


def now_kst() -> datetime:
    """서버 시각(KST). 테스트에서 교체 가능."""
    return datetime.now(KST).replace(tzinfo=None)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
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
            conn.executemany("INSERT INTO mr_rooms (name) VALUES (?)", [(n,) for n in ROOMS])
        if conn.execute("SELECT COUNT(*) FROM mr_users").fetchone()[0] == 0:
            conn.executemany("INSERT INTO mr_users (name) VALUES (?)", [(n,) for n in USERS])
        conn.commit()
    finally:
        conn.close()


app = FastAPI(title="회의실 예약", docs_url=None, redoc_url=None, openapi_url=None)
init_db()


def err(status: int, msg: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": msg})


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return err(400, MSG_BAD)


@app.exception_handler(StarletteHTTPException)
async def on_http_error(request: Request, exc: StarletteHTTPException):
    return err(exc.status_code, exc.detail if isinstance(exc.detail, str) else MSG_BAD)


class ReservationIn(BaseModel):
    room_id: int
    user_id: int
    slot_start: str


@app.get("/api/now")
def api_now():
    n = now_kst()
    return {"date": n.strftime("%Y-%m-%d"), "time": n.strftime("%H:%M:%S")}


@app.get("/api/rooms")
def api_rooms():
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name FROM mr_rooms ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/users")
def api_users():
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name FROM mr_users ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/reservations")
def api_list(date: str | None = None):
    today = now_kst().strftime("%Y-%m-%d")
    if date is None:
        date = today
    if date != today:  # Phase 1: 오늘만
        return err(400, MSG_BAD)
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT r.id, r.room_id, r.user_id, u.name AS user_name,
                      r.rsv_date, r.slot_start
               FROM mr_reservations r JOIN mr_users u ON u.id = r.user_id
               WHERE r.rsv_date = ? AND r.status = 'active'
               ORDER BY r.slot_start, r.room_id""",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/reservations", status_code=201)
def api_create(body: ReservationIn):
    if body.slot_start not in SLOTS:  # 09:00~17:30, 30분 단위
        return err(400, MSG_BAD)
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM mr_rooms WHERE id = ?", (body.room_id,)).fetchone():
            return err(404, MSG_NOT_FOUND)
        if not conn.execute("SELECT 1 FROM mr_users WHERE id = ?", (body.user_id,)).fetchone():
            return err(404, MSG_NOT_FOUND)
        now = now_kst()
        today = now.strftime("%Y-%m-%d")
        slot_dt = datetime.strptime(f"{today} {body.slot_start}", "%Y-%m-%d %H:%M")
        if slot_dt <= now:
            return err(422, MSG_PAST_RSV)
        try:
            cur = conn.execute(
                """INSERT INTO mr_reservations
                   (room_id, user_id, rsv_date, slot_start, status, created_at)
                   VALUES (?, ?, ?, ?, 'active', ?)""",
                (body.room_id, body.user_id, today, body.slot_start,
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return err(409, MSG_CONFLICT)
        return {
            "id": cur.lastrowid, "room_id": body.room_id, "user_id": body.user_id,
            "rsv_date": today, "slot_start": body.slot_start,
        }
    finally:
        conn.close()


@app.delete("/api/reservations/{rsv_id}")
def api_cancel(rsv_id: int, user_id: int):
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM mr_users WHERE id = ?", (user_id,)).fetchone():
            return err(404, MSG_NOT_FOUND)
        row = conn.execute("SELECT * FROM mr_reservations WHERE id = ?", (rsv_id,)).fetchone()
        if not row:
            return err(404, MSG_NOT_FOUND)
        if row["user_id"] != user_id:
            return err(403, MSG_FORBIDDEN)
        if row["status"] == "cancelled":
            return err(409, MSG_CANCELLED)
        now = now_kst()
        slot_dt = datetime.strptime(f"{row['rsv_date']} {row['slot_start']}", "%Y-%m-%d %H:%M")
        if slot_dt <= now:
            return err(422, MSG_PAST_CANCEL)
        cur = conn.execute(
            "UPDATE mr_reservations SET status = 'cancelled', cancelled_at = ? "
            "WHERE id = ? AND status = 'active'",
            (now.strftime("%Y-%m-%d %H:%M:%S"), rsv_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return err(409, MSG_CANCELLED)
        return {"id": rsv_id, "status": "cancelled"}
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
