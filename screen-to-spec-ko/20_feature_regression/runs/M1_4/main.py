import csv
import datetime
import os
import re
import sqlite3
import threading

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "rooms.db")
SEED = os.path.join(BASE, "seed")
LOCK = threading.Lock()
MAX_WEEKS = 12
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE mr_rooms (room_id TEXT PRIMARY KEY, name TEXT, capacity INTEGER)")
    con.execute("CREATE TABLE mr_users (user TEXT PRIMARY KEY)")
    con.execute("CREATE TABLE mr_reservations (res_id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, "
                "date TEXT, start TEXT, end TEXT, user TEXT, series_id INTEGER)")
    for r in read_csv("rooms.csv"):
        con.execute("INSERT INTO mr_rooms VALUES (?,?,?)", (r["room_id"], r["name"], int(r["capacity"])))
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO mr_users VALUES (?)", (r["user"],))
    for r in read_csv("reservations.csv"):
        con.execute("INSERT INTO mr_reservations (res_id, room_id, date, start, end, user) VALUES (?,?,?,?,?,?)",
                    (int(r["res_id"]), r["room_id"], r["date"], r["start"], r["end"], r["user"]))
    con.commit()
    con.close()


init_db()
app = FastAPI()


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


def minutes(t):
    return int(t[:2]) * 60 + int(t[3:])


@app.get("/api/rooms")
def rooms():
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT room_id, name, capacity FROM mr_rooms ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/users")
def users():
    con = db()
    try:
        return [r["user"] for r in con.execute("SELECT user FROM mr_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/reservations")
def list_reservations(date: str = Query(...)):
    con = db()
    try:
        rows = con.execute("SELECT res_id, room_id, date, start, end, user, series_id FROM mr_reservations "
                           "WHERE date=? ORDER BY start, res_id", (date,))
        return [dict(r) for r in rows]
    finally:
        con.close()


@app.post("/api/reservations")
def create(body: dict):
    vals = {k: body.get(k) for k in ("room_id", "date", "start", "end", "user")}
    if any(not isinstance(v, str) or not v.strip() for v in vals.values()):
        return err(400, "모든 값을 입력해 주세요")
    s, e = vals["start"], vals["end"]
    if not (TIME_RE.match(s) and TIME_RE.match(e)) or s[3:] not in ("00", "30") or e[3:] not in ("00", "30"):
        return err(400, "30분 단위로만 예약할 수 있습니다")
    if s < "09:00" or e > "18:00" or e <= s:
        return err(400, "예약 가능 시간은 09:00~18:00 입니다")
    if minutes(e) - minutes(s) > 120:
        return err(400, "한 번에 최대 2시간까지 예약할 수 있습니다")
    weeks = body.get("weeks", 1)
    if isinstance(weeks, bool) or not isinstance(weeks, int) or not 1 <= weeks <= MAX_WEEKS:
        return err(400, f"반복 횟수는 1~{MAX_WEEKS}회 입니다")
    try:
        first = datetime.date.fromisoformat(vals["date"])
    except ValueError:
        return err(400, "날짜 형식이 올바르지 않습니다")
    dates = [(first + datetime.timedelta(weeks=i)).isoformat() for i in range(weeks)]
    con = db()
    try:
        with LOCK:
            if not con.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (vals["room_id"],)).fetchone():
                return err(404, "회의실을 찾을 수 없습니다")
            for d in dates:
                if con.execute("SELECT 1 FROM mr_reservations WHERE room_id=? AND date=? AND ? < end AND ? > start",
                               (vals["room_id"], d, s, e)).fetchone():
                    if weeks == 1:
                        return err(409, "이미 예약된 시간입니다")
                    return err(409, f"{d} 에 이미 예약된 시간이 있어 반복 예약을 만들 수 없습니다")
            series = None
            if weeks > 1:
                series = (con.execute("SELECT COALESCE(MAX(series_id), 0) + 1 FROM mr_reservations").fetchone()[0])
            ids = []
            for d in dates:
                cur = con.execute("INSERT INTO mr_reservations (room_id, date, start, end, user, series_id) "
                                  "VALUES (?,?,?,?,?,?)", (vals["room_id"], d, s, e, vals["user"], series))
                ids.append(cur.lastrowid)
            con.commit()
    finally:
        con.close()
    return JSONResponse({"res_id": ids[0], **vals, "series_id": series, "res_ids": ids, "dates": dates},
                        status_code=201)


@app.delete("/api/reservations/{res_id}")
def cancel(res_id: int, user: str = "", series: bool = False):
    con = db()
    try:
        with LOCK:
            row = con.execute("SELECT user, date, series_id FROM mr_reservations WHERE res_id=?", (res_id,)).fetchone()
            if not row:
                return err(404, "예약을 찾을 수 없습니다")
            if row["user"] != user:
                return err(403, "본인 예약만 취소할 수 있습니다")
            if series and row["series_id"] is not None:
                con.execute("DELETE FROM mr_reservations WHERE series_id=? AND date>=?", (row["series_id"], row["date"]))
            else:
                con.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
            con.commit()
    finally:
        con.close()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
