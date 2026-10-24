import csv
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "onboard.db"
MAX_ATTEMPTS = 3
PASS_SCORE = 80

SCHEMA = """
CREATE TABLE ob_users (user TEXT PRIMARY KEY, role TEXT NOT NULL);
CREATE TABLE ob_lessons (lesson_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, title TEXT NOT NULL);
CREATE TABLE ob_questions (q_id TEXT PRIMARY KEY, text TEXT NOT NULL, choices TEXT NOT NULL, answer INTEGER NOT NULL);
CREATE TABLE ob_progress (user TEXT NOT NULL, lesson_id TEXT NOT NULL, completed_at TEXT NOT NULL,
                          PRIMARY KEY (user, lesson_id));
CREATE TABLE ob_attempts (user TEXT NOT NULL, attempt INTEGER NOT NULL, score INTEGER NOT NULL,
                          passed INTEGER NOT NULL, at TEXT NOT NULL, PRIMARY KEY (user, attempt));
"""


def read_csv(name):
    with open(BASE / "seed" / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO ob_users VALUES (?,?)",
                    [(r["user"], r["role"]) for r in read_csv("users.csv")])
    con.executemany("INSERT INTO ob_lessons VALUES (?,?,?)",
                    [(r["lesson_id"], int(r["seq"]), r["title"]) for r in read_csv("lessons.csv")])
    con.executemany("INSERT INTO ob_questions VALUES (?,?,?,?)",
                    [(r["q_id"], r["text"], r["choices"], int(r["answer"])) for r in read_csv("questions.csv")])
    con.executemany("INSERT INTO ob_progress VALUES (?,?,?)",
                    [(r["user"], r["lesson_id"], r["completed_at"]) for r in read_csv("progress.csv")])
    con.executemany("INSERT INTO ob_attempts VALUES (?,?,?,?,?)",
                    [(r["user"], int(r["attempt"]), int(r["score"]), int(r["passed"]), r["at"])
                     for r in read_csv("attempts.csv")])
    con.commit()
    con.close()


init_db()
app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return JSONResponse({"detail": "입력이 올바르지 않습니다"}, status_code=400)


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def role_of(con, user):
    row = con.execute("SELECT role FROM ob_users WHERE user=?", (user,)).fetchone()
    return row["role"] if row else None


def build_progress(con, user):
    lessons = con.execute("SELECT lesson_id FROM ob_lessons ORDER BY seq").fetchall()
    done = {r["lesson_id"] for r in
            con.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
    states, open_given = [], False
    for l in lessons:
        lid = l["lesson_id"]
        if lid in done:
            state = "done"
        elif not open_given:
            state, open_given = "open", True
        else:
            state = "locked"
        states.append({"lesson_id": lid, "state": state})
    total = len(lessons)
    n_done = sum(1 for s in states if s["state"] == "done")
    progress = n_done * 100 // total if total else 0
    att = con.execute("SELECT COUNT(*) c, COALESCE(MAX(score),0) b, COALESCE(MAX(passed),0) p "
                      "FROM ob_attempts WHERE user=?", (user,)).fetchone()
    passed = bool(att["p"])
    return {
        "user": user,
        "lessons": states,
        "progress": progress,
        "attempts": att["c"],
        "best_score": att["b"],
        "passed": passed,
        "certified": bool(total) and n_done == total and passed,
        "attempts_left": 0 if passed else max(0, MAX_ATTEMPTS - att["c"]),
    }


def clean_str(v):
    return v if isinstance(v, str) and v.strip() else None


async def read_body(request):
    try:
        body = await request.json()
    except Exception:
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    if not isinstance(body, dict):
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    return body


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/users")
def users():
    con = db()
    rows = con.execute("SELECT user, role FROM ob_users ORDER BY rowid").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/lessons")
def lessons():
    con = db()
    rows = con.execute("SELECT lesson_id, seq, title FROM ob_lessons ORDER BY seq").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/quiz")
def quiz():
    con = db()
    rows = con.execute("SELECT q_id, text, choices FROM ob_questions ORDER BY rowid").fetchall()
    con.close()
    return [{"q_id": r["q_id"], "text": r["text"], "choices": r["choices"].split("|")} for r in rows]


@app.get("/api/progress")
def progress(request: Request):
    user = clean_str(request.query_params.get("user"))
    viewer = clean_str(request.query_params.get("viewer"))
    if not user or not viewer:
        raise Reject(400, "user 와 viewer 가 필요합니다")
    con = db()
    try:
        if viewer != user and role_of(con, viewer) != "admin":
            raise Reject(403, "본인 진도만 볼 수 있습니다")
        if role_of(con, user) is None:
            raise Reject(404, "없는 사용자입니다")
        return build_progress(con, user)
    finally:
        con.close()


@app.post("/api/lessons/{lesson_id}/complete")
async def complete(lesson_id: str, request: Request):
    body = await read_body(request)
    user = clean_str(body.get("user"))
    if not user:
        raise Reject(400, "user 가 필요합니다")
    con = db()
    try:
        role = role_of(con, user)
        lesson = con.execute("SELECT seq FROM ob_lessons WHERE lesson_id=?", (lesson_id,)).fetchone()
        if role is None:
            raise Reject(404, "없는 사용자입니다")
        if lesson is None:
            raise Reject(404, "없는 레슨입니다")
        if role != "trainee":
            raise Reject(403, "신입만 레슨을 완료할 수 있습니다")
        done = {r["lesson_id"] for r in
                con.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
        if lesson_id not in done:
            earlier = con.execute("SELECT lesson_id FROM ob_lessons WHERE seq<?", (lesson["seq"],)).fetchall()
            if any(r["lesson_id"] not in done for r in earlier):
                raise Reject(409, "이전 레슨을 먼저 마치세요")
            con.execute("INSERT INTO ob_progress VALUES (?,?,datetime('now','localtime'))",
                        (user, lesson_id))
            con.commit()
        return build_progress(con, user)
    finally:
        con.close()


@app.post("/api/quiz/submit")
async def submit(request: Request):
    body = await read_body(request)
    user = clean_str(body.get("user"))
    answers = body.get("answers")
    con = db()
    try:
        questions = con.execute("SELECT answer FROM ob_questions ORDER BY rowid").fetchall()
        n = len(questions)
        if (not user or not isinstance(answers, list) or len(answers) != n
                or any(type(a) is not int or not 0 <= a <= 3 for a in answers)):
            raise Reject(400, "answers 는 문항 수만큼의 0~3 정수여야 합니다")
        role = role_of(con, user)
        if role is None:
            raise Reject(404, "없는 사용자입니다")
        if role != "trainee":
            raise Reject(403, "신입만 응시할 수 있습니다")
        before = build_progress(con, user)
        if any(s["state"] != "done" for s in before["lessons"]):
            raise Reject(409, "레슨을 모두 마친 뒤 응시할 수 있습니다")
        if before["attempts_left"] <= 0:
            raise Reject(409, "더 응시할 수 없습니다")
        correct = sum(1 for q, a in zip(questions, answers) if q["answer"] == a)
        score = correct * 100 // n
        passed = score >= PASS_SCORE
        attempt = before["attempts"] + 1
        con.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,datetime('now','localtime'))",
                    (user, attempt, score, int(passed)))
        con.commit()
        after = build_progress(con, user)
        return {"score": score, "passed": passed, "attempt": attempt,
                "attempts_left": after["attempts_left"], "certified": after["certified"]}
    finally:
        con.close()


@app.get("/api/admin/incomplete")
def incomplete(request: Request):
    viewer = clean_str(request.query_params.get("viewer"))
    if not viewer:
        raise Reject(400, "viewer 가 필요합니다")
    con = db()
    try:
        if role_of(con, viewer) != "admin":
            raise Reject(403, "관리자만 볼 수 있습니다")
        out = []
        for r in con.execute("SELECT user FROM ob_users WHERE role='trainee'"):
            p = build_progress(con, r["user"])
            if not p["certified"]:
                out.append({"user": p["user"], "progress": p["progress"],
                            "attempts": p["attempts"], "best_score": p["best_score"]})
        out.sort(key=lambda x: (x["progress"], x["user"]))
        return out
    finally:
        con.close()
