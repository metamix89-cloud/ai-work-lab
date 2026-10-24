# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R7 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "civil.db")
FLOW = ["접수", "배정", "처리중", "종결"]
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE cv_staff(name TEXT PRIMARY KEY, team TEXT);
    CREATE TABLE cv_complaints(complaint_id TEXT PRIMARY KEY, title TEXT, category TEXT, received TEXT, status TEXT, assignee TEXT, answer TEXT);
    CREATE TABLE cv_history(id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id TEXT, from_status TEXT, to_status TEXT, at TEXT, by TEXT);""")
    for name, table, n in (("staff.csv", "cv_staff", 2), ("complaints.csv", "cv_complaints", 7)):
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


def view(r, today):
    d = dict(r)
    due = dt.date.fromisoformat(d["received"]) + dt.timedelta(days=7)
    d["due"] = due.isoformat()
    d["days_left"] = (due - today).days
    d["overdue"] = d["status"] != "종결" and today > due
    return d


class Move(BaseModel):
    to: str = ""
    by: str = ""
    assignee: str = ""
    answer: str = ""


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/staff")
def staff():
    return [dict(r) for r in con().execute("SELECT * FROM cv_staff")]


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    rows = [view(r, today) for r in con().execute("SELECT * FROM cv_complaints")]
    return {"as_of": today.isoformat(), "counts": {s: sum(1 for r in rows if r["status"] == s) for s in FLOW},
            "overdue": sum(1 for r in rows if r["overdue"])}


@app.get("/api/complaints")
def complaints(status: str = ""):
    today = dt.date.today()
    q, args = "SELECT * FROM cv_complaints", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    out = [view(r, today) for r in con().execute(q + " ORDER BY received, complaint_id", args)]
    for o in out:
        o.pop("answer", None)
    return {"as_of": today.isoformat(), "items": out}


@app.get("/api/complaints/{cid}")
def complaint(cid: str):
    r = con().execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    if not r:
        raise HTTPException(404, "민원이 없습니다")
    return view(r, dt.date.today())


@app.get("/api/complaints/{cid}/history")
def history(cid: str):
    c = con()
    if not c.execute("SELECT 1 FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone():
        raise HTTPException(404, "민원이 없습니다")
    return [{"from_status": h["from_status"], "to_status": h["to_status"], "at": h["at"], "by": h["by"]}
            for h in c.execute("SELECT * FROM cv_history WHERE complaint_id=? ORDER BY id", (cid,))]


@app.post("/api/complaints/{cid}/transition")
def transition(cid: str, m: Move):
    c = con()
    staff_names = {r["name"] for r in c.execute("SELECT name FROM cv_staff")}
    # R7: 400 → 404 → 409
    if m.to not in FLOW:
        raise HTTPException(400, "알 수 없는 단계입니다")
    if m.by not in staff_names:
        raise HTTPException(400, "처리자를 선택하세요")
    if m.to == "배정" and m.assignee not in staff_names:
        raise HTTPException(400, "담당자를 선택하세요")
    if m.to == "종결" and not m.answer.strip():
        raise HTTPException(400, "답변을 입력하세요")
    r = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    if not r:
        raise HTTPException(404, "민원이 없습니다")
    cur, nxt = FLOW.index(r["status"]), FLOW.index(m.to)
    if r["status"] == "종결":
        raise HTTPException(409, "종결된 민원입니다")
    if nxt <= cur:
        raise HTTPException(409, "상태를 되돌릴 수 없습니다")
    if nxt > cur + 1:
        raise HTTPException(409, "단계를 건너뛸 수 없습니다")
    assignee = m.assignee if m.to == "배정" else r["assignee"]
    answer = m.answer.strip() if m.to == "종결" else r["answer"]
    c.execute("UPDATE cv_complaints SET status=?, assignee=?, answer=? WHERE complaint_id=?", (m.to, assignee, answer, cid))
    c.execute("INSERT INTO cv_history(complaint_id, from_status, to_status, at, by) VALUES (?,?,?,?,?)",
              (cid, r["status"], m.to, dt.datetime.now().strftime("%Y-%m-%d %H:%M"), m.by))
    c.commit()
    return view(c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone(), dt.date.today())
