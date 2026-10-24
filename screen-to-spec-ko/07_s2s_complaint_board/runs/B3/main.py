import csv
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "civil.db"
STATUSES = ["접수", "배정", "처리중", "종결"]

app = FastAPI()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE cv_staff (name TEXT PRIMARY KEY, team TEXT);
        CREATE TABLE cv_complaints (
            complaint_id INTEGER PRIMARY KEY, title TEXT, category TEXT,
            received TEXT, status TEXT, assignee TEXT, answer TEXT);
        CREATE TABLE cv_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, complaint_id INTEGER,
            from_status TEXT, to_status TEXT, at TEXT, "by" TEXT);
        """
    )
    with open(BASE / "seed" / "staff.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            conn.execute("INSERT INTO cv_staff VALUES (?,?)", (r["name"].strip(), r["team"].strip()))
    with open(BASE / "seed" / "complaints.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            conn.execute(
                "INSERT INTO cv_complaints VALUES (?,?,?,?,?,?,?)",
                (int(r["complaint_id"]), r["title"], r["category"], r["received"].strip(),
                 r["status"].strip(), (r["assignee"] or "").strip(), r["answer"] or ""),
            )
    conn.commit()
    conn.close()


init_db()


def view(row, with_answer=False):
    due = date.fromisoformat(row["received"]) + timedelta(days=7)
    left = (due - date.today()).days
    out = {
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
    if with_answer:
        out["answer"] = row["answer"] or ""
    return out


def reject(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/api/staff")
def staff():
    conn = connect()
    rows = conn.execute("SELECT name, team FROM cv_staff ORDER BY rowid").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/summary")
def summary():
    conn = connect()
    rows = conn.execute("SELECT * FROM cv_complaints").fetchall()
    conn.close()
    counts = {s: 0 for s in STATUSES}
    overdue = 0
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if view(r)["overdue"]:
            overdue += 1
    return {"as_of": date.today().isoformat(), "counts": counts, "overdue": overdue}


@app.get("/api/complaints")
def complaints(status: str = ""):
    conn = connect()
    if status:
        rows = conn.execute(
            "SELECT * FROM cv_complaints WHERE status=? ORDER BY complaint_id", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM cv_complaints ORDER BY complaint_id").fetchall()
    conn.close()
    return {"as_of": date.today().isoformat(), "items": [view(r) for r in rows]}


@app.get("/api/complaints/{cid}")
def complaint(cid: int):
    conn = connect()
    row = conn.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        return reject(404, "민원을 찾을 수 없습니다")
    return view(row, True)


@app.get("/api/complaints/{cid}/history")
def history(cid: int):
    conn = connect()
    row = conn.execute("SELECT 1 FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
    if not row:
        conn.close()
        return reject(404, "민원을 찾을 수 없습니다")
    rows = conn.execute(
        'SELECT from_status, to_status, at, "by" AS by FROM cv_history WHERE complaint_id=? ORDER BY id',
        (cid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/complaints/{cid}/transition")
async def transition(cid: int, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        body = {}

    def text(key):
        v = body.get(key)
        return v.strip() if isinstance(v, str) else ""

    to, by, assignee, answer = text("to"), text("by"), text("assignee"), text("answer")

    conn = connect()
    try:
        names = {r["name"] for r in conn.execute("SELECT name FROM cv_staff")}
        # R7: 400 -> 404 -> 409
        if to not in STATUSES:
            return reject(400, "이동할 단계를 선택하세요")
        if by not in names:
            return reject(400, "처리자를 선택하세요")
        if to == "배정" and assignee not in names:
            return reject(400, "담당자를 선택하세요")
        if to == "종결" and not answer:
            return reject(400, "답변을 입력하세요")
        row = conn.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        if not row:
            return reject(404, "민원을 찾을 수 없습니다")
        cur = row["status"]
        if cur == "종결":
            return reject(409, "종결된 민원입니다")
        diff = STATUSES.index(to) - STATUSES.index(cur)
        if diff <= 0:
            return reject(409, "상태를 되돌릴 수 없습니다")
        if diff > 1:
            return reject(409, "단계를 건너뛸 수 없습니다")
        new_assignee = assignee if to == "배정" else row["assignee"]
        new_answer = answer if to == "종결" else row["answer"]
        conn.execute(
            "UPDATE cv_complaints SET status=?, assignee=?, answer=? WHERE complaint_id=?",
            (to, new_assignee, new_answer, cid))
        conn.execute(
            'INSERT INTO cv_history (complaint_id, from_status, to_status, at, "by") VALUES (?,?,?,?,?)',
            (cid, cur, to, datetime.now().strftime("%Y-%m-%d %H:%M"), by))
        conn.commit()
        row = conn.execute("SELECT * FROM cv_complaints WHERE complaint_id=?", (cid,)).fetchone()
        return view(row, True)
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
