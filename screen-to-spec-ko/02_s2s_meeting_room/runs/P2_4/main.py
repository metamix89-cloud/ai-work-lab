"""다온소프트 회의실 예약 웹앱 - Phase 1 (오늘 하루, 보기 → 예약 → 취소)."""
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
DB_PATH = os.environ.get("MR_DB_PATH", str(BASE_DIR / "meeting_rooms.db"))
KST = timezone(timedelta(hours=9))  # Asia/Seoul (서머타임 없음)

OPEN_MIN = 9 * 60
CLOSE_MIN = 18 * 60
MAX_MIN = 120

TIME_RE = re.compile(r"^(\d{2}):(\d{2})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MSG_INPUT = "입력값을 확인해 주세요."


def now_kst() -> datetime:
    """서버 현재 시각(KST). 테스트용으로 MR_FAKE_NOW='YYYY-MM-DD HH:MM[:SS]' 지정 가능."""
    fake = os.environ.get("MR_FAKE_NOW")
    if fake:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(fake, fmt).replace(tzinfo=KST)
            except ValueError:
                pass
    return datetime.now(KST)


def hhmm_to_min(s: str) -> int:
    return int(s[:2]) * 60 + int(s[3:])


def min_to_hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(
            """
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
        )
        if conn.execute("SELECT COUNT(*) FROM mr_users").fetchone()[0] == 0:
            seed(conn)
    finally:
        conn.close()


def seed(conn: sqlite3.Connection) -> None:
    """가상 데이터. 서버를 띄운 시각과 무관하게 오늘 09:00~18:00 안, 겹침 없음."""
    users = [
        ("김가온", "개발팀"),
        ("이나래", "디자인팀"),
        ("박다온", "영업팀"),
        ("최라온", "인사팀"),
        ("정마루", "기획팀"),
    ]
    rooms = [("회의실 A", 4), ("회의실 B", 8), ("회의실 C", 12)]
    conn.executemany("INSERT INTO mr_users (name, dept) VALUES (?, ?)", users)
    conn.executemany("INSERT INTO mr_rooms (name, capacity) VALUES (?, ?)", rooms)
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    rsvs = [
        (2, 1, "09:00", "10:00", "주간회의"),
        (1, 2, "10:30", "12:00", "디자인 리뷰"),
        (3, 3, "13:00", "14:00", "고객사 미팅"),
        (2, 4, "14:00", "15:30", "채용 면접"),
        (1, 5, "16:00", "17:00", "기획 브레인스토밍"),
    ]
    conn.executemany(
        "INSERT INTO mr_reservations (room_id, user_id, rsv_date, start_time, end_time,"
        " title, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
        [(r, u, today, s, e, t, stamp) for r, u, s, e, t in rsvs],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="회의실 예약", lifespan=lifespan)


def err(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": MSG_INPUT})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "일시적인 오류입니다. 잠시 후 다시 시도해 주세요."},
    )


class ReservationIn(BaseModel):
    user_id: Optional[Any] = None
    room_id: Optional[Any] = None
    rsv_date: Optional[Any] = None
    start_time: Optional[Any] = None
    end_time: Optional[Any] = None
    title: Optional[Any] = None


class CancelIn(BaseModel):
    user_id: Optional[Any] = None


def as_int(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(422, MSG_INPUT)
    return v


def valid_time(v: Any) -> int:
    """'HH:MM' 형식이면 분 단위로 변환, 아니면 422."""
    if not isinstance(v, str):
        raise err(422, MSG_INPUT)
    m = TIME_RE.match(v)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise err(422, MSG_INPUT)
    return int(m.group(1)) * 60 + int(m.group(2))


def valid_date(v: Any) -> str:
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise err(422, MSG_INPUT)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise err(422, MSG_INPUT)
    return v


SELECT_RSV = (
    "SELECT r.id, r.room_id, r.user_id, u.name AS user_name, r.rsv_date, r.start_time,"
    " r.end_time, r.title, r.status, r.created_at, r.cancelled_at"
    " FROM mr_reservations r JOIN mr_users u ON u.id = r.user_id"
)


@app.get("/api/now")
def api_now():
    n = now_kst()
    return {"date": n.strftime("%Y-%m-%d"), "time": n.strftime("%H:%M")}


@app.get("/api/users")
def api_users():
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, dept FROM mr_users ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/rooms")
def api_rooms():
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, capacity FROM mr_rooms ORDER BY id")]
    finally:
        conn.close()


@app.get("/api/reservations")
def api_reservations(date: Optional[str] = None):
    d = valid_date(date) if date is not None else now_kst().strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        rows = conn.execute(
            SELECT_RSV + " WHERE r.rsv_date = ? AND r.status = 'active' ORDER BY r.start_time, r.id",
            (d,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/reservations", status_code=201)
def api_create(body: ReservationIn):
    # ① 입력 형식·누락
    user_id = as_int(body.user_id)
    room_id = as_int(body.room_id)
    rsv_date = valid_date(body.rsv_date)
    start = valid_time(body.start_time)
    end = valid_time(body.end_time)
    if not isinstance(body.title, str):
        raise err(422, MSG_INPUT)
    title = body.title.strip()

    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute

    conn = get_conn()
    try:
        # ② 사용자·회의실 존재 여부
        if conn.execute("SELECT 1 FROM mr_users WHERE id = ?", (user_id,)).fetchone() is None:
            raise err(403, "사용자를 확인할 수 없습니다. 이름을 다시 선택해 주세요.")
        if conn.execute("SELECT 1 FROM mr_rooms WHERE id = ?", (room_id,)).fetchone() is None:
            raise err(404, "회의실을 찾을 수 없습니다.")

        # ③ 업무 규칙 (R-10, R-05, R-01, R-02, R-08, R-04)
        if rsv_date != today:
            raise err(422, "오늘 날짜만 예약할 수 있습니다.")
        if not title:
            raise err(422, "제목을 입력해 주세요.")
        if len(title) > 30:
            raise err(422, "제목은 30자 이하로 입력해 주세요.")
        if (
            not (OPEN_MIN <= start <= CLOSE_MIN - 30)
            or not (OPEN_MIN + 30 <= end <= CLOSE_MIN)
            or start % 30
            or end % 30
        ):
            raise err(422, "예약은 09:00~18:00 사이, 30분 단위로만 가능합니다.")
        if end <= start:
            raise err(422, "종료 시각은 시작 시각보다 늦어야 합니다.")
        if end - start > MAX_MIN:
            raise err(422, "한 번에 최대 2시간까지 예약할 수 있습니다.")
        if start < now_min:
            raise err(422, "이미 지난 시간은 예약할 수 없습니다.")

        start_s, end_s = min_to_hhmm(start), min_to_hhmm(end)

        # ④ 겹침 검사 + 저장을 한 트랜잭션에서 (R-03, R-09)
        conn.execute("BEGIN IMMEDIATE")
        try:
            clash = conn.execute(
                "SELECT 1 FROM mr_reservations WHERE room_id = ? AND rsv_date = ?"
                " AND status = 'active' AND ? < end_time AND ? > start_time",
                (room_id, rsv_date, start_s, end_s),
            ).fetchone()
            if clash:
                conn.execute("ROLLBACK")
                raise err(409, "이미 예약된 시간입니다. 다른 시간을 선택해 주세요.")
            cur = conn.execute(
                "INSERT INTO mr_reservations (room_id, user_id, rsv_date, start_time, end_time,"
                " title, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
                (room_id, user_id, rsv_date, start_s, end_s, title,
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )
            new_id = cur.lastrowid
            conn.execute("COMMIT")
        except HTTPException:
            raise
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return dict(conn.execute(SELECT_RSV + " WHERE r.id = ?", (new_id,)).fetchone())
    finally:
        conn.close()


@app.post("/api/reservations/{rsv_id}/cancel")
def api_cancel(rsv_id: int, body: CancelIn):
    user_id = as_int(body.user_id)
    now = now_kst()
    now_min = now.hour * 60 + now.minute
    today = now.strftime("%Y-%m-%d")

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM mr_reservations WHERE id = ?", (rsv_id,)
            ).fetchone()
            if row is None:
                raise err(404, "예약을 찾을 수 없습니다.")
            if row["user_id"] != user_id:
                raise err(403, "본인의 예약만 취소할 수 있습니다.")
            if row["status"] == "cancelled":
                raise err(409, "이미 취소된 예약입니다.")
            # 종료 시각 <= 현재 → 이미 끝남 (지난 날짜 예약도 포함)
            if row["rsv_date"] < today or (
                row["rsv_date"] == today and hhmm_to_min(row["end_time"]) <= now_min
            ):
                raise err(409, "이미 끝난 예약은 취소할 수 없습니다.")
            conn.execute(
                "UPDATE mr_reservations SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (now.strftime("%Y-%m-%d %H:%M:%S"), rsv_id),
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return dict(conn.execute(SELECT_RSV + " WHERE r.id = ?", (rsv_id,)).fetchone())
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
