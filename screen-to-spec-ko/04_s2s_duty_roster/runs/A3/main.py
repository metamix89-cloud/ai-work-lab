import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import scheduler

BASE = Path(__file__).parent
DB = BASE / "duty.db"
app = FastAPI(title="한빛요양병원 3병동 야간 당직표")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS nurses(id INTEGER PRIMARY KEY, name TEXT NOT NULL, position TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS leaves(
            nurse_id INTEGER NOT NULL REFERENCES nurses(id) ON DELETE CASCADE,
            day TEXT NOT NULL, PRIMARY KEY(nurse_id, day));
        CREATE TABLE IF NOT EXISTS duty(day TEXT PRIMARY KEY, nurse_id INTEGER REFERENCES nurses(id));
        """)
        if c.execute("SELECT COUNT(*) FROM nurses").fetchone()[0]:
            return
        c.executemany("INSERT INTO nurses(id,name,position) VALUES(?,?,?)", [
            (1, "김서연", "수간호사"), (2, "이지민", "책임간호사"), (3, "박하늘", "간호사"),
            (4, "최유진", "간호사"), (5, "정민호", "간호사"), (6, "한소라", "간호사")])
        c.executemany("INSERT INTO leaves VALUES(?,?)",
                      [(3, f"2026-10-{d:02d}") for d in range(12, 17)]      # 박하늘 10/12~16
                      + [(5, f"2026-10-{d:02d}") for d in (21, 22, 23)]      # 정민호 10/21~23
                      + [(2, f"2026-11-{d:02d}") for d in range(2, 7)]       # 이지민 11/2~6
                      + [(6, f"2026-11-{d:02d}") for d in range(16, 21)])    # 한소라 11/16~20
        for m in ("2026-10", "2026-11"):
            save(c, m)


def save(c, month):
    ids = [r["id"] for r in c.execute("SELECT id FROM nurses ORDER BY id")]
    leaves = {i: set() for i in ids}
    for r in c.execute("SELECT nurse_id, day FROM leaves WHERE day LIKE ?", (month + "-%",)):
        leaves[r["nurse_id"]].add(r["day"])
    res = scheduler.generate(month, ids, leaves)
    c.execute("DELETE FROM duty WHERE day LIKE ?", (month + "-%",))
    c.executemany("INSERT INTO duty VALUES(?,?)", res.items())


def check_month(month):
    try:
        date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(400, "month는 YYYY-MM 형식이어야 합니다")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/nurses")
def nurses():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM nurses ORDER BY id")]


@app.get("/api/schedule")
def get_schedule(month: str):
    check_month(month)
    with conn() as c:
        duty = {r["day"]: r["nurse_id"] for r in c.execute("SELECT * FROM duty WHERE day LIKE ?", (month + "-%",))}
        leaves = [dict(r) for r in c.execute(
            "SELECT nurse_id, day FROM leaves WHERE day LIKE ? ORDER BY day", (month + "-%",))]
    days = scheduler.month_days(month)
    stats = {}
    for n in nurses():
        mine = [d for d in days if duty.get(d.isoformat()) == n["id"]]
        stats[n["id"]] = {"total": len(mine), "heavy": sum(scheduler.is_heavy(d) for d in mine),
                          "leave": sum(1 for l in leaves if l["nurse_id"] == n["id"])}
    return {"month": month, "duty": duty, "leaves": leaves, "stats": stats,
            "holidays": sorted(h for h in scheduler.HOLIDAYS if h.startswith(month))}


@app.post("/api/schedule/generate")
def generate(month: str):
    check_month(month)
    with conn() as c:
        save(c, month)
    return get_schedule(month)


class Leave(BaseModel):
    nurse_id: int
    day: date


@app.post("/api/leaves")
def add_leave(l: Leave):
    with conn() as c:
        if not c.execute("SELECT 1 FROM nurses WHERE id=?", (l.nurse_id,)).fetchone():
            raise HTTPException(404, "없는 간호사입니다")
        c.execute("INSERT OR IGNORE INTO leaves VALUES(?,?)", (l.nurse_id, l.day.isoformat()))
        save(c, l.day.isoformat()[:7])  # 휴가가 바뀌면 해당 월 자동 재배정
    return get_schedule(l.day.isoformat()[:7])


@app.delete("/api/leaves")
def del_leave(nurse_id: int, day: date):
    with conn() as c:
        c.execute("DELETE FROM leaves WHERE nurse_id=? AND day=?", (nurse_id, day.isoformat()))
        save(c, day.isoformat()[:7])
    return get_schedule(day.isoformat()[:7])


init_db()
