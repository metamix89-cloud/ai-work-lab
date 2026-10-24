import csv
import os
import re
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "rooms.db")
LOCK = threading.Lock()

app = FastAPI()


def connect():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    conn = connect()
    conn.executescript("""
        CREATE TABLE mr_rooms (room_id TEXT PRIMARY KEY, name TEXT, capacity INTEGER);
        CREATE TABLE mr_users (user TEXT PRIMARY KEY);
        CREATE TABLE mr_reservations (
            res_id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT, date TEXT, start TEXT, end TEXT, user TEXT);
    """)
    for r in read_csv("rooms.csv"):
        conn.execute("INSERT INTO mr_rooms VALUES (?,?,?)", (r["room_id"], r["name"], int(r["capacity"])))
    for r in read_csv("users.csv"):
        conn.execute("INSERT INTO mr_users VALUES (?)", (r["user"],))
    for r in read_csv("reservations.csv"):
        conn.execute("INSERT INTO mr_reservations VALUES (?,?,?,?,?,?)",
                     (int(r["res_id"]), r["room_id"], r["date"], r["start"], r["end"], r["user"]))
    conn.commit()
    conn.close()


init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


TIME_RE = re.compile(r"^\d{2}:\d{2}$")


@app.get("/api/rooms")
def rooms():
    conn = connect()
    rows = conn.execute("SELECT room_id, name, capacity FROM mr_rooms ORDER BY rowid").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/users")
def users():
    conn = connect()
    rows = conn.execute("SELECT user FROM mr_users ORDER BY rowid").fetchall()
    conn.close()
    return [r["user"] for r in rows]


@app.get("/api/reservations")
def list_reservations(date: str = ""):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    conn = connect()
    rows = conn.execute(
        "SELECT res_id, room_id, date, start, end, user FROM mr_reservations WHERE date=? ORDER BY start, res_id",
        (date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/reservations")
async def create_reservation(request: Request):
    try:
        body = await request.json()
    except Exception:
        return err(400, "요청 형식이 올바르지 않습니다")
    if not isinstance(body, dict):
        return err(400, "요청 형식이 올바르지 않습니다")
    vals = {}
    for k in ("room_id", "date", "start", "end", "user"):
        v = body.get(k)
        if not isinstance(v, str) or not v.strip():
            return err(400, "빈 값이 있습니다: " + k)
        vals[k] = v.strip()
    try:
        datetime.strptime(vals["date"], "%Y-%m-%d")
    except ValueError:
        return err(400, "날짜 형식이 올바르지 않습니다")
    if not TIME_RE.match(vals["start"]) or not TIME_RE.match(vals["end"]):
        return err(400, "시각 형식이 올바르지 않습니다")
    s, e = minutes(vals["start"]), minutes(vals["end"])
    if s % 30 or e % 30:
        return err(400, "30분 단위로만 예약할 수 있습니다")
    if s < 9 * 60 or e > 18 * 60 or e <= s:
        return err(400, "예약 가능 시간은 09:00~18:00 입니다")
    if e - s > 120:
        return err(400, "한 번에 최대 2시간까지 예약할 수 있습니다")
    with LOCK:
        conn = connect()
        try:
            if not conn.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (vals["room_id"],)).fetchone():
                return err(400, "존재하지 않는 회의실입니다")
            if not conn.execute("SELECT 1 FROM mr_users WHERE user=?", (vals["user"],)).fetchone():
                return err(400, "존재하지 않는 사용자입니다")
            clash = conn.execute(
                "SELECT 1 FROM mr_reservations WHERE room_id=? AND date=? AND ? < end AND ? > start",
                (vals["room_id"], vals["date"], vals["start"], vals["end"])).fetchone()
            if clash:
                return err(409, "이미 예약된 시간입니다")
            cur = conn.execute(
                "INSERT INTO mr_reservations (room_id, date, start, end, user) VALUES (?,?,?,?,?)",
                (vals["room_id"], vals["date"], vals["start"], vals["end"], vals["user"]))
            conn.commit()
            out = dict(vals, res_id=cur.lastrowid)
        finally:
            conn.close()
    return JSONResponse(out, status_code=201)


@app.delete("/api/reservations/{res_id}")
def delete_reservation(res_id: int, user: str = ""):
    with LOCK:
        conn = connect()
        try:
            row = conn.execute("SELECT user FROM mr_reservations WHERE res_id=?", (res_id,)).fetchone()
            if not row:
                return err(404, "예약을 찾을 수 없습니다")
            if row["user"] != user:
                return err(403, "본인 예약만 취소할 수 있습니다")
            conn.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
            conn.commit()
        finally:
            conn.close()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
