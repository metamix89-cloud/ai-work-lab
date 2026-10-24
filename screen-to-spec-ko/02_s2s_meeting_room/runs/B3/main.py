import csv
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response

BASE = Path(__file__).parent
DB_PATH = BASE / "rooms.db"
OPEN_MIN, CLOSE_MIN, MAX_MIN = 9 * 60, 18 * 60, 120


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(BASE / "seed" / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    c = conn()
    c.executescript(
        """
        CREATE TABLE mr_rooms (room_id TEXT PRIMARY KEY, name TEXT, capacity INTEGER);
        CREATE TABLE mr_users (user TEXT PRIMARY KEY);
        CREATE TABLE mr_reservations (
            res_id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, date TEXT,
            start TEXT, end TEXT, user TEXT);
        """
    )
    c.executemany("INSERT INTO mr_rooms VALUES (?,?,?)",
                  [(r["room_id"], r["name"], int(r["capacity"])) for r in read_csv("rooms.csv")])
    c.executemany("INSERT INTO mr_users VALUES (?)", [(r["user"],) for r in read_csv("users.csv")])
    c.executemany("INSERT INTO mr_reservations VALUES (?,?,?,?,?,?)",
                  [(int(r["res_id"]), r["room_id"], r["date"], r["start"], r["end"], r["user"])
                   for r in read_csv("reservations.csv")])
    c.commit()
    c.close()


init_db()
app = FastAPI()


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "필수 값이 비어 있거나 형식이 올바르지 않습니다"}, status_code=400)


def to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def row(r):
    return {k: r[k] for k in r.keys()}


def bad(msg, code=400):
    raise HTTPException(status_code=code, detail=msg)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/rooms")
def rooms():
    c = conn()
    out = [row(r) for r in c.execute("SELECT * FROM mr_rooms ORDER BY rowid")]
    c.close()
    return out


@app.get("/api/users")
def users():
    c = conn()
    out = [r["user"] for r in c.execute("SELECT user FROM mr_users ORDER BY rowid")]
    c.close()
    return out


@app.get("/api/reservations")
def list_res(date: str = ""):
    c = conn()
    if date:
        rs = c.execute("SELECT * FROM mr_reservations WHERE date=? ORDER BY start", (date,))
    else:
        rs = c.execute("SELECT * FROM mr_reservations ORDER BY date, start")
    out = [row(r) for r in rs]
    c.close()
    return out


@app.post("/api/reservations", status_code=201)
async def create(request: Request):
    try:
        b = await request.json()
    except Exception:
        b = None
    if not isinstance(b, dict):
        bad("요청 형식이 올바르지 않습니다")
    vals = {k: b.get(k) for k in ("room_id", "date", "start", "end", "user")}
    if any(not isinstance(v, str) or not v.strip() for v in vals.values()):
        bad("모든 항목을 입력해야 합니다")
    try:
        assert len(vals["start"]) == 5 and len(vals["end"]) == 5
        s, e = to_min(vals["start"]), to_min(vals["end"])
    except Exception:
        bad("시각 형식이 올바르지 않습니다 (HH:MM)")
    if s % 30 or e % 30:
        bad("30분 단위로만 예약할 수 있습니다")
    if s < OPEN_MIN or e > CLOSE_MIN or e <= s:
        bad("예약 가능 시간은 09:00~18:00 입니다")
    if e - s > MAX_MIN:
        bad("한 번에 최대 2시간까지 예약할 수 있습니다")
    c = conn()
    try:
        if not c.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (vals["room_id"],)).fetchone():
            bad("없는 회의실입니다")
        for r in c.execute("SELECT start, end FROM mr_reservations WHERE room_id=? AND date=?",
                           (vals["room_id"], vals["date"])):
            if s < to_min(r["end"]) and e > to_min(r["start"]):
                bad("이미 예약된 시간입니다", 409)
        cur = c.execute("INSERT INTO mr_reservations (room_id,date,start,end,user) VALUES (?,?,?,?,?)",
                        (vals["room_id"], vals["date"], vals["start"], vals["end"], vals["user"]))
        c.commit()
        return {"res_id": cur.lastrowid, **vals}
    finally:
        c.close()


@app.delete("/api/reservations/{res_id}")
def delete(res_id: int, user: str = ""):
    c = conn()
    try:
        r = c.execute("SELECT * FROM mr_reservations WHERE res_id=?", (res_id,)).fetchone()
        if not r:
            bad("예약을 찾을 수 없습니다", 404)
        if r["user"] != user:
            bad("본인 예약만 취소할 수 있습니다", 403)
        c.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
        c.commit()
        return Response(status_code=204)
    finally:
        c.close()
