"""다온소프트 회의실 예약 웹앱 (Phase 1). FastAPI + SQLite + 순수 HTML/JS."""
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE_DIR = Path(__file__).parent
DB_PATH = os.environ.get("MR_DB_PATH", str(BASE_DIR / "meetingroom.db"))

DAY_START, DAY_END = 9 * 60, 18 * 60  # 분 단위
TIME_RE = re.compile(r"^(\d{2}):(\d{2})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now() -> datetime:
    """서버 로컬(KST) 현재 시각, 분 단위 내림. 테스트에서 교체 가능."""
    return datetime.now().replace(second=0, microsecond=0)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)  # 트랜잭션 수동 제어
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mr_users (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mr_rooms (
                room_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS mr_reservations (
                reservation_id INTEGER PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES mr_rooms(room_id),
                user_id INTEGER NOT NULL REFERENCES mr_users(user_id),
                rsv_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mr_rsv_room_date
                ON mr_reservations (room_id, rsv_date);
            """
        )
        conn.execute("BEGIN IMMEDIATE")
        empty = (
            conn.execute("SELECT COUNT(*) FROM mr_users").fetchone()[0] == 0
            and conn.execute("SELECT COUNT(*) FROM mr_rooms").fetchone()[0] == 0
        )
        if empty:  # 최초 실행 때만 가상 데이터 적재
            conn.executemany(
                "INSERT INTO mr_users (user_id, name) VALUES (?, ?)",
                [(1, "김하늘"), (2, "이서준"), (3, "박지우"), (4, "최민서"), (5, "정도윤")],
            )
            conn.executemany(
                "INSERT INTO mr_rooms (room_id, name) VALUES (?, ?)",
                [(1, "회의실 A"), (2, "회의실 B"), (3, "회의실 C")],
            )
            today = now().strftime("%Y-%m-%d")
            stamp = now().strftime("%Y-%m-%d %H:%M:%S")
            conn.executemany(
                "INSERT INTO mr_reservations (room_id, user_id, rsv_date, start_time,"
                " end_time, title, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (1, 1, today, "09:30", "10:30", "주간 업무 회의", stamp),
                    (1, 2, today, "13:00", "14:30", "신규 기능 기획", stamp),
                    (2, 3, today, "11:00", "12:00", "디자인 리뷰", stamp),
                    (2, 4, today, "14:00", "15:00", "고객사 미팅", stamp),
                    (3, 5, today, "16:00", "17:30", "분기 계획 워크숍", stamp),
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


class Reject(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


def parse_time(value) -> int | None:
    """'HH:MM' → 분. 형식 오류면 None."""
    if not isinstance(value, str):
        return None
    m = TIME_RE.match(value)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def validate_and_insert(conn: sqlite3.Connection, body: dict) -> dict:
    """R-12 순서로 검사 후 저장. 호출 측이 트랜잭션을 연다."""
    # R-11 사용자 · 회의실
    user_id, room_id = body.get("user_id"), body.get("room_id")
    if (
        not isinstance(user_id, int) or isinstance(user_id, bool)
        or not conn.execute("SELECT 1 FROM mr_users WHERE user_id=?", (user_id,)).fetchone()
    ):
        raise Reject(422, "사용자를 선택해 주세요.")
    if (
        not isinstance(room_id, int) or isinstance(room_id, bool)
        or not conn.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (room_id,)).fetchone()
    ):
        raise Reject(422, "존재하지 않는 회의실입니다.")

    # R-10 오늘만
    current = now()
    rsv_date = body.get("rsv_date")
    if (
        not isinstance(rsv_date, str)
        or not DATE_RE.match(rsv_date)
        or rsv_date != current.strftime("%Y-%m-%d")
    ):
        raise Reject(422, "오늘 날짜만 예약할 수 있습니다.")

    # R-01 단위 · 범위
    start, end = parse_time(body.get("start_time")), parse_time(body.get("end_time"))
    if (
        start is None or end is None
        or start % 30 or end % 30
        or start < DAY_START or end > DAY_END
        or end <= start
    ):
        raise Reject(422, "예약은 09:00~18:00 사이 30분 단위로만 가능합니다.")

    # R-04 길이
    if not 30 <= end - start <= 120:
        raise Reject(422, "예약 시간은 30분 이상 2시간 이하여야 합니다.")

    # R-05 제목
    title = body.get("title")
    title = title.strip() if isinstance(title, str) else ""
    if not title:
        raise Reject(422, "제목을 입력해 주세요.")
    if len(title) > 50:
        raise Reject(422, "제목은 50자 이하로 입력해 주세요.")

    # R-03 이미 시작한 시간
    if start < current.hour * 60 + current.minute:
        raise Reject(422, "이미 지난 시간은 예약할 수 없습니다.")

    # R-02 겹침 ([시작, 종료) 구간). HH:MM 고정폭이라 문자열 비교가 시간순과 같다.
    clash = conn.execute(
        "SELECT 1 FROM mr_reservations WHERE room_id=? AND rsv_date=?"
        " AND start_time < ? AND end_time > ?",
        (room_id, rsv_date, fmt(end), fmt(start)),
    ).fetchone()
    if clash:
        raise Reject(409, "이미 예약된 시간과 겹칩니다.")

    created_at = current.strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO mr_reservations (room_id, user_id, rsv_date, start_time, end_time,"
        " title, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (room_id, user_id, rsv_date, fmt(start), fmt(end), title, created_at),
    )
    return {
        "reservation_id": cur.lastrowid,
        "room_id": room_id,
        "user_id": user_id,
        "rsv_date": rsv_date,
        "start_time": fmt(start),
        "end_time": fmt(end),
        "title": title,
        "created_at": created_at,
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="회의실 예약", lifespan=lifespan)


@app.exception_handler(Reject)
async def _reject_handler(request: Request, exc: Reject):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    return JSONResponse(
        {"detail": "처리 중 오류가 발생했습니다. 잠시 후 다시 시도하세요."}, status_code=500
    )


@app.get("/api/timetable")
def timetable():
    current = now()
    today = current.strftime("%Y-%m-%d")
    conn = connect()
    try:
        users = [dict(r) for r in conn.execute("SELECT user_id, name FROM mr_users ORDER BY user_id")]
        rooms = [dict(r) for r in conn.execute("SELECT room_id, name FROM mr_rooms ORDER BY room_id")]
        reservations = [
            dict(r)
            for r in conn.execute(
                "SELECT r.reservation_id, r.room_id, r.user_id, u.name AS user_name,"
                " r.rsv_date, r.start_time, r.end_time, r.title"
                " FROM mr_reservations r JOIN mr_users u ON u.user_id = r.user_id"
                " WHERE r.rsv_date=? ORDER BY r.start_time",
                (today,),
            )
        ]
    finally:
        conn.close()
    return {
        "date": today,
        "now": current.strftime("%Y-%m-%d %H:%M"),
        "users": users,
        "rooms": rooms,
        "reservations": reservations,
    }


@app.post("/api/reservations", status_code=201)
async def create_reservation(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise Reject(422, "사용자를 선택해 주세요.")
    return _create(body)


def _create(body: dict) -> dict:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")  # 검사와 저장을 한 트랜잭션에서 (R-08)
        try:
            result = validate_and_insert(conn, body)
            conn.execute("COMMIT")
            return result
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


@app.delete("/api/reservations/{reservation_id}")
def cancel_reservation(reservation_id: int, user_id: int | None = None):
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT user_id, rsv_date, end_time FROM mr_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise Reject(404, "예약을 찾을 수 없습니다. 이미 취소되었을 수 있습니다.")
            if user_id != row["user_id"]:  # R-06
                raise Reject(403, "본인의 예약만 취소할 수 있습니다.")
            current = now()
            end_dt = datetime.strptime(f"{row['rsv_date']} {row['end_time']}", "%Y-%m-%d %H:%M")
            if end_dt <= current:  # R-07
                raise Reject(409, "이미 종료된 예약은 취소할 수 없습니다.")
            conn.execute("DELETE FROM mr_reservations WHERE reservation_id=?", (reservation_id,))
            conn.execute("COMMIT")
            return {"reservation_id": reservation_id, "status": "cancelled"}
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")
