import csv
import os
import re
import sqlite3
import threading

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "rooms.db")
LOCK = threading.Lock()

app = FastAPI()
conn = None


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global conn
    if conn:
        conn.close()
    if os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE mr_rooms (room_id TEXT PRIMARY KEY, name TEXT, capacity INTEGER);
        CREATE TABLE mr_users (user TEXT PRIMARY KEY);
        CREATE TABLE mr_reservations (
            res_id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, date TEXT,
            start TEXT, end TEXT, user TEXT);
        """
    )
    for r in read_csv("rooms.csv"):
        conn.execute("INSERT INTO mr_rooms VALUES (?,?,?)", (r["room_id"], r["name"], int(r["capacity"])))
    for r in read_csv("users.csv"):
        conn.execute("INSERT INTO mr_users VALUES (?)", (r["user"],))
    for r in read_csv("reservations.csv"):
        conn.execute(
            "INSERT INTO mr_reservations (res_id, room_id, date, start, end, user) VALUES (?,?,?,?,?,?)",
            (int(r["res_id"]), r["room_id"], r["date"], r["start"], r["end"], r["user"]),
        )
    conn.commit()


init_db()


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


def minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/rooms")
def rooms():
    rows = conn.execute("SELECT * FROM mr_rooms ORDER BY rowid").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/users")
def users():
    return [r["user"] for r in conn.execute("SELECT user FROM mr_users ORDER BY rowid")]


@app.get("/api/reservations")
def list_reservations(date: str = Query(...)):
    rows = conn.execute(
        "SELECT * FROM mr_reservations WHERE date=? ORDER BY start, res_id", (date,)
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/reservations")
def create(body: dict):
    room_id = str(body.get("room_id") or "").strip()
    date = str(body.get("date") or "").strip()
    start = str(body.get("start") or "").strip()
    end = str(body.get("end") or "").strip()
    user = str(body.get("user") or "").strip()
    if not (room_id and date and start and end and user):
        return err(400, "필수 값이 비어 있습니다")
    if not (re.fullmatch(r"\d{2}:\d{2}", start) and re.fullmatch(r"\d{2}:\d{2}", end)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)):
        return err(400, "날짜 또는 시각 형식이 올바르지 않습니다")
    if start[3:] not in ("00", "30") or end[3:] not in ("00", "30"):
        return err(400, "30분 단위로만 예약할 수 있습니다")
    s, e = minutes(start), minutes(end)
    if s < 9 * 60 or e > 18 * 60 or e <= s:
        return err(400, "예약 가능 시간은 09:00~18:00 입니다")
    if e - s > 120:
        return err(400, "한 번에 최대 2시간까지 예약할 수 있습니다")
    with LOCK:
        if not conn.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (room_id,)).fetchone():
            return err(404, "회의실을 찾을 수 없습니다")
        if not conn.execute("SELECT 1 FROM mr_users WHERE user=?", (user,)).fetchone():
            return err(400, "알 수 없는 사용자입니다")
        for r in conn.execute(
            "SELECT start, end FROM mr_reservations WHERE room_id=? AND date=?", (room_id, date)
        ):
            if s < minutes(r["end"]) and e > minutes(r["start"]):
                return err(409, "이미 예약된 시간입니다")
        cur = conn.execute(
            "INSERT INTO mr_reservations (room_id, date, start, end, user) VALUES (?,?,?,?,?)",
            (room_id, date, start, end, user),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM mr_reservations WHERE res_id=?", (cur.lastrowid,)).fetchone()
    return JSONResponse(dict(row), status_code=201)


@app.delete("/api/reservations/{res_id}")
def delete(res_id: int, user: str = ""):
    with LOCK:
        row = conn.execute("SELECT * FROM mr_reservations WHERE res_id=?", (res_id,)).fetchone()
        if not row:
            return err(404, "예약을 찾을 수 없습니다")
        if row["user"] != user:
            return err(403, "본인 예약만 취소할 수 있습니다")
        conn.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
        conn.commit()
    return Response(status_code=204)
