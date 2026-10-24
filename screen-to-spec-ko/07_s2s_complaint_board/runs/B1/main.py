import csv
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "civil.db"
STAGES = ["접수", "배정", "처리중", "종결"]

app = FastAPI()


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(BASE / "seed" / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    c = conn()
    c.executescript(
        """
        DROP TABLE IF EXISTS cv_history;
        DROP TABLE IF EXISTS cv_complaints;
        DROP TABLE IF EXISTS cv_staff;
        CREATE TABLE cv_staff(name TEXT PRIMARY KEY, team TEXT);
        CREATE TABLE cv_complaints(
            complaint_id TEXT PRIMARY KEY, title TEXT, category TEXT,
            received TEXT, status TEXT, assignee TEXT, answer TEXT);
        CREATE TABLE cv_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id TEXT,
            from_status TEXT, to_status TEXT, at TEXT, "by" TEXT);
        """
    )
    for r in read_csv("staff.csv"):
        c.execute("INSERT INTO cv_staff VALUES(?,?)", (r["name"].strip(), (r.get("team") or "").strip()))
    for r in read_csv("complaints.csv"):
        c.execute(
            "INSERT INTO cv_complaints VALUES(?,?,?,?,?,?,?)",
            (
                r["complaint_id"].strip(), r["title"], r["category"], r["received"].strip(),
                r["status"].strip(), (r.get("assignee") or "").strip(), r.get("answer") or "",
            ),
        )
    c.commit()
    c.close()


init_db()


def today():
    return date.today()


def shape(row):
    received = date.fromisoformat(row["received"])
    due = received + timedelta(days=7)
    left = (due - today()).days
    return {
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


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((BASE / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/api/staff")
def staff():
    c = conn()
    rows = c.execute("SELECT name, team FROM cv_staff ORDER BY rowid").fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/api/summary")
def summary():
    c = conn()
    rows = [shape(r) for r in c.execute("SELECT * FROM cv_complaints").fetchall()]
    c.close()
    counts = {s: 0 for s in STAGES}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] += 1
    return {"as_of": today().isoformat(), "counts": counts, "overdue": sum(r["overdue"] for r in rows)}


@app.get("/api/complaints")
def complaints(status: str = ""):
    c = conn()
    if status:
        rows = c.execute("SELECT * FROM cv_complaints WHERE status=? ORDER BY rowid", (status,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM cv_complaints ORDER BY rowid").fetchall()
    c.close()
    return {"as_of": today().isoformat(), "items": [shape(r) for r in rows]}


def get_one(c, cid):
    return c.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()


@app.get("/api/complaints/{cid}")
def complaint(cid: str):
    c = conn()
    row = get_one(c, cid)
    c.close()
    if not row:
        return err(404, "민원을 찾을 수 없습니다")
    d = shape(row)
    d["answer"] = row["answer"] or ""
    return d


@app.get("/api/complaints/{cid}/history")
def history(cid: str):
    c = conn()
    if not get_one(c, cid):
        c.close()
        return err(404, "민원을 찾을 수 없습니다")
    rows = c.execute(
        'SELECT from_status, to_status, at, "by" FROM cv_history WHERE complaint_id=? ORDER BY id', (cid,)
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
        names = {r["name"] for r in c.execute("SELECT name FROM cv_staff")}
        # R7: 400 입력 오류 -> 404 -> 409
        if to not in STAGES:
            return err(400, "이동할 단계를 선택하세요")
        if by not in names:
            return err(400, "처리자를 선택하세요")
        if to == "배정" and assignee not in names:
            return err(400, "담당자를 선택하세요")
        if to == "종결" and not answer.strip():
            return err(400, "답변을 입력하세요")
        row = get_one(c, cid)
        if not row:
            return err(404, "민원을 찾을 수 없습니다")
        cur = row["status"]
        if cur == "종결":
            return err(409, "종결된 민원입니다")
        ci, ti = STAGES.index(cur), STAGES.index(to)
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
        out = shape(get_one(c, cid))
        out["answer"] = get_one(c, cid)["answer"] or ""
        return out
    finally:
        c.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
