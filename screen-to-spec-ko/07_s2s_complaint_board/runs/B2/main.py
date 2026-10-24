import csv
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "civil.db"
STATUSES = ["접수", "배정", "처리중", "종결"]

app = FastAPI()


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    for suffix in ("", "-journal"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    c = conn()
    c.executescript(
        """
        CREATE TABLE cv_staff(name TEXT PRIMARY KEY, team TEXT);
        CREATE TABLE cv_complaints(
            complaint_id TEXT PRIMARY KEY, title TEXT, category TEXT,
            received TEXT, status TEXT, assignee TEXT, answer TEXT);
        CREATE TABLE cv_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT, from_status TEXT, to_status TEXT, at TEXT, "by" TEXT);
        """
    )
    with open(BASE / "seed" / "staff.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO cv_staff VALUES(?,?)", (r["name"].strip(), r["team"].strip()))
    with open(BASE / "seed" / "complaints.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute(
                "INSERT INTO cv_complaints VALUES(?,?,?,?,?,?,?)",
                (r["complaint_id"].strip(), r["title"], r["category"], r["received"].strip(),
                 r["status"].strip(), (r["assignee"] or "").strip(), r["answer"] or ""),
            )
    c.commit()
    c.close()


init_db()


def today():
    return date.today()


def view(row, as_of):
    received = date.fromisoformat(row["received"])
    due = received + timedelta(days=7)
    return {
        "complaint_id": row["complaint_id"],
        "title": row["title"],
        "category": row["category"],
        "received": row["received"],
        "status": row["status"],
        "assignee": row["assignee"] or "",
        "due": due.isoformat(),
        "days_left": (due - as_of).days,
        "overdue": row["status"] != "종결" and as_of > due,
    }


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/staff")
def staff():
    c = conn()
    rows = c.execute("SELECT name, team FROM cv_staff ORDER BY rowid").fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/api/summary")
def summary():
    as_of = today()
    c = conn()
    rows = c.execute("SELECT * FROM cv_complaints").fetchall()
    c.close()
    counts = {s: 0 for s in STATUSES}
    overdue = 0
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] += 1
        if view(r, as_of)["overdue"]:
            overdue += 1
    return {"as_of": as_of.isoformat(), "counts": counts, "overdue": overdue}


@app.get("/api/complaints")
def complaints(status: str = ""):
    as_of = today()
    c = conn()
    if status:
        rows = c.execute("SELECT * FROM cv_complaints WHERE status=? ORDER BY received, complaint_id", (status,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM cv_complaints ORDER BY received, complaint_id").fetchall()
    c.close()
    return {"as_of": as_of.isoformat(), "items": [view(r, as_of) for r in rows]}


@app.get("/api/complaints/{cid}")
def complaint(cid: str):
    c = conn()
    r = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    c.close()
    if not r:
        return err(404, "민원을 찾을 수 없습니다")
    d = view(r, today())
    d["answer"] = r["answer"] or ""
    return d


@app.get("/api/complaints/{cid}/history")
def history(cid: str):
    c = conn()
    r = c.execute("SELECT 1 FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    if not r:
        c.close()
        return err(404, "민원을 찾을 수 없습니다")
    rows = c.execute(
        'SELECT from_status, to_status, at, "by" FROM cv_history WHERE complaint_id=? ORDER BY id', (cid,)
    ).fetchall()
    c.close()
    return [dict(x) for x in rows]


@app.post("/api/complaints/{cid}/transition")
async def transition(cid: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return err(400, "요청 본문이 올바르지 않습니다")

    def text(k):
        v = body.get(k)
        return v if isinstance(v, str) else ""

    to, by, assignee, answer = text("to"), text("by"), text("assignee"), text("answer")
    c = conn()
    try:
        names = {r["name"] for r in c.execute("SELECT name FROM cv_staff")}
        # R7: 400 -> 404 -> 409
        if to not in STATUSES:
            return err(400, "이동할 단계가 올바르지 않습니다")
        if by not in names:
            return err(400, "처리자를 선택하세요")
        if to == "배정" and assignee not in names:
            return err(400, "담당자를 선택하세요")
        if to == "종결" and not answer.strip():
            return err(400, "답변을 입력하세요")
        row = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        if not row:
            return err(404, "민원을 찾을 수 없습니다")
        cur = row["status"]
        if cur == "종결":
            return err(409, "종결된 민원입니다")
        ci, ti = STATUSES.index(cur), STATUSES.index(to)
        if ti <= ci:
            return err(409, "상태를 되돌릴 수 없습니다")
        if ti > ci + 1:
            return err(409, "단계를 건너뛸 수 없습니다")
        if to == "배정":
            c.execute("UPDATE cv_complaints SET status=?, assignee=? WHERE complaint_id=?", (to, assignee, cid))
        elif to == "종결":
            c.execute("UPDATE cv_complaints SET status=?, answer=? WHERE complaint_id=?", (to, answer.strip(), cid))
        else:
            c.execute("UPDATE cv_complaints SET status=? WHERE complaint_id=?", (to, cid))
        c.execute(
            'INSERT INTO cv_history(complaint_id, from_status, to_status, at, "by") VALUES(?,?,?,?,?)',
            (cid, cur, to, datetime.now().strftime("%Y-%m-%d %H:%M"), by),
        )
        c.commit()
        r = c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        d = view(r, today())
        d["answer"] = r["answer"] or ""
        return d
    finally:
        c.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
