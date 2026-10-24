import csv
import os
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "onboard.db")
MAX_ATTEMPTS = 3
PASS_SCORE = 80

app = FastAPI()


def rows(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_db():
    if os.path.exists(DB):
        os.remove(DB)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE ob_users (user TEXT PRIMARY KEY, role TEXT);
    CREATE TABLE ob_lessons (lesson_id TEXT PRIMARY KEY, seq INTEGER, title TEXT);
    CREATE TABLE ob_questions (q_id TEXT PRIMARY KEY, text TEXT, choices TEXT, answer INTEGER);
    CREATE TABLE ob_progress (user TEXT, lesson_id TEXT, completed_at TEXT);
    CREATE TABLE ob_attempts (user TEXT, attempt INTEGER, score INTEGER, passed INTEGER, at TEXT);
    """)
    c.executemany("INSERT INTO ob_users VALUES (?,?)", [(r["user"], r["role"]) for r in rows("users.csv")])
    c.executemany("INSERT INTO ob_lessons VALUES (?,?,?)", [(r["lesson_id"], int(r["seq"]), r["title"]) for r in rows("lessons.csv")])
    c.executemany("INSERT INTO ob_questions VALUES (?,?,?,?)", [(r["q_id"], r["text"], r["choices"], int(r["answer"])) for r in rows("questions.csv")])
    c.executemany("INSERT INTO ob_progress VALUES (?,?,?)", [(r["user"], r["lesson_id"], r["completed_at"]) for r in rows("progress.csv")])
    c.executemany("INSERT INTO ob_attempts VALUES (?,?,?,?,?)", [(r["user"], int(r["attempt"]), int(r["score"]), int(r["passed"]), r["at"]) for r in rows("attempts.csv")])
    c.commit()
    c.close()


build_db()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def role_of(c, user):
    r = c.execute("SELECT role FROM ob_users WHERE user=?", (user,)).fetchone()
    return r["role"] if r else None


def progress_of(c, user):
    lessons = c.execute("SELECT lesson_id FROM ob_lessons ORDER BY seq").fetchall()
    done = {r["lesson_id"] for r in c.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
    out, opened = [], False
    for l in lessons:
        lid = l["lesson_id"]
        if lid in done:
            out.append({"lesson_id": lid, "state": "done"})
        elif not opened:
            out.append({"lesson_id": lid, "state": "open"})
            opened = True
        else:
            out.append({"lesson_id": lid, "state": "locked"})
    total = len(lessons)
    n_done = sum(1 for x in out if x["state"] == "done")
    pct = n_done * 100 // total if total else 0
    att = c.execute("SELECT score, passed FROM ob_attempts WHERE user=?", (user,)).fetchall()
    passed = any(a["passed"] for a in att)
    return {
        "user": user,
        "lessons": out,
        "progress": pct,
        "attempts": len(att),
        "best_score": max((a["score"] for a in att), default=0),
        "passed": passed,
        "certified": bool(total) and n_done == total and passed,
        "attempts_left": 0 if passed else max(0, MAX_ATTEMPTS - len(att)),
    }


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    if not isinstance(b, dict):
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    return b


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with db() as c:
        return [{"user": r["user"], "role": r["role"]} for r in c.execute("SELECT user, role FROM ob_users ORDER BY rowid")]


@app.get("/api/lessons")
def lessons():
    with db() as c:
        return [dict(r) for r in c.execute("SELECT lesson_id, seq, title FROM ob_lessons ORDER BY seq")]


@app.get("/api/quiz")
def quiz():
    with db() as c:
        return [{"q_id": r["q_id"], "text": r["text"], "choices": r["choices"].split("|")}
                for r in c.execute("SELECT q_id, text, choices FROM ob_questions ORDER BY rowid")]


@app.get("/api/progress")
def progress(user: str = "", viewer: str = ""):
    if not user or not viewer:
        raise Reject(400, "user 와 viewer 가 필요합니다")
    with db() as c:
        if viewer != user and role_of(c, viewer) != "admin":
            raise Reject(403, "본인 진도만 볼 수 있습니다")
        if role_of(c, user) is None:
            raise Reject(404, "없는 사용자입니다")
        return progress_of(c, user)


@app.post("/api/lessons/{lesson_id}/complete")
async def complete(lesson_id: str, request: Request):
    b = await body_of(request)
    user = b.get("user")
    if not isinstance(user, str) or not user:
        raise Reject(400, "user 가 필요합니다")
    with db() as c:
        if role_of(c, user) is None:
            raise Reject(404, "없는 사용자입니다")
        if not c.execute("SELECT 1 FROM ob_lessons WHERE lesson_id=?", (lesson_id,)).fetchone():
            raise Reject(404, "없는 레슨입니다")
        state = next(x["state"] for x in progress_of(c, user)["lessons"] if x["lesson_id"] == lesson_id)
        if state == "locked":
            raise Reject(409, "이전 레슨을 먼저 마치세요")
        if state == "open":
            c.execute("INSERT INTO ob_progress VALUES (?,?,?)", (user, lesson_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
            c.commit()
        return progress_of(c, user)


@app.post("/api/quiz/submit")
async def submit(request: Request):
    b = await body_of(request)
    user, answers = b.get("user"), b.get("answers")
    with db() as c:
        qs = c.execute("SELECT answer FROM ob_questions ORDER BY rowid").fetchall()
        if (not isinstance(user, str) or not user or not isinstance(answers, list)
                or len(answers) != len(qs)
                or any(type(a) is not int or not 0 <= a <= 3 for a in answers)):
            raise Reject(400, "answers 는 문항 수만큼의 0~3 정수여야 합니다")
        if role_of(c, user) is None:
            raise Reject(404, "없는 사용자입니다")
        p = progress_of(c, user)
        if any(x["state"] != "done" for x in p["lessons"]):
            raise Reject(409, "레슨을 모두 마친 뒤 응시할 수 있습니다")
        if p["passed"] or p["attempts"] >= MAX_ATTEMPTS:
            raise Reject(409, "더 응시할 수 없습니다")
        right = sum(1 for a, q in zip(answers, qs) if a == q["answer"])
        score = right * 100 // len(qs)
        c.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,?)",
                  (user, p["attempts"] + 1, score, int(score >= PASS_SCORE), datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()
        p = progress_of(c, user)
        return {"score": score, "passed": score >= PASS_SCORE, "attempt": p["attempts"],
                "attempts_left": p["attempts_left"], "certified": p["certified"]}


@app.get("/api/admin/incomplete")
def incomplete(viewer: str = ""):
    with db() as c:
        if role_of(c, viewer) != "admin":
            raise Reject(403, "관리자만 볼 수 있습니다")
        out = []
        for r in c.execute("SELECT user FROM ob_users WHERE role='trainee'").fetchall():
            p = progress_of(c, r["user"])
            if not p["certified"]:
                out.append({"user": r["user"], "progress": p["progress"], "attempts": p["attempts"], "best_score": p["best_score"]})
        out.sort(key=lambda x: (x["progress"], x["user"]))
        return out
