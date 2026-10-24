import sqlite3
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scheduler import generate

BASE = Path(__file__).parent
DB = BASE / "duty.db"


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="한빛요양병원 3병동 야간 당직표", lifespan=lifespan)


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    c = conn()
    with c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS nurse(id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS leave(
            id INTEGER PRIMARY KEY, nurse_id INTEGER NOT NULL REFERENCES nurse(id) ON DELETE CASCADE,
            day TEXT NOT NULL, reason TEXT DEFAULT '', UNIQUE(nurse_id, day));
        CREATE TABLE IF NOT EXISTS duty(day TEXT PRIMARY KEY, nurse_id INTEGER NOT NULL REFERENCES nurse(id));
        """)
        if c.execute("SELECT COUNT(*) FROM nurse").fetchone()[0]:
            return
        colors = ["#4f8cff", "#ff7a59", "#2fb67c", "#b36bff", "#f2b134", "#e0508f"]
        for i, n in enumerate(["김서연", "이지훈", "박민지", "최유나", "정하늘", "한도윤"]):
            c.execute("INSERT INTO nurse(name,color) VALUES(?,?)", (n, colors[i]))
        today = date.today()
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        # 가상 휴가: 간호사id -> (월 내 일자들, 사유)
        plan = {2: (range(4, 9), "연차"), 4: ([14, 15], "경조사"),
                5: (range(20, 23), "여름휴가"), 1: ([9], "병가"), 6: ([27, 28], "연차")}
        for first in (today.replace(day=1), nxt):
            for nid, (ds, why) in plan.items():
                for d in ds:
                    c.execute("INSERT OR IGNORE INTO leave(nurse_id,day,reason) VALUES(?,?,?)",
                              (nid, (first + timedelta(days=d - 1)).isoformat(), why))
            _build(c, first.year, first.month)


def _build(c, y, m):
    nurses = [r["id"] for r in c.execute("SELECT id FROM nurse ORDER BY id")]
    prefix = f"{y:04d}-{m:02d}-"
    leaves = {}
    for r in c.execute("SELECT nurse_id, day FROM leave WHERE day LIKE ?", (prefix + "%",)):
        leaves.setdefault(r["nurse_id"], set()).add(date.fromisoformat(r["day"]))
    res = generate(y, m, nurses, leaves)
    c.execute("DELETE FROM duty WHERE day LIKE ?", (prefix + "%",))
    c.executemany("INSERT INTO duty(day,nurse_id) VALUES(?,?)", [(d.isoformat(), n) for d, n in res.items()])


def _month(ym):
    try:
        y, m = map(int, ym.split("-"))
        date(y, m, 1)
        return y, m
    except ValueError:
        raise HTTPException(400, "월 형식은 YYYY-MM")


@app.get("/api/nurses")
def nurses():
    return [dict(r) for r in conn().execute("SELECT * FROM nurse ORDER BY id")]


@app.get("/api/schedule/{ym}")
def schedule(ym: str):
    y, m = _month(ym)
    p = f"{y:04d}-{m:02d}-%"
    c = conn()
    duty = {r["day"]: r["nurse_id"] for r in c.execute("SELECT * FROM duty WHERE day LIKE ?", (p,))}
    leaves = [dict(r) for r in c.execute(
        "SELECT nurse_id, day, reason FROM leave WHERE day LIKE ? ORDER BY day", (p,))]
    stats = [dict(r) for r in c.execute("""
        SELECT n.id nurse_id, n.name, n.color,
          (SELECT COUNT(*) FROM duty d WHERE d.nurse_id=n.id AND d.day LIKE ?) duties,
          (SELECT COUNT(*) FROM leave l WHERE l.nurse_id=n.id AND l.day LIKE ?) leave_days
        FROM nurse n ORDER BY n.id""", (p, p))]
    return {"month": ym, "duty": duty, "leaves": leaves, "stats": stats}


@app.post("/api/schedule/{ym}/generate")
def regenerate(ym: str):
    y, m = _month(ym)
    c = conn()
    with c:
        _build(c, y, m)
    return schedule(ym)


class LeaveIn(BaseModel):
    nurse_id: int
    day: date
    reason: str = ""


@app.post("/api/leaves")
def add_leave(l: LeaveIn):
    c = conn()
    with c:
        if not c.execute("SELECT 1 FROM nurse WHERE id=?", (l.nurse_id,)).fetchone():
            raise HTTPException(404, "없는 간호사")
        c.execute("INSERT OR REPLACE INTO leave(nurse_id,day,reason) VALUES(?,?,?)",
                  (l.nurse_id, l.day.isoformat(), l.reason))
    return {"ok": True}


@app.delete("/api/leaves")
def del_leave(nurse_id: int, day: date):
    c = conn()
    with c:
        c.execute("DELETE FROM leave WHERE nurse_id=? AND day=?", (nurse_id, day.isoformat()))
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
