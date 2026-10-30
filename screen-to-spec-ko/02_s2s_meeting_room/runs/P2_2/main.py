import os
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("RSV_DB", os.path.join(BASE_DIR, "reservations.db"))
KST = timezone(timedelta(hours=9))
SLOTS = 18
MAX_LEN = 8

MSG_USER = "사용자를 확인할 수 없습니다."
MSG_TIME = "예약할 수 없는 시간입니다. (09:00~18:00, 30분 단위, 오늘만 가능)"
MSG_LEN = "예약은 30분 이상 4시간 이하로 해 주세요."
MSG_TITLE = "제목은 1~30자로 입력해 주세요."
MSG_PAST = "이미 지난 시간에는 예약할 수 없습니다."
MSG_ROOM = "존재하지 않는 회의실입니다."
MSG_FORBIDDEN = "본인이 만든 예약만 취소할 수 있습니다."
MSG_NOT_FOUND = "예약을 찾을 수 없습니다."
MSG_OVERLAP = "이미 예약된 시간입니다."
MSG_CANCEL_PAST = "이미 시작했거나 지난 예약은 취소할 수 없습니다."
MSG_CANCELED = "이미 취소된 예약입니다."
MSG_SERVER = "처리 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요."


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def now_kst():
    """서버 KST 현재 시각 (테스트에서 교체 가능)."""
    return datetime.now(KST).replace(tzinfo=None)


def past_slots(now):
    """슬롯 i 는 i < past_slots 이면 지난(이미 시작한) 칸. 칸 시작 시각 <= 현재."""
    s = now.hour * 3600 + now.minute * 60 + now.second - 9 * 3600
    if s < 0:
        return 0
    return min(SLOTS, s // 1800 + 1)


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rsv_user (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rsv_room (
                room_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rsv_booking (
                booking_id INTEGER PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES rsv_room(room_id),
                user_id INTEGER NOT NULL REFERENCES rsv_user(user_id),
                book_date TEXT NOT NULL,
                start_slot INTEGER NOT NULL,
                end_slot INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK (start_slot < end_slot)
            );
            CREATE INDEX IF NOT EXISTS rsv_booking_day
                ON rsv_booking (book_date, room_id, status);
            """
        )
        if conn.execute("SELECT COUNT(*) FROM rsv_user").fetchone()[0] == 0:
            seed(conn)
    finally:
        conn.close()


def seed(conn):
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("BEGIN IMMEDIATE")
    conn.executemany(
        "INSERT INTO rsv_user (user_id, name) VALUES (?, ?)",
        [(i, f"사용자{c}") for i, c in enumerate("ABCDE", 1)],
    )
    conn.executemany(
        "INSERT INTO rsv_room (room_id, name) VALUES (?, ?)",
        [(i, f"회의실 {i}") for i in (1, 2, 3)],
    )
    nxt = past_slots(now)  # 지금 이후 첫 예약 가능 칸
    rows = [
        (1, 1, 0, 2, "주간 업무 점검"),
        (2, 2, 1, 3, "디자인 리뷰"),
        (1, 2, nxt + 1, nxt + 3, "신규 기능 논의"),
        (3, 3, nxt + 2, nxt + 3, "면담"),
    ]
    for room, user, s, e, title in rows:
        if e <= SLOTS:
            conn.execute(
                "INSERT INTO rsv_booking (room_id, user_id, book_date, start_slot,"
                " end_slot, title, status, created_at) VALUES (?,?,?,?,?,?,'ACTIVE',?)",
                (room, user, today, s, e, title, stamp),
            )
    conn.execute("COMMIT")


BOOKING_SELECT = (
    "SELECT b.*, u.name AS user_name FROM rsv_booking b"
    " JOIN rsv_user u ON u.user_id = b.user_id"
)


def booking_dict(row):
    return {
        k: row[k]
        for k in ("booking_id", "room_id", "user_id", "user_name", "book_date",
                  "start_slot", "end_slot", "title", "status")
    }


def require_user(conn, request):
    raw = request.headers.get("X-User-Id")
    if raw is None or not raw.strip().isdigit():
        raise ApiError(400, MSG_USER)
    row = conn.execute(
        "SELECT user_id FROM rsv_user WHERE user_id = ?", (int(raw),)
    ).fetchone()
    if row is None:
        raise ApiError(400, MSG_USER)
    return row["user_id"]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def rollback_on_error(conn):
    if conn.in_transaction:
        conn.execute("ROLLBACK")


app = FastAPI(title="회의실 예약")
init_db()


@app.exception_handler(ApiError)
async def api_error_handler(request, exc):
    return JSONResponse({"message": exc.message}, status_code=exc.status)


@app.exception_handler(Exception)
async def unexpected_handler(request, exc):
    return JSONResponse({"message": MSG_SERVER}, status_code=500)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/api/users")
def list_users():
    conn = connect()
    try:
        rows = conn.execute("SELECT user_id, name FROM rsv_user ORDER BY user_id")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/timetable")
def timetable():
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    conn = connect()
    try:
        rooms = [
            dict(r)
            for r in conn.execute("SELECT room_id, name FROM rsv_room ORDER BY room_id")
        ]
        rows = conn.execute(
            BOOKING_SELECT + " WHERE b.book_date = ? AND b.status = 'ACTIVE'"
            " ORDER BY b.room_id, b.start_slot",
            (today,),
        )
        return {
            "date": today,
            "past_slots": past_slots(now),
            "rooms": rooms,
            "bookings": [booking_dict(r) for r in rows],
        }
    finally:
        conn.close()


@app.post("/api/bookings", status_code=201)
async def create_booking(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        body = {}
    conn = connect()
    try:
        user_id = require_user(conn, request)
        room_id = body.get("room_id")
        room = None
        if is_int(room_id):
            room = conn.execute(
                "SELECT room_id FROM rsv_room WHERE room_id = ?", (room_id,)
            ).fetchone()
        if room is None:
            raise ApiError(400, MSG_ROOM)

        now = now_kst()
        today = now.strftime("%Y-%m-%d")
        start, end = body.get("start_slot"), body.get("end_slot")
        if (
            not is_int(start)
            or not is_int(end)
            or not (0 <= start <= SLOTS - 1)
            or not (1 <= end <= SLOTS)
            or start >= end
            or body.get("book_date") != today
        ):
            raise ApiError(400, MSG_TIME)
        if not (1 <= end - start <= MAX_LEN):
            raise ApiError(400, MSG_LEN)
        title = body.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if not (1 <= len(title) <= 30):
            raise ApiError(400, MSG_TITLE)
        if start < past_slots(now):
            raise ApiError(400, MSG_PAST)

        conn.execute("BEGIN IMMEDIATE")
        try:
            clash = conn.execute(
                "SELECT 1 FROM rsv_booking WHERE room_id = ? AND book_date = ?"
                " AND status = 'ACTIVE' AND ? < end_slot AND start_slot < ?",
                (room_id, today, start, end),
            ).fetchone()
            if clash:
                raise ApiError(409, MSG_OVERLAP)
            cur = conn.execute(
                "INSERT INTO rsv_booking (room_id, user_id, book_date, start_slot,"
                " end_slot, title, status, created_at) VALUES (?,?,?,?,?,?,'ACTIVE',?)",
                (room_id, user_id, today, start, end, title,
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.execute("COMMIT")
        except BaseException:
            rollback_on_error(conn)
            raise
        row = conn.execute(
            BOOKING_SELECT + " WHERE b.booking_id = ?", (cur.lastrowid,)
        ).fetchone()
        return booking_dict(row)
    finally:
        conn.close()


@app.post("/api/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, request: Request):
    conn = connect()
    try:
        user_id = require_user(conn, request)
        bid = int(booking_id) if booking_id.isdigit() else -1
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                BOOKING_SELECT + " WHERE b.booking_id = ?", (bid,)
            ).fetchone()
            if row is None:
                raise ApiError(404, MSG_NOT_FOUND)
            if row["user_id"] != user_id:
                raise ApiError(403, MSG_FORBIDDEN)
            now = now_kst()
            today = now.strftime("%Y-%m-%d")
            started = row["book_date"] < today or (
                row["book_date"] == today and row["start_slot"] < past_slots(now)
            )
            if started:
                raise ApiError(409, MSG_CANCEL_PAST)
            if row["status"] == "CANCELED":
                raise ApiError(409, MSG_CANCELED)
            conn.execute(
                "UPDATE rsv_booking SET status = 'CANCELED' WHERE booking_id = ?",
                (bid,),
            )
            conn.execute("COMMIT")
        except BaseException:
            rollback_on_error(conn)
            raise
        row = conn.execute(
            BOOKING_SELECT + " WHERE b.booking_id = ?", (bid,)
        ).fetchone()
        return booking_dict(row)
    finally:
        conn.close()
