import calendar
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import scheduler

BASE = Path(__file__).parent
DB = BASE / "duty.db"

app = FastAPI(title="한빛요양병원 3병동 야간 당직 순번표")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_db():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS nurse(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS leave(
                id INTEGER PRIMARY KEY,
                nurse_id INTEGER NOT NULL REFERENCES nurse(id),
                day TEXT NOT NULL, UNIQUE(nurse_id, day));
            CREATE TABLE IF NOT EXISTS duty(
                day TEXT PRIMARY KEY,
                nurse_id INTEGER REFERENCES nurse(id));
            """
        )
        if c.execute("SELECT COUNT(*) FROM nurse").fetchone()[0]:
            return
        nurses = [
            ("김서연", "#4e79a7"), ("이지민", "#f28e2b"), ("박하은", "#59a14f"),
            ("최유진", "#b07aa1"), ("정수빈", "#e15759"), ("한도윤", "#76b7b2"),
        ]
        c.executemany("INSERT INTO nurse(name,color) VALUES(?,?)", nurses)
        # 가상 휴가 (이번 달 / 다음 달)
        today = date.today()
        nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        plan = {  # nurse_id: [(month_date, 시작일, 종료일), ...]
            1: [(today, 5, 9)], 2: [(today, 14, 16), (nxt, 20, 22)],
            3: [(today, 24, 28)], 4: [(nxt, 2, 6)],
            5: [(today, 1, 3), (nxt, 12, 14)], 6: [(nxt, 25, 29)],
        }
        for nid, ranges in plan.items():
            for base, s, e in ranges:
                last = calendar.monthrange(base.year, base.month)[1]
                for d in range(s, min(e, last) + 1):
                    c.execute("INSERT OR IGNORE INTO leave(nurse_id,day) VALUES(?,?)",
                              (nid, date(base.year, base.month, d).isoformat()))
    for base in (date.today(), (date.today().replace(day=1) + timedelta(days=32))):
        generate(base.year, base.month)


def generate(year: int, month: int):
    with conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM nurse ORDER BY id")]
        prefix = f"{year:04d}-{month:02d}-"
        leaves = {(r["nurse_id"], date.fromisoformat(r["day"]))
                  for r in c.execute("SELECT nurse_id, day FROM leave WHERE day LIKE ?", (prefix + "%",))}
        result = scheduler.generate(ids, year, month, leaves)
        c.execute("DELETE FROM duty WHERE day LIKE ?", (prefix + "%",))
        c.executemany("INSERT INTO duty(day,nurse_id) VALUES(?,?)",
                      [(d.isoformat(), n) for d, n in result.items()])


init_db()


class LeaveIn(BaseModel):
    nurse_id: int
    start: date
    end: date


@app.get("/api/nurses")
def nurses():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM nurse ORDER BY id")]


@app.get("/api/schedule")
def schedule(year: int, month: int):
    if not 1 <= month <= 12:
        raise HTTPException(400, "month 범위 오류")
    prefix = f"{year:04d}-{month:02d}-"
    with conn() as c:
        duty = {r["day"]: r["nurse_id"] for r in c.execute("SELECT * FROM duty WHERE day LIKE ?", (prefix + "%",))}
        leaves = {}
        for r in c.execute("SELECT nurse_id, day FROM leave WHERE day LIKE ? ORDER BY day", (prefix + "%",)):
            leaves.setdefault(r["day"], []).append(r["nurse_id"])
        stats = {r["id"]: {"name": r["name"], "total": 0, "weekend": 0, "leave": 0}
                 for r in c.execute("SELECT id, name FROM nurse")}
    for day, nid in duty.items():
        if nid:
            stats[nid]["total"] += 1
            stats[nid]["weekend"] += date.fromisoformat(day).weekday() >= 5
    for day, ids in leaves.items():
        for nid in ids:
            stats[nid]["leave"] += 1
    return {"year": year, "month": month, "generated": bool(duty),
            "duty": duty, "leaves": leaves, "stats": stats}


@app.post("/api/schedule/generate")
def regenerate(year: int, month: int):
    if not 1 <= month <= 12:
        raise HTTPException(400, "month 범위 오류")
    generate(year, month)
    return schedule(year, month)


@app.post("/api/leaves")
def add_leave(body: LeaveIn):
    if body.end < body.start or (body.end - body.start).days > 60:
        raise HTTPException(400, "기간이 올바르지 않습니다")
    with conn() as c:
        if not c.execute("SELECT 1 FROM nurse WHERE id=?", (body.nurse_id,)).fetchone():
            raise HTTPException(404, "간호사 없음")
        d = body.start
        while d <= body.end:
            c.execute("INSERT OR IGNORE INTO leave(nurse_id,day) VALUES(?,?)", (body.nurse_id, d.isoformat()))
            d += timedelta(days=1)
    return {"ok": True}


@app.delete("/api/leaves")
def delete_leave(nurse_id: int, day: date):
    with conn() as c:
        c.execute("DELETE FROM leave WHERE nurse_id=? AND day=?", (nurse_id, day.isoformat()))
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
