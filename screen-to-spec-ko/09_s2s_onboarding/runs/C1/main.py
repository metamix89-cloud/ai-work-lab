import csv
import os
import sqlite3
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "onboard.db")
SEED = os.path.join(BASE, "seed")
MAX_ATTEMPTS = 3
PASS_SCORE = 80

SCHEMA = """
CREATE TABLE ob_users (user TEXT PRIMARY KEY, role TEXT);
CREATE TABLE ob_lessons (lesson_id TEXT PRIMARY KEY, seq INTEGER, title TEXT);
CREATE TABLE ob_questions (q_id TEXT PRIMARY KEY, text TEXT, choices TEXT, answer INTEGER);
CREATE TABLE ob_progress (user TEXT, lesson_id TEXT, completed_at TEXT);
CREATE TABLE ob_attempts (user TEXT, attempt INTEGER, score INTEGER, passed INTEGER, at TEXT);
"""


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
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


@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "입력이 올바르지 않습니다"}, status_code=400)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def bad(msg="입력이 올바르지 않습니다"):
    return HTTPException(400, msg)


def need_str(v):
    if not isinstance(v, str) or not v:
        raise bad()
    return v


def get_role(con, user):
    r = con.execute("SELECT role FROM ob_users WHERE user=?", (user,)).fetchone()
    return r["role"] if r else None


def build_progress(con, user):
    lessons = con.execute("SELECT lesson_id FROM ob_lessons ORDER BY seq").fetchall()
    done = {r["lesson_id"] for r in con.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
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
    progress = n_done * 100 // len(out) if out else 0
    att = con.execute("SELECT score, passed FROM ob_attempts WHERE user=?", (user,)).fetchall()
    passed = any(a["passed"] for a in att)
    all_done = bool(out) and n_done == len(out)
    return {
        "user": user, "lessons": out, "progress": progress, "attempts": len(att),
        "best_score": max((a["score"] for a in att), default=0),
        "passed": passed, "certified": all_done and passed,
        "attempts_left": max(0, MAX_ATTEMPTS - len(att)),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT user, role FROM ob_users")]


@app.get("/api/lessons")
def lessons():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT lesson_id, seq, title FROM ob_lessons ORDER BY seq")]


@app.get("/api/quiz")
def quiz():
    with db() as con:
        return [{"q_id": r["q_id"], "text": r["text"], "choices": r["choices"].split("|")}
                for r in con.execute("SELECT q_id, text, choices FROM ob_questions ORDER BY rowid")]


@app.get("/api/progress")
def progress(user: str = "", viewer: str = ""):
    need_str(user)
    need_str(viewer)
    with db() as con:
        if viewer != user and get_role(con, viewer) != "admin":
            raise HTTPException(403, "본인 진도만 볼 수 있습니다")
        if get_role(con, user) is None:
            raise HTTPException(404, "없는 사용자입니다")
        return build_progress(con, user)


def trainee_or_error(con, user):
    role = get_role(con, user)
    if role is None:
        raise HTTPException(404, "없는 사용자입니다")
    if role != "trainee":
        raise HTTPException(403, "신입만 할 수 있습니다")


@app.post("/api/lessons/{lesson_id}/complete")
def complete(lesson_id: str, body: Any = Body(None)):
    user = need_str(body.get("user") if isinstance(body, dict) else None)
    with db() as con:
        if get_role(con, user) is None:
            raise HTTPException(404, "없는 사용자입니다")
        trainee_or_error(con, user)
        lesson = con.execute("SELECT seq FROM ob_lessons WHERE lesson_id=?", (lesson_id,)).fetchone()
        if not lesson:
            raise HTTPException(404, "없는 레슨입니다")
        state = {x["lesson_id"]: x["state"] for x in build_progress(con, user)["lessons"]}[lesson_id]
        if state == "locked":
            raise HTTPException(409, "이전 레슨을 먼저 마치세요")
        if state == "open":
            con.execute("INSERT INTO ob_progress VALUES (?,?,datetime('now','localtime'))", (user, lesson_id))
            con.commit()
        return build_progress(con, user)


@app.post("/api/quiz/submit")
def submit(body: Any = Body(None)):
    if not isinstance(body, dict):
        raise bad()
    answers = body.get("answers")
    with db() as con:
        answer_key = [r["answer"] for r in con.execute("SELECT answer FROM ob_questions ORDER BY rowid")]
        if (not isinstance(answers, list) or len(answers) != len(answer_key)
                or any(type(a) is not int or not 0 <= a <= 3 for a in answers)):
            raise bad("answers 는 문항 수만큼의 0~3 정수여야 합니다")
        user = need_str(body.get("user"))
        trainee_or_error(con, user)
        p = build_progress(con, user)
        if p["progress"] < 100:
            raise HTTPException(409, "레슨을 모두 마친 뒤 응시할 수 있습니다")
        if p["passed"] or p["attempts"] >= MAX_ATTEMPTS:
            raise HTTPException(409, "더 응시할 수 없습니다")
        right = sum(1 for a, k in zip(answers, answer_key) if a == k)
        score = right * 100 // len(answer_key)
        passed = score >= PASS_SCORE
        attempt = p["attempts"] + 1
        con.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,datetime('now','localtime'))",
                    (user, attempt, score, int(passed)))
        con.commit()
        return {"score": score, "passed": passed, "attempt": attempt,
                "attempts_left": MAX_ATTEMPTS - attempt, "certified": passed}


@app.get("/api/admin/incomplete")
def incomplete(viewer: str = ""):
    need_str(viewer)
    with db() as con:
        if get_role(con, viewer) != "admin":
            raise HTTPException(403, "관리자만 볼 수 있습니다")
        rows = []
        for r in con.execute("SELECT user FROM ob_users WHERE role='trainee'").fetchall():
            p = build_progress(con, r["user"])
            if not p["certified"]:
                rows.append({"user": p["user"], "progress": p["progress"],
                             "attempts": p["attempts"], "best_score": p["best_score"]})
        rows.sort(key=lambda x: (x["progress"], x["user"]))
        return rows
