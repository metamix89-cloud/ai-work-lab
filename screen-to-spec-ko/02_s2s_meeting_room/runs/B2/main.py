import csv
import os
import re
import sqlite3
import threading
from datetime import date as _date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "rooms.db"
OPEN_MIN, CLOSE_MIN, MAX_MIN = 9 * 60, 18 * 60, 120

app = FastAPI()
_lock = threading.Lock()
_conn = None


def _read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global _conn
    if _conn is not None:
        _conn.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE mr_rooms (room_id TEXT PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL);
        CREATE TABLE mr_users (user TEXT PRIMARY KEY);
        CREATE TABLE mr_reservations (
            res_id INTEGER PRIMARY KEY, room_id TEXT NOT NULL, date TEXT NOT NULL,
            start TEXT NOT NULL, end TEXT NOT NULL, user TEXT NOT NULL);
        """
    )
    conn.executemany(
        "INSERT INTO mr_rooms VALUES (?,?,?)",
        [(r["room_id"], r["name"], int(r["capacity"])) for r in _read_csv("rooms.csv")],
    )
    conn.executemany("INSERT INTO mr_users VALUES (?)", [(r["user"],) for r in _read_csv("users.csv")])
    conn.executemany(
        "INSERT INTO mr_reservations VALUES (?,?,?,?,?,?)",
        [
            (int(r["res_id"]), r["room_id"], r["date"], r["start"], r["end"], r["user"])
            for r in _read_csv("reservations.csv")
        ],
    )
    conn.commit()
    _conn = conn


init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


@app.exception_handler(RequestValidationError)
async def _validation(request, exc):
    return err(400, "입력값이 올바르지 않습니다")


@app.exception_handler(HTTPException)
async def _http(request, exc):
    return err(exc.status_code, exc.detail)


def to_min(s):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m or int(m.group(2)) > 59 or int(m.group(1)) > 24:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def valid_date(s):
    try:
        _date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


def row(r):
    return {k: r[k] for k in ("res_id", "room_id", "date", "start", "end", "user")}


@app.get("/api/rooms")
def rooms():
    with _lock:
        rs = _conn.execute("SELECT * FROM mr_rooms ORDER BY rowid").fetchall()
    return [dict(r) for r in rs]


@app.get("/api/users")
def users():
    with _lock:
        rs = _conn.execute("SELECT user FROM mr_users ORDER BY rowid").fetchall()
    return [r["user"] for r in rs]


@app.get("/api/reservations")
def list_reservations(date: str = Query(default=None)):
    d = date or _date.today().isoformat()
    if not valid_date(d):
        return err(400, "날짜 형식이 올바르지 않습니다")
    with _lock:
        rs = _conn.execute(
            "SELECT * FROM mr_reservations WHERE date=? ORDER BY start, res_id", (d,)
        ).fetchall()
    return [row(r) for r in rs]


@app.post("/api/reservations", status_code=201)
def create(body: dict):
    vals = {k: body.get(k) for k in ("room_id", "date", "start", "end", "user")}
    if any(not isinstance(v, str) or not v.strip() for v in vals.values()):
        return err(400, "방, 날짜, 시작, 끝, 사용자를 모두 입력해야 합니다")
    room_id, d, start, end, user = (vals[k].strip() for k in ("room_id", "date", "start", "end", "user"))
    s, e = to_min(start), to_min(end)
    if s is None or e is None or not valid_date(d):
        return err(400, "시각 또는 날짜 형식이 올바르지 않습니다")
    if s % 30 or e % 30:
        return err(400, "30분 단위로만 예약할 수 있습니다")
    if s < OPEN_MIN or e > CLOSE_MIN or e <= s:
        return err(400, "예약 가능 시간은 09:00~18:00 입니다")
    if e - s > MAX_MIN:
        return err(400, "한 번에 최대 2시간까지 예약할 수 있습니다")
    start, end = f"{s // 60:02d}:{s % 60:02d}", f"{e // 60:02d}:{e % 60:02d}"
    with _lock:
        if not _conn.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (room_id,)).fetchone():
            return err(400, "없는 회의실입니다")
        if not _conn.execute("SELECT 1 FROM mr_users WHERE user=?", (user,)).fetchone():
            return err(400, "없는 사용자입니다")
        clash = _conn.execute(
            "SELECT 1 FROM mr_reservations WHERE room_id=? AND date=? AND ? < end AND ? > start",
            (room_id, d, start, end),
        ).fetchone()
        if clash:
            return err(409, "이미 예약된 시간입니다")
        cur = _conn.execute(
            "INSERT INTO mr_reservations (room_id,date,start,end,user) VALUES (?,?,?,?,?)",
            (room_id, d, start, end, user),
        )
        _conn.commit()
        r = _conn.execute("SELECT * FROM mr_reservations WHERE res_id=?", (cur.lastrowid,)).fetchone()
    return row(r)


@app.delete("/api/reservations/{res_id}", status_code=204)
def delete(res_id: int, user: str = ""):
    with _lock:
        r = _conn.execute("SELECT * FROM mr_reservations WHERE res_id=?", (res_id,)).fetchone()
        if not r:
            return err(404, "예약을 찾을 수 없습니다")
        if r["user"] != user:
            return err(403, "본인 예약만 취소할 수 있습니다")
        _conn.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
        _conn.commit()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
