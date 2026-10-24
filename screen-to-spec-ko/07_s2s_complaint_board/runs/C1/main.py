import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "civil.db")
STATUSES = ["접수", "배정", "처리중", "종결"]

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
        CREATE TABLE cv_staff (name TEXT PRIMARY KEY, team TEXT);
        CREATE TABLE cv_complaints (
            complaint_id TEXT PRIMARY KEY, title TEXT, category TEXT, received TEXT,
            status TEXT, assignee TEXT, answer TEXT);
        CREATE TABLE cv_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id TEXT,
            from_status TEXT, to_status TEXT, at TEXT, "by" TEXT);
        """
    )
    with open(os.path.join(BASE, "seed", "staff.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO cv_staff VALUES (?,?)", (r["name"].strip(), r["team"].strip()))
    with open(os.path.join(BASE, "seed", "complaints.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute(
                "INSERT INTO cv_complaints VALUES (?,?,?,?,?,?,?)",
                (r["complaint_id"].strip(), r["title"], r["category"], r["received"].strip(),
                 r["status"].strip(), r["assignee"] or "", r["answer"] or ""),
            )
    c.commit()
    c.close()


init_db()


def today():
    return dt.date.today()


def view(row, with_answer=False):
    received = dt.date.fromisoformat(row["received"])
    due = received + dt.timedelta(days=7)
    left = (due - today()).days
    d = {
        "complaint_id": row["complaint_id"], "title": row["title"], "category": row["category"],
        "received": row["received"], "status": row["status"], "assignee": row["assignee"],
        "due": due.isoformat(), "days_left": left,
        "overdue": row["status"] != "종결" and left < 0,
    }
    if with_answer:
        d["answer"] = row["answer"]
    return d


def err(code, detail):
    return JSONResponse(status_code=code, content={"detail": detail})


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/staff")
def staff():
    c = conn()
    rows = c.execute("SELECT name, team FROM cv_staff ORDER BY rowid").fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/api/summary")
def summary():
    c = conn()
    rows = [view(r) for r in c.execute("SELECT * FROM cv_complaints").fetchall()]
    c.close()
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] += 1
    return {"as_of": today().isoformat(), "counts": counts, "overdue": sum(1 for r in rows if r["overdue"])}


@app.get("/api/complaints")
def complaints(status: str = ""):
    c = conn()
    if status:
        rows = c.execute("SELECT * FROM cv_complaints WHERE status=? ORDER BY rowid", (status,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM cv_complaints ORDER BY rowid").fetchall()
    c.close()
    return {"as_of": today().isoformat(), "items": [view(r) for r in rows]}


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
    rows = c.execute(
        'SELECT from_status, to_status, at, "by" AS by FROM cv_history WHERE complaint_id=? ORDER BY id', (cid,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


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
        # R7: 400 → 404 → 409
        if to not in STATUSES:
            return err(400, "이동할 단계를 선택하세요")
        if not c.execute("SELECT 1 FROM cv_staff WHERE name=?", (by,)).fetchone():
            return err(400, "처리자를 선택하세요")
        if to == "배정" and not c.execute("SELECT 1 FROM cv_staff WHERE name=?", (assignee,)).fetchone():
            return err(400, "담당자를 선택하세요")
        if to == "종결" and not answer.strip():
            return err(400, "답변을 입력하세요")
        row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        if not row:
            return err(404, "민원을 찾을 수 없습니다")
        cur = row["status"]
        if cur == "종결":
            return err(409, "종결된 민원입니다")
        diff = STATUSES.index(to) - STATUSES.index(cur)
        if diff <= 0:
            return err(409, "상태를 되돌릴 수 없습니다")
        if diff > 1:
            return err(409, "단계를 건너뛸 수 없습니다")
        if to == "배정":
            c.execute("UPDATE cv_complaints SET status=?, assignee=? WHERE complaint_id=?", (to, assignee, cid))
        elif to == "종결":
            c.execute("UPDATE cv_complaints SET status=?, answer=? WHERE complaint_id=?", (to, answer, cid))
        else:
            c.execute("UPDATE cv_complaints SET status=? WHERE complaint_id=?", (to, cid))
        c.execute(
            'INSERT INTO cv_history (complaint_id, from_status, to_status, at, "by") VALUES (?,?,?,?,?)',
            (cid, cur, to, dt.datetime.now().strftime("%Y-%m-%d %H:%M"), by),
        )
        c.commit()
        row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        return view(row, True)
    finally:
        c.close()
