import csv
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "onboard.db")
MAX_ATTEMPTS = 3
PASS_SCORE = 80

SCHEMA = """
CREATE TABLE ob_users (user TEXT PRIMARY KEY, role TEXT NOT NULL);
CREATE TABLE ob_lessons (lesson_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, title TEXT NOT NULL);
CREATE TABLE ob_questions (q_id TEXT PRIMARY KEY, text TEXT NOT NULL, choices TEXT NOT NULL, answer INTEGER NOT NULL);
CREATE TABLE ob_progress (user TEXT NOT NULL, lesson_id TEXT NOT NULL, completed_at TEXT NOT NULL, PRIMARY KEY (user, lesson_id));
CREATE TABLE ob_attempts (user TEXT NOT NULL, attempt INTEGER NOT NULL, score INTEGER NOT NULL, passed INTEGER NOT NULL, at TEXT NOT NULL, PRIMARY KEY (user, attempt));
"""


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def reset_db():
    """seed/ CSV 로 SQLite 를 새로 만든다."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
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


@asynccontextmanager
async def lifespan(app):
    reset_db()
    yield


app = FastAPI(lifespan=lifespan)
reset_db()


@app.exception_handler(StarletteHTTPException)
async def http_exc(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exc(request, exc):
    return JSONResponse({"detail": "입력이 올바르지 않습니다"}, status_code=400)


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def get_role(con, user):
    row = con.execute("SELECT role FROM ob_users WHERE user=?", (user,)).fetchone()
    return row["role"] if row else None


def build_progress(con, user):
    lessons = con.execute("SELECT lesson_id FROM ob_lessons ORDER BY seq").fetchall()
    done = {r["lesson_id"] for r in con.execute(
        "SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
    states, opened = [], False
    for l in lessons:
        lid = l["lesson_id"]
        if lid in done:
            state = "done"
        elif not opened:
            state, opened = "open", True
        else:
            state = "locked"
        states.append({"lesson_id": lid, "state": state})
    total = len(lessons)
    ndone = sum(1 for s in states if s["state"] == "done")
    progress = ndone * 100 // total if total else 0
    att = con.execute(
        "SELECT COUNT(*) c, MAX(score) b, MAX(passed) p FROM ob_attempts WHERE user=?", (user,)).fetchone()
    attempts = att["c"]
    passed = bool(att["p"])
    return {
        "user": user,
        "lessons": states,
        "progress": progress,
        "attempts": attempts,
        "best_score": att["b"] if attempts else None,
        "passed": passed,
        "certified": bool(total) and ndone == total and passed,
        "attempts_left": max(MAX_ATTEMPTS - attempts, 0),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    con = db()
    try:
        return [{"user": r["user"], "role": r["role"]}
                for r in con.execute("SELECT user, role FROM ob_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/lessons")
def lessons():
    con = db()
    try:
        return [{"lesson_id": r["lesson_id"], "seq": r["seq"], "title": r["title"]}
                for r in con.execute("SELECT * FROM ob_lessons ORDER BY seq")]
    finally:
        con.close()


@app.get("/api/quiz")
def quiz():
    con = db()
    try:
        return [{"q_id": r["q_id"], "text": r["text"], "choices": r["choices"].split("|")}
                for r in con.execute("SELECT q_id, text, choices FROM ob_questions ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/progress")
def progress(user: str = None, viewer: str = None):
    if not user or not viewer:
        raise HTTPException(400, "user 와 viewer 가 필요합니다")
    con = db()
    try:
        if viewer != user and get_role(con, viewer) != "admin":
            raise HTTPException(403, "본인 진도만 볼 수 있습니다")
        if get_role(con, user) is None:
            raise HTTPException(404, "없는 사용자입니다")
        return build_progress(con, user)
    finally:
        con.close()


async def read_body(request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "본문이 올바른 JSON 이 아닙니다")
    if not isinstance(body, dict):
        raise HTTPException(400, "본문이 올바르지 않습니다")
    return body


@app.post("/api/lessons/{lesson_id}/complete")
async def complete(lesson_id: str, request: Request):
    body = await read_body(request)
    user = body.get("user")
    if not isinstance(user, str) or not user:
        raise HTTPException(400, "user 가 필요합니다")
    con = db()
    try:
        if get_role(con, user) is None:
            raise HTTPException(404, "없는 사용자입니다")
        lesson = con.execute("SELECT seq FROM ob_lessons WHERE lesson_id=?", (lesson_id,)).fetchone()
        if lesson is None:
            raise HTTPException(404, "없는 레슨입니다")
        done = {r["lesson_id"] for r in con.execute(
            "SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
        if lesson_id not in done:
            earlier = [r["lesson_id"] for r in con.execute(
                "SELECT lesson_id FROM ob_lessons WHERE seq<?", (lesson["seq"],))]
            if any(e not in done for e in earlier):
                raise HTTPException(409, "이전 레슨을 먼저 마치세요")
            con.execute("INSERT INTO ob_progress VALUES (?,?,?)",
                        (user, lesson_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
            con.commit()
        return build_progress(con, user)
    finally:
        con.close()


@app.post("/api/quiz/submit")
async def submit(request: Request):
    body = await read_body(request)
    user = body.get("user")
    answers = body.get("answers")
    if not isinstance(user, str) or not user:
        raise HTTPException(400, "user 가 필요합니다")
    con = db()
    try:
        questions = con.execute("SELECT answer FROM ob_questions ORDER BY rowid").fetchall()
        if (not isinstance(answers, list) or len(answers) != len(questions)
                or any(type(a) is not int or not 0 <= a <= 3 for a in answers)):
            raise HTTPException(400, "answers 는 문항 수만큼의 0~3 정수여야 합니다")
        if get_role(con, user) is None:
            raise HTTPException(404, "없는 사용자입니다")
        prog = build_progress(con, user)
        if any(l["state"] != "done" for l in prog["lessons"]):
            raise HTTPException(409, "레슨을 모두 마친 뒤 응시할 수 있습니다")
        if prog["passed"] or prog["attempts"] >= MAX_ATTEMPTS:
            raise HTTPException(409, "더 응시할 수 없습니다")
        correct = sum(1 for a, q in zip(answers, questions) if a == q["answer"])
        score = correct * 100 // len(questions)
        passed = score >= PASS_SCORE
        attempt = prog["attempts"] + 1
        con.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,?)",
                    (user, attempt, score, int(passed), datetime.now().strftime("%Y-%m-%d %H:%M")))
        con.commit()
        return {"score": score, "passed": passed, "attempt": attempt,
                "attempts_left": MAX_ATTEMPTS - attempt, "certified": passed}
    finally:
        con.close()


@app.get("/api/admin/incomplete")
def incomplete(viewer: str = None):
    if not viewer:
        raise HTTPException(400, "viewer 가 필요합니다")
    con = db()
    try:
        if get_role(con, viewer) != "admin":
            raise HTTPException(403, "관리자만 볼 수 있습니다")
        rows = []
        for r in con.execute("SELECT user FROM ob_users WHERE role='trainee'"):
            p = build_progress(con, r["user"])
            if not p["certified"]:
                rows.append({"user": p["user"], "progress": p["progress"],
                             "attempts": p["attempts"], "best_score": p["best_score"]})
        rows.sort(key=lambda x: (x["progress"], x["user"]))
        return rows
    finally:
        con.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
