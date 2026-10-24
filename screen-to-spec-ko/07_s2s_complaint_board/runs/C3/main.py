import csv
import datetime as dt
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "civil.db")
STATUSES = ["접수", "배정", "처리중", "종결"]


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


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
    for r in read_csv("staff.csv"):
        c.execute("INSERT INTO cv_staff VALUES(?,?)", (r["name"], r["team"]))
    for r in read_csv("complaints.csv"):
        c.execute(
            "INSERT INTO cv_complaints VALUES(?,?,?,?,?,?,?)",
            (r["complaint_id"], r["title"], r["category"], r["received"], r["status"],
             r.get("assignee") or "", r.get("answer") or ""),
        )
    c.commit()
    c.close()


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


def today():
    return dt.date.today()


def view(row, detail=False):
    received = dt.date.fromisoformat(row["received"])
    due = received + dt.timedelta(days=7)
    left = (due - today()).days
    d = {
        "complaint_id": row["complaint_id"],
        "title": row["title"],
        "category": row["category"],
        "received": row["received"],
        "status": row["status"],
        "assignee": row["assignee"] or "",
        "due": due.isoformat(),
        "days_left": left,
        "overdue": row["status"] != "종결" and left < 0,
    }
    if detail:
        d["answer"] = row["answer"] or ""
    return d


def err(code, msg):
    return JSONResponse({"detail": msg}, status_code=code)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


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
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"as_of": today().isoformat(), "counts": counts, "overdue": sum(1 for r in rows if r["overdue"])}


@app.get("/api/complaints")
def complaints(status: str = ""):
    c = conn()
    if status:
        cur = c.execute("SELECT * FROM cv_complaints WHERE status=? ORDER BY complaint_id", (status,))
    else:
        cur = c.execute("SELECT * FROM cv_complaints ORDER BY complaint_id")
    items = [view(r) for r in cur]
    c.close()
    return {"as_of": today().isoformat(), "items": items}


@app.get("/api/complaints/{cid}")
def complaint(cid: str):
    c = conn()
    row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    c.close()
    if not row:
        return err(404, "민원을 찾을 수 없습니다")
    return view(row, True)


@app.get("/api/complaints/{cid}/history")
def history(cid: str):
    c = conn()
    if not c.execute("SELECT 1 FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone():
        c.close()
        return err(404, "민원을 찾을 수 없습니다")
    rows = [
        {"from_status": r["from_status"], "to_status": r["to_status"], "at": r["at"], "by": r["by"]}
        for r in c.execute("SELECT * FROM cv_history WHERE complaint_id=? ORDER BY id", (cid,))
    ]
    c.close()
    return rows


@app.post("/api/complaints/{cid}/transition")
async def transition(cid: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        body = {}

    def text(k):
        v = body.get(k)
        return v if isinstance(v, str) else ""

    to, by, assignee, answer = text("to"), text("by"), text("assignee"), text("answer")
    c = conn()
    try:
        names = {r["name"] for r in c.execute("SELECT name FROM cv_staff")}
        # R7: 400 -> 404 -> 409
        if to not in STATUSES:
            return err(400, "단계를 선택하세요")
        if by not in names:
            return err(400, "처리자를 선택하세요")
        if to == "배정" and assignee not in names:
            return err(400, "담당자를 선택하세요")
        if to == "종결" and not answer.strip():
            return err(400, "답변을 입력하세요")
        row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        if not row:
            return err(404, "민원을 찾을 수 없습니다")
        cur = STATUSES.index(row["status"])
        nxt = STATUSES.index(to)
        if cur == 3:
            return err(409, "종결된 민원입니다")
        if nxt < cur:
            return err(409, "상태를 되돌릴 수 없습니다")
        if nxt > cur + 1 or nxt == cur:
            return err(409, "단계를 건너뛸 수 없습니다")
        new_assignee = assignee if to == "배정" else row["assignee"]
        new_answer = answer.strip() if to == "종결" else row["answer"]
        c.execute(
            "UPDATE cv_complaints SET status=?, assignee=?, answer=? WHERE complaint_id=?",
            (to, new_assignee, new_answer, cid),
        )
        c.execute(
            "INSERT INTO cv_history(complaint_id, from_status, to_status, at, by) VALUES(?,?,?,?,?)",
            (cid, row["status"], to, dt.datetime.now().strftime("%Y-%m-%d %H:%M"), by),
        )
        c.commit()
        row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        return view(row, True)
    finally:
        c.close()
