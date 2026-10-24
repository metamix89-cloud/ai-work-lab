import csv
import os
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "onboard.db")
MAX_ATTEMPTS = 3
PASS_SCORE = 80

app = FastAPI()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request: Request, exc: Reject):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


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
    c.executescript("""
        CREATE TABLE ob_users (user TEXT PRIMARY KEY, role TEXT);
        CREATE TABLE ob_lessons (lesson_id TEXT PRIMARY KEY, seq INTEGER, title TEXT);
        CREATE TABLE ob_questions (q_id TEXT PRIMARY KEY, text TEXT, choices TEXT, answer INTEGER);
        CREATE TABLE ob_progress (user TEXT, lesson_id TEXT, completed_at TEXT, PRIMARY KEY (user, lesson_id));
        CREATE TABLE ob_attempts (user TEXT, attempt INTEGER, score INTEGER, passed INTEGER, at TEXT);
    """)
    c.executemany("INSERT INTO ob_users VALUES (?,?)", [(r["user"], r["role"]) for r in read_csv("users.csv")])
    c.executemany("INSERT INTO ob_lessons VALUES (?,?,?)",
                  [(r["lesson_id"], int(r["seq"]), r["title"]) for r in read_csv("lessons.csv")])
    c.executemany("INSERT INTO ob_questions VALUES (?,?,?,?)",
                  [(r["q_id"], r["text"], r["choices"], int(r["answer"])) for r in read_csv("questions.csv")])
    c.executemany("INSERT OR IGNORE INTO ob_progress VALUES (?,?,?)",
                  [(r["user"], r["lesson_id"], r["completed_at"]) for r in read_csv("progress.csv")])
    c.executemany("INSERT INTO ob_attempts VALUES (?,?,?,?,?)",
                  [(r["user"], int(r["attempt"]), int(r["score"]), int(r["passed"]), r["at"])
                   for r in read_csv("attempts.csv")])
    c.commit()
    c.close()


init_db()


def get_user(c, name):
    return c.execute("SELECT * FROM ob_users WHERE user=?", (name,)).fetchone()


def build_progress(c, name):
    lessons = c.execute("SELECT lesson_id FROM ob_lessons ORDER BY seq").fetchall()
    done = {r["lesson_id"] for r in c.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (name,))}
    out, opened = [], False
    for l in lessons:
        lid = l["lesson_id"]
        if lid in done:
            state = "done"
        elif not opened:
            state, opened = "open", True
        else:
            state = "locked"
        out.append({"lesson_id": lid, "state": state})
    n_done = sum(1 for x in out if x["state"] == "done")
    total = len(out)
    pct = n_done * 100 // total if total else 0
    att = c.execute("SELECT score, passed FROM ob_attempts WHERE user=?", (name,)).fetchall()
    passed = any(a["passed"] for a in att)
    return {
        "user": name,
        "lessons": out,
        "progress": pct,
        "attempts": len(att),
        "best_score": max((a["score"] for a in att), default=0),
        "passed": passed,
        "certified": bool(total) and n_done == total and passed,
        "attempts_left": max(0, MAX_ATTEMPTS - len(att)),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    c = conn()
    rows = c.execute("SELECT user, role FROM ob_users").fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/api/lessons")
def lessons():
    c = conn()
    rows = c.execute("SELECT lesson_id, seq, title FROM ob_lessons ORDER BY seq").fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.get("/api/quiz")
def quiz():
    c = conn()
    rows = c.execute("SELECT q_id, text, choices FROM ob_questions ORDER BY q_id").fetchall()
    c.close()
    return [{"q_id": r["q_id"], "text": r["text"], "choices": r["choices"].split("|")} for r in rows]


@app.get("/api/progress")
def progress(user: str = "", viewer: str = ""):
    if not user or not viewer:
        raise Reject(400, "user 와 viewer 가 필요합니다")
    c = conn()
    try:
        if viewer != user:
            v = get_user(c, viewer)
            if not v or v["role"] != "admin":
                raise Reject(403, "본인 진도만 볼 수 있습니다")
        if not get_user(c, user):
            raise Reject(404, "없는 사용자입니다")
        return build_progress(c, user)
    finally:
        c.close()


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        b = None
    return b if isinstance(b, dict) else {}


@app.post("/api/lessons/{lesson_id}/complete")
async def complete(lesson_id: str, request: Request):
    body = await body_of(request)
    name = body.get("user")
    if not isinstance(name, str) or not name:
        raise Reject(400, "user 가 필요합니다")
    c = conn()
    try:
        if not get_user(c, name):
            raise Reject(404, "없는 사용자입니다")
        if not c.execute("SELECT 1 FROM ob_lessons WHERE lesson_id=?", (lesson_id,)).fetchone():
            raise Reject(404, "없는 레슨입니다")
        states = {x["lesson_id"]: x["state"] for x in build_progress(c, name)["lessons"]}
        if states[lesson_id] == "locked":
            raise Reject(409, "이전 레슨을 먼저 마치세요")
        if states[lesson_id] == "open":
            c.execute("INSERT INTO ob_progress VALUES (?,?,?)",
                      (name, lesson_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
            c.commit()
        return build_progress(c, name)
    finally:
        c.close()


@app.post("/api/quiz/submit")
async def submit(request: Request):
    body = await body_of(request)
    name = body.get("user")
    answers = body.get("answers")
    c = conn()
    try:
        answer_key = [r["answer"] for r in c.execute("SELECT answer FROM ob_questions ORDER BY q_id")]
        if (not isinstance(name, str) or not name or not isinstance(answers, list)
                or len(answers) != len(answer_key)
                or any(type(a) is not int or not 0 <= a <= 3 for a in answers)):
            raise Reject(400, "answers 는 문항 수만큼의 0~3 정수여야 합니다")
        if not get_user(c, name):
            raise Reject(404, "없는 사용자입니다")
        p = build_progress(c, name)
        if any(x["state"] != "done" for x in p["lessons"]):
            raise Reject(409, "레슨을 모두 마친 뒤 응시할 수 있습니다")
        if p["passed"] or p["attempts"] >= MAX_ATTEMPTS:
            raise Reject(409, "더 응시할 수 없습니다")
        right = sum(1 for a, k in zip(answers, answer_key) if a == k)
        score = right * 100 // len(answer_key)
        passed = score >= PASS_SCORE
        attempt = p["attempts"] + 1
        c.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,?)",
                  (name, attempt, score, int(passed), datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()
        return {"score": score, "passed": passed, "attempt": attempt,
                "attempts_left": MAX_ATTEMPTS - attempt, "certified": passed}
    finally:
        c.close()


@app.get("/api/admin/incomplete")
def incomplete(viewer: str = ""):
    c = conn()
    try:
        v = get_user(c, viewer) if viewer else None
        if not v or v["role"] != "admin":
            raise Reject(403, "관리자만 볼 수 있습니다")
        rows = []
        for u in c.execute("SELECT user FROM ob_users WHERE role='trainee'").fetchall():
            p = build_progress(c, u["user"])
            if not p["certified"]:
                rows.append({"user": u["user"], "progress": p["progress"],
                             "attempts": p["attempts"], "best_score": p["best_score"]})
        rows.sort(key=lambda r: (r["progress"], r["user"]))
        return rows
    finally:
        c.close()
