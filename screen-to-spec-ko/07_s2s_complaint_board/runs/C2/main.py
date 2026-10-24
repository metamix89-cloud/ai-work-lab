import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "civil.db")
STEPS = ["접수", "배정", "처리중", "종결"]

app = FastAPI()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    c = conn()
    c.executescript(
        """
        CREATE TABLE cv_staff(name TEXT PRIMARY KEY, team TEXT);
        CREATE TABLE cv_complaints(complaint_id TEXT PRIMARY KEY, title TEXT, category TEXT,
            received TEXT, status TEXT, assignee TEXT, answer TEXT);
        CREATE TABLE cv_history(id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id TEXT,
            from_status TEXT, to_status TEXT, at TEXT, by TEXT);
        """
    )
    with open(os.path.join(BASE, "seed", "staff.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO cv_staff VALUES(?,?)", (r["name"], r["team"]))
    with open(os.path.join(BASE, "seed", "complaints.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute(
                "INSERT INTO cv_complaints VALUES(?,?,?,?,?,?,?)",
                (r["complaint_id"], r["title"], r["category"], r["received"], r["status"],
                 r["assignee"] or "", r["answer"] or ""),
            )
    c.commit()
    c.close()


init_db()


def today():
    return dt.date.today()


def view(row, with_answer=False):
    due = dt.date.fromisoformat(row["received"]) + dt.timedelta(days=7)
    left = (due - today()).days
    d = {
        "complaint_id": row["complaint_id"], "title": row["title"], "category": row["category"],
        "received": row["received"], "status": row["status"], "assignee": row["assignee"] or "",
        "due": due.isoformat(), "days_left": left,
        "overdue": row["status"] != "종결" and left < 0,
    }
    if with_answer:
        d["answer"] = row["answer"] or ""
    return d


def reject(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/api/staff")
def staff():
    c = conn()
    rows = [dict(r) for r in c.execute("SELECT name, team FROM cv_staff ORDER BY rowid")]
    c.close()
    return rows


@app.get("/api/summary")
def summary():
    c = conn()
    rows = [view(r) for r in c.execute("SELECT * FROM cv_complaints")]
    c.close()
    counts = {s: 0 for s in STEPS}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"as_of": today().isoformat(), "counts": counts, "overdue": sum(1 for r in rows if r["overdue"])}


@app.get("/api/complaints")
def complaints(status: str = ""):
    c = conn()
    rows = [view(r) for r in c.execute("SELECT * FROM cv_complaints ORDER BY rowid")]
    c.close()
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"as_of": today().isoformat(), "items": rows}


@app.get("/api/complaints/{cid}")
def complaint(cid: str):
    c = conn()
    row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    c.close()
    if not row:
        return reject(404, "민원을 찾을 수 없습니다")
    return view(row, True)


@app.get("/api/complaints/{cid}/history")
def history(cid: str):
    c = conn()
    if not c.execute("SELECT 1 FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone():
        c.close()
        return reject(404, "민원을 찾을 수 없습니다")
    rows = [dict(r) for r in c.execute(
        "SELECT from_status, to_status, at, by FROM cv_history WHERE complaint_id=? ORDER BY id", (cid,))]
    c.close()
    return rows


@app.post("/api/complaints/{cid}/transition")
async def transition(cid: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return reject(400, "요청 형식이 올바르지 않습니다")
    to = body.get("to")
    by = body.get("by")
    assignee = body.get("assignee") or ""
    answer = body.get("answer") or ""
    if not isinstance(assignee, str) or not isinstance(answer, str):
        return reject(400, "요청 형식이 올바르지 않습니다")
    c = conn()
    try:
        names = {r["name"] for r in c.execute("SELECT name FROM cv_staff")}
        if to not in STEPS:
            return reject(400, "단계를 선택하세요")
        if by not in names:
            return reject(400, "처리자를 선택하세요")
        if to == "배정" and assignee not in names:
            return reject(400, "담당자를 선택하세요")
        if to == "종결" and not answer.strip():
            return reject(400, "답변을 입력하세요")
        row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        if not row:
            return reject(404, "민원을 찾을 수 없습니다")
        cur = row["status"]
        if cur == "종결":
            return reject(409, "종결된 민원입니다")
        diff = STEPS.index(to) - STEPS.index(cur)
        if diff <= 0:
            return reject(409, "상태를 되돌릴 수 없습니다")
        if diff > 1:
            return reject(409, "단계를 건너뛸 수 없습니다")
        if to == "배정":
            c.execute("UPDATE cv_complaints SET status=?, assignee=? WHERE complaint_id=?", (to, assignee, cid))
        elif to == "종결":
            c.execute("UPDATE cv_complaints SET status=?, answer=? WHERE complaint_id=?", (to, answer.strip(), cid))
        else:
            c.execute("UPDATE cv_complaints SET status=? WHERE complaint_id=?", (to, cid))
        c.execute(
            "INSERT INTO cv_history(complaint_id, from_status, to_status, at, by) VALUES(?,?,?,?,?)",
            (cid, cur, to, dt.datetime.now().strftime("%Y-%m-%d %H:%M"), by),
        )
        c.commit()
        return view(c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone(), True)
    finally:
        c.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
