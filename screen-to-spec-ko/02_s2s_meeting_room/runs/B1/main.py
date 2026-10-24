import csv
import os
import re
import sqlite3
import threading
from datetime import date as date_cls
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "rooms.db"
OPEN_MIN = 9 * 60
CLOSE_MIN = 18 * 60
MAX_MIN = 120

lock = threading.Lock()


def read_csv(name):
    with open(SEED / name, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """시작할 때마다 기존 DB 를 지우고 seed CSV 로 새로 만든다."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE mr_rooms (room_id TEXT PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL);
        CREATE TABLE mr_users (user TEXT PRIMARY KEY);
        CREATE TABLE mr_reservations (
            res_id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            date TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            user TEXT NOT NULL
        );
        """
    )
    for r in read_csv("rooms.csv"):
        conn.execute(
            "INSERT INTO mr_rooms VALUES (?,?,?)",
            (r["room_id"], r["name"], int(r["capacity"])),
        )
    for u in read_csv("users.csv"):
        conn.execute("INSERT INTO mr_users VALUES (?)", (u["user"],))
    for r in read_csv("reservations.csv"):
        conn.execute(
            "INSERT INTO mr_reservations (res_id, room_id, date, start, end, user) VALUES (?,?,?,?,?,?)",
            (int(r["res_id"]), r["room_id"], r["date"], r["start"], r["end"], r["user"]),
        )
    conn.commit()
    conn.close()


init_db()
app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request: Request, exc: Reject):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def to_min(hhmm):
    m = re.fullmatch(r"(\d{2}):(\d{2})", hhmm)
    if not m:
        raise Reject(400, "시각은 HH:MM 형식이어야 합니다")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise Reject(400, "시각은 HH:MM 형식이어야 합니다")
    return h * 60 + mi


def row_to_dict(r):
    return {k: r[k] for k in ("res_id", "room_id", "date", "start", "end", "user")}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/rooms")
def rooms():
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM mr_rooms ORDER BY rowid").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/users")
def users():
    conn = connect()
    try:
        rows = conn.execute("SELECT user FROM mr_users ORDER BY rowid").fetchall()
        return [r["user"] for r in rows]
    finally:
        conn.close()


@app.get("/api/reservations")
def list_reservations(date: str = ""):
    if not date:
        date = date_cls.today().isoformat()
    try:
        date_cls.fromisoformat(date)
    except ValueError:
        raise Reject(400, "날짜는 YYYY-MM-DD 형식이어야 합니다")
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM mr_reservations WHERE date=? ORDER BY start, res_id", (date,)
        ).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/reservations", status_code=201)
async def create_reservation(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    if not isinstance(body, dict):
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    vals = {}
    for k in ("room_id", "date", "start", "end", "user"):
        v = body.get(k)
        if not isinstance(v, str) or not v.strip():
            raise Reject(400, "빈 값이 있습니다: " + k)
        vals[k] = v.strip()
    try:
        date_cls.fromisoformat(vals["date"])
    except ValueError:
        raise Reject(400, "날짜는 YYYY-MM-DD 형식이어야 합니다")
    s, e = to_min(vals["start"]), to_min(vals["end"])
    if s % 30 or e % 30:
        raise Reject(400, "30분 단위로만 예약할 수 있습니다")
    if s < OPEN_MIN or e > CLOSE_MIN or e <= s:
        raise Reject(400, "예약 가능 시간은 09:00~18:00 입니다")
    if e - s > MAX_MIN:
        raise Reject(400, "한 번에 최대 2시간까지 예약할 수 있습니다")

    with lock:
        conn = connect()
        try:
            if not conn.execute(
                "SELECT 1 FROM mr_rooms WHERE room_id=?", (vals["room_id"],)
            ).fetchone():
                raise Reject(400, "존재하지 않는 회의실입니다")
            for r in conn.execute(
                "SELECT start, end FROM mr_reservations WHERE room_id=? AND date=?",
                (vals["room_id"], vals["date"]),
            ).fetchall():
                if s < to_min(r["end"]) and e > to_min(r["start"]):
                    raise Reject(409, "이미 예약된 시간입니다")
            cur = conn.execute(
                "INSERT INTO mr_reservations (room_id, date, start, end, user) VALUES (?,?,?,?,?)",
                (vals["room_id"], vals["date"], vals["start"], vals["end"], vals["user"]),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM mr_reservations WHERE res_id=?", (cur.lastrowid,)
            ).fetchone()
            return row_to_dict(row)
        finally:
            conn.close()


@app.delete("/api/reservations/{res_id}")
def delete_reservation(res_id: int, user: str = ""):
    with lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM mr_reservations WHERE res_id=?", (res_id,)
            ).fetchone()
            if not row:
                raise Reject(404, "예약을 찾을 수 없습니다")
            if row["user"] != user:
                raise Reject(403, "본인 예약만 취소할 수 있습니다")
            conn.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
            conn.commit()
            return Response(status_code=204)
        finally:
            conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
