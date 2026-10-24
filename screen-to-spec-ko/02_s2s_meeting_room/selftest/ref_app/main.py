# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R7 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import os
import sqlite3

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "rooms.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE mr_rooms(room_id TEXT PRIMARY KEY, name TEXT, capacity INTEGER);
    CREATE TABLE mr_users(user TEXT PRIMARY KEY);
    CREATE TABLE mr_reservations(res_id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, date TEXT, start TEXT, end TEXT, user TEXT);""")
    for name, table, n in (("rooms.csv", "mr_rooms", 3), ("users.csv", "mr_users", 1), ("reservations.csv", "mr_reservations", 6)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


class ResIn(BaseModel):
    room_id: str
    date: str
    start: str
    end: str
    user: str


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/rooms")
def rooms():
    return [dict(r) for r in con().execute("SELECT * FROM mr_rooms")]


@app.get("/api/users")
def users():
    return [r["user"] for r in con().execute("SELECT user FROM mr_users")]


@app.get("/api/reservations")
def reservations(date: str):
    return [dict(r) for r in con().execute("SELECT * FROM mr_reservations WHERE date=? ORDER BY room_id, start", (date,))]


@app.post("/api/reservations", status_code=201)
def create(r: ResIn):
    try:
        s, e = minutes(r.start), minutes(r.end)
    except Exception:
        raise HTTPException(400, "시각 형식은 HH:MM 입니다")
    if s % 30 or e % 30:
        raise HTTPException(400, "30분 단위로만 예약할 수 있습니다")
    if s < 9 * 60 or e > 18 * 60 or e <= s:
        raise HTTPException(400, "예약 가능 시간은 09:00~18:00 입니다")
    if e - s > 120:
        raise HTTPException(400, "한 번에 최대 2시간까지 예약할 수 있습니다")
    if not r.user:
        raise HTTPException(400, "사용자를 선택하세요")
    c = con()
    clash = c.execute("SELECT 1 FROM mr_reservations WHERE room_id=? AND date=? AND start<? AND end>?",
                      (r.room_id, r.date, r.end, r.start)).fetchone()
    if clash:
        raise HTTPException(409, "이미 예약된 시간입니다")
    cur = c.execute("INSERT INTO mr_reservations(room_id,date,start,end,user) VALUES (?,?,?,?,?)",
                    (r.room_id, r.date, r.start, r.end, r.user))
    c.commit()
    return dict(c.execute("SELECT * FROM mr_reservations WHERE res_id=?", (cur.lastrowid,)).fetchone())


@app.delete("/api/reservations/{res_id}", status_code=204)
def delete(res_id: int, user: str = ""):
    c = con()
    row = c.execute("SELECT * FROM mr_reservations WHERE res_id=?", (res_id,)).fetchone()
    if not row:
        raise HTTPException(404, "예약이 없습니다")
    if row["user"] != user:
        raise HTTPException(403, "본인 예약만 취소할 수 있습니다")
    c.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))
    c.commit()
    return Response(status_code=204)
