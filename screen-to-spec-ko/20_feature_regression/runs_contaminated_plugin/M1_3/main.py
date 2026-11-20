import csv
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
                "date TEXT, start TEXT, end TEXT, user TEXT)")
    for r in read_csv("rooms.csv"):
        con.execute("INSERT INTO mr_rooms VALUES (?,?,?)", (r["room_id"], r["name"], int(r["capacity"])))
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO mr_users VALUES (?)", (r["user"],))
    for r in read_csv("reservations.csv"):
        con.execute("INSERT INTO mr_reservations VALUES (?,?,?,?,?,?)",
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
        rows = con.execute("SELECT res_id, room_id, date, start, end, user FROM mr_reservations "
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
    con = db()
    try:
        with LOCK:
            if not con.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (vals["room_id"],)).fetchone():
                return err(404, "회의실을 찾을 수 없습니다")
            if con.execute("SELECT 1 FROM mr_reservations WHERE room_id=? AND date=? AND ? < end AND ? > start",
                           (vals["room_id"], vals["date"], s, e)).fetchone():
                return err(409, "이미 예약된 시간입니다")
            cur = con.execute("INSERT INTO mr_reservations (room_id, date, start, end, user) VALUES (?,?,?,?,?)",
                              (vals["room_id"], vals["date"], s, e, vals["user"]))
            con.commit()
            res_id = cur.lastrowid
    finally:
        con.close()
    return JSONResponse({"res_id": res_id, **vals}, status_code=201)


@app.delete("/api/reservations/{res_id}")
def cancel(res_id: int, user: str = ""):
    con = db()
    try:
        with LOCK:
            row = con.execute("SELECT user FROM mr_reservations WHERE res_id=?", (res_id,)).fetchone()
            if not row:
                return err(404, "예약을 찾을 수 없습니다")
            if row["user"] != user:
                return err(403, "본인 예약만 취소할 수 있습니다")
            con.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
            con.commit()
    finally:
        con.close()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
