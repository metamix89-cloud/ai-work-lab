"""다온소프트 회의실 예약 웹앱 — Phase 1 (PRD.md)"""
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

BASE = Path(__file__).parent
DB_PATH = os.environ.get("RR_DB", str(BASE / "rr.db"))
KST = timezone(timedelta(hours=9))

SLOTS = [f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 30)]  # 09:00~17:30, 18칸
SLOT_RE = re.compile(r"^\d{2}:\d{2}$")

app = FastAPI(title="다온소프트 회의실 예약")


def now_kst() -> datetime:
    # 테스트용: RR_FAKE_NOW="YYYY-MM-DD HH:MM:SS" 로 서버 시각을 고정할 수 있다.
    fake = os.environ.get("RR_FAKE_NOW")
    if fake:
        return datetime.strptime(fake, "%Y-%m-%d %H:%M:%S")
    return datetime.now(KST).replace(tzinfo=None)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rr_user (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rr_room (
                room_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS rr_reservation (
                reservation_id INTEGER PRIMARY KEY,
                room_id INTEGER NOT NULL REFERENCES rr_room(room_id),
                user_id INTEGER NOT NULL REFERENCES rr_user(user_id),
                rsv_date TEXT NOT NULL,
                slot_start TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_rr_active_slot
                ON rr_reservation (room_id, rsv_date, slot_start)
                WHERE status = 'active';
            """
        )
        empty = all(
            conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
            for t in ("rr_user", "rr_room", "rr_reservation")
        )
        if empty:
            conn.executemany(
                "INSERT INTO rr_user (user_id, name) VALUES (?, ?)",
                [(1, "김다온"), (2, "이소프트"), (3, "박예약"), (4, "최회의"), (5, "정시간")],
            )
            conn.executemany(
                "INSERT INTO rr_room (room_id, name) VALUES (?, ?)",
                [(1, "회의실 A"), (2, "회의실 B"), (3, "회의실 C")],
            )
            now = now_kst()
            today = now.strftime("%Y-%m-%d")
            created = now.strftime("%Y-%m-%d %H:%M:%S")
            demo = [
                (2, 3, "09:00"), (2, 3, "09:30"), (2, 3, "10:00"),
                (1, 2, "14:00"), (1, 2, "14:30"),
                (3, 1, "17:30"),
                (3, 4, "11:00"),
            ]
            conn.executemany(
                "INSERT INTO rr_reservation (room_id, user_id, rsv_date, slot_start, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(r, u, today, s, created) for r, u, s in demo],
            )
    finally:
        conn.close()


init_db()


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "사용자를 확인할 수 없습니다"}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    return JSONResponse(
        {"detail": "서버 오류가 발생했습니다. 잠시 후 다시 시도하세요"}, status_code=500
    )


def check_user(conn: sqlite3.Connection, user_id) -> int:
    """E-07: user_id 가 없거나 rr_user 에 없으면 422."""
    try:
        uid = int(user_id)
        if isinstance(user_id, bool):
            raise ValueError
    except (TypeError, ValueError):
        raise ApiError(422, "사용자를 확인할 수 없습니다")
    if conn.execute("SELECT 1 FROM rr_user WHERE user_id=?", (uid,)).fetchone() is None:
        raise ApiError(422, "사용자를 확인할 수 없습니다")
    return uid


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.get("/api/users")
def users():
    conn = connect()
    try:
        rows = conn.execute("SELECT user_id, name FROM rr_user ORDER BY user_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/timetable")
def timetable(date: str | None = None):
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    if date is not None and date != today:
        raise ApiError(422, "오늘 날짜만 조회할 수 있습니다")
    conn = connect()
    try:
        rooms = conn.execute("SELECT room_id, name FROM rr_room ORDER BY room_id").fetchall()
        out = []
        for room in rooms:
            rows = conn.execute(
                "SELECT r.reservation_id, r.room_id, r.slot_start, r.user_id, u.name"
                " FROM rr_reservation r JOIN rr_user u ON u.user_id = r.user_id"
                " WHERE r.room_id=? AND r.rsv_date=? AND r.status='active'"
                " ORDER BY r.slot_start",
                (room["room_id"], today),
            ).fetchall()
            out.append(
                {"room_id": room["room_id"], "name": room["name"],
                 "reservations": [dict(r) for r in rows]}
            )
        return {
            "date": today,
            "now": now.strftime("%H:%M:%S"),
            "slots": SLOTS,
            "rooms": out,
        }
    finally:
        conn.close()


@app.post("/api/reservations", status_code=201)
async def create_reservation(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except Exception:
        body = {}
    conn = connect()
    try:
        # BEGIN IMMEDIATE: R-09 검사와 INSERT 사이에 다른 쓰기가 끼어들지 못하게 직렬화
        conn.execute("BEGIN IMMEDIATE")
        try:
            uid = check_user(conn, body.get("user_id"))

            slot = body.get("slot_start")
            if not isinstance(slot, str) or not SLOT_RE.match(slot) or slot not in SLOTS:
                raise ApiError(422, "예약할 수 없는 시간입니다 (09:00~17:30, 30분 단위)")

            room_id = body.get("room_id")
            room = None
            if isinstance(room_id, int) and not isinstance(room_id, bool):
                room = conn.execute(
                    "SELECT room_id FROM rr_room WHERE room_id=?", (room_id,)
                ).fetchone()
            if room is None:
                raise ApiError(422, "존재하지 않는 회의실입니다")

            now = now_kst()
            today = now.strftime("%Y-%m-%d")
            if slot <= now.strftime("%H:%M:%S"):
                raise ApiError(422, "지난 시간은 예약할 수 없습니다")

            if conn.execute(
                "SELECT 1 FROM rr_reservation WHERE room_id=? AND rsv_date=?"
                " AND slot_start=? AND status='active'",
                (room_id, today, slot),
            ).fetchone():
                raise ApiError(409, "이미 예약된 시간입니다")

            if conn.execute(
                "SELECT 1 FROM rr_reservation WHERE user_id=? AND rsv_date=?"
                " AND slot_start=? AND status='active'",
                (uid, today, slot),
            ).fetchone():
                raise ApiError(409, "같은 시간에 다른 회의실을 이미 예약했습니다")

            created = now.strftime("%Y-%m-%d %H:%M:%S")
            try:
                cur = conn.execute(
                    "INSERT INTO rr_reservation (room_id, user_id, rsv_date, slot_start, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (room_id, uid, today, slot, created),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "이미 예약된 시간입니다")
            conn.execute("COMMIT")
            return {
                "reservation_id": cur.lastrowid, "room_id": room_id, "user_id": uid,
                "rsv_date": today, "slot_start": slot, "status": "active",
                "created_at": created, "cancelled_at": None,
            }
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


@app.delete("/api/reservations/{reservation_id}")
async def cancel_reservation(reservation_id: int, request: Request, user_id: str | None = None):
    if user_id is None:
        try:
            body = await request.json()
            if isinstance(body, dict):
                user_id = body.get("user_id")
        except Exception:
            pass
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            uid = check_user(conn, user_id)
            row = conn.execute(
                "SELECT * FROM rr_reservation WHERE reservation_id=?", (reservation_id,)
            ).fetchone()
            if row is None:
                raise ApiError(404, "존재하지 않는 예약입니다")
            if row["status"] == "cancelled":
                raise ApiError(409, "이미 취소된 예약입니다")
            if row["user_id"] != uid:
                raise ApiError(403, "본인의 예약만 취소할 수 있습니다")
            now = now_kst()
            if row["slot_start"] <= now.strftime("%H:%M:%S") or row["rsv_date"] < now.strftime("%Y-%m-%d"):
                raise ApiError(422, "이미 시작된 예약은 취소할 수 없습니다")
            cancelled = now.strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE rr_reservation SET status='cancelled', cancelled_at=? WHERE reservation_id=?",
                (cancelled, reservation_id),
            )
            conn.execute("COMMIT")
            result = dict(row)
            result.update(status="cancelled", cancelled_at=cancelled)
            return result
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
