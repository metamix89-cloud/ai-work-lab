import os
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = os.environ.get("MR_DB", str(BASE / "meeting.db"))
OPEN_MIN, CLOSE_MIN = 9 * 60, 18 * 60
MIN_LEN, MAX_LEN = 30, 120
MAX_TITLE = 50


def connect():
    # isolation_level=None: 트랜잭션을 직접 제어 (BEGIN IMMEDIATE)
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def to_min(hhmm):
    try:
        h, m = hhmm.split(":")
        if len(h) != 2 or len(m) != 2:
            raise ValueError
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        raise HTTPException(400, "시간 형식이 올바르지 않습니다. (HH:MM)")


def fmt(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def init_db():
    con = connect()
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS mr_users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mr_rooms (
            room_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS mr_reservations (
            reservation_id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL REFERENCES mr_rooms(room_id),
            user_id INTEGER NOT NULL REFERENCES mr_users(user_id),
            rsv_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_mr_rsv_room_date
            ON mr_reservations(room_id, rsv_date);
        """
    )
    if con.execute("SELECT COUNT(*) FROM mr_rooms").fetchone()[0] == 0:
        # 가상 데이터만 사용
        con.execute("BEGIN IMMEDIATE")
        con.executemany(
            "INSERT INTO mr_users(user_id, name) VALUES (?, ?)",
            [(1, "김가온"), (2, "이나래"), (3, "박다온"), (4, "최라온"), (5, "정마루")],
        )
        con.executemany(
            "INSERT INTO mr_rooms(room_id, name) VALUES (?, ?)",
            [(1, "회의실 A"), (2, "회의실 B"), (3, "회의실 C")],
        )
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().isoformat(timespec="seconds")
        con.executemany(
            "INSERT INTO mr_reservations(room_id, user_id, rsv_date, start_time,"
            " end_time, title, created_at) VALUES (?,?,?,?,?,?,?)",
            [
                (1, 1, today, "09:00", "10:00", "주간 업무 회의", now),
                (1, 2, today, "10:00", "11:00", "디자인 리뷰", now),
                (2, 3, today, "11:00", "12:00", "스프린트 계획", now),
                (2, 4, today, "14:00", "15:30", "고객사 미팅", now),
                (3, 5, today, "13:00", "14:00", "신입 온보딩", now),
                (3, 1, today, "16:00", "17:00", "회고 모임", now),
            ],
        )
        con.execute("COMMIT")
    con.close()


app = FastAPI(title="회의실 예약")
init_db()


class ReservationIn(BaseModel):
    room_id: int
    user_id: int
    start_time: str
    end_time: str
    title: str


def now_info():
    n = datetime.now()
    return n.strftime("%Y-%m-%d"), n.hour * 60 + n.minute


@app.get("/api/users")
def users():
    con = connect()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM mr_users ORDER BY user_id")]
    finally:
        con.close()


@app.get("/api/schedule")
def schedule():
    today, now_min = now_info()
    con = connect()
    try:
        rooms = [dict(r) for r in con.execute("SELECT * FROM mr_rooms ORDER BY room_id")]
        rsv = [
            dict(r)
            for r in con.execute(
                "SELECT r.reservation_id, r.room_id, r.user_id, u.name AS user_name,"
                " r.start_time, r.end_time, r.title FROM mr_reservations r"
                " JOIN mr_users u ON u.user_id = r.user_id"
                " WHERE r.rsv_date = ? ORDER BY r.start_time",
                (today,),
            )
        ]
        return {"date": today, "now": fmt(now_min), "rooms": rooms, "reservations": rsv}
    finally:
        con.close()


@app.post("/api/reservations", status_code=201)
def create_reservation(body: ReservationIn):
    today, now_min = now_info()
    s, e = to_min(body.start_time), to_min(body.end_time)
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "제목을 입력해 주세요.")
    if len(title) > MAX_TITLE:
        raise HTTPException(400, f"제목은 {MAX_TITLE}자 이내로 입력해 주세요.")
    if s % 30 or e % 30:
        raise HTTPException(400, "시작·종료 시각은 30분 단위여야 합니다.")
    if s < OPEN_MIN or e > CLOSE_MIN:
        raise HTTPException(400, "예약 가능 시간은 09:00~18:00입니다.")
    if e <= s:
        raise HTTPException(400, "종료 시각은 시작 시각보다 뒤여야 합니다.")
    if e - s < MIN_LEN or e - s > MAX_LEN:
        raise HTTPException(400, "예약은 최소 30분, 최대 2시간까지 가능합니다.")
    if s < now_min:
        raise HTTPException(400, "이미 지난 시간은 예약할 수 없습니다.")

    con = connect()
    try:
        # 검사와 저장을 하나의 쓰기 트랜잭션으로 (R-08)
        con.execute("BEGIN IMMEDIATE")
        try:
            if not con.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (body.room_id,)).fetchone():
                raise HTTPException(404, "존재하지 않는 회의실입니다.")
            if not con.execute("SELECT 1 FROM mr_users WHERE user_id=?", (body.user_id,)).fetchone():
                raise HTTPException(404, "존재하지 않는 사용자입니다.")
            for r in con.execute(
                "SELECT start_time, end_time FROM mr_reservations WHERE room_id=? AND rsv_date=?",
                (body.room_id, today),
            ).fetchall():
                if to_min(r["start_time"]) < e and s < to_min(r["end_time"]):
                    raise HTTPException(409, "이미 예약된 시간과 겹칩니다.")
            cur = con.execute(
                "INSERT INTO mr_reservations(room_id, user_id, rsv_date, start_time,"
                " end_time, title, created_at) VALUES (?,?,?,?,?,?,?)",
                (body.room_id, body.user_id, today, fmt(s), fmt(e), title,
                 datetime.now().isoformat(timespec="seconds")),
            )
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        return {"reservation_id": cur.lastrowid}
    finally:
        con.close()


@app.delete("/api/reservations/{reservation_id}")
def cancel_reservation(reservation_id: int, user_id: int):
    today, now_min = now_info()
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            r = con.execute(
                "SELECT * FROM mr_reservations WHERE reservation_id=?", (reservation_id,)
            ).fetchone()
            if not r:
                raise HTTPException(404, "예약을 찾을 수 없습니다.")
            if r["user_id"] != user_id:
                raise HTTPException(403, "본인의 예약만 취소할 수 있습니다.")
            if (r["rsv_date"], to_min(r["end_time"])) <= (today, now_min):
                raise HTTPException(400, "이미 종료된 예약은 취소할 수 없습니다.")
            con.execute("DELETE FROM mr_reservations WHERE reservation_id=?", (reservation_id,))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        return {"ok": True}
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
