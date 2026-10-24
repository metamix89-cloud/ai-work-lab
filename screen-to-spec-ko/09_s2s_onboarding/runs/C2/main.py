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


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE ob_users (user TEXT PRIMARY KEY, role TEXT);
        CREATE TABLE ob_lessons (lesson_id TEXT PRIMARY KEY, seq INTEGER, title TEXT);
        CREATE TABLE ob_questions (q_id TEXT PRIMARY KEY, text TEXT, choices TEXT, answer INTEGER);
        CREATE TABLE ob_progress (user TEXT, lesson_id TEXT, completed_at TEXT, PRIMARY KEY (user, lesson_id));
        CREATE TABLE ob_attempts (user TEXT, attempt INTEGER, score INTEGER, passed INTEGER, at TEXT);
        """
    )
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO ob_users VALUES (?,?)", (r["user"], r["role"]))
    for r in read_csv("lessons.csv"):
        con.execute("INSERT INTO ob_lessons VALUES (?,?,?)", (r["lesson_id"], int(r["seq"]), r["title"]))
    for r in read_csv("questions.csv"):
        con.execute("INSERT INTO ob_questions VALUES (?,?,?,?)", (r["q_id"], r["text"], r["choices"], int(r["answer"])))
    for r in read_csv("progress.csv"):
        con.execute("INSERT OR IGNORE INTO ob_progress VALUES (?,?,?)", (r["user"], r["lesson_id"], r["completed_at"]))
    for r in read_csv("attempts.csv"):
        con.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,?)",
                    (r["user"], int(r["attempt"]), int(r["score"]), int(r["passed"]), r["at"]))
    con.commit()
    con.close()


build_db()


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request: Request, exc: Reject):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def get_role(con, user):
    row = con.execute("SELECT role FROM ob_users WHERE user=?", (user,)).fetchone()
    return row["role"] if row else None


def require_user(con, user):
    if get_role(con, user) is None:
        raise Reject(404, "없는 사용자입니다")


def check_viewer(con, user, viewer):
    if viewer != user and get_role(con, viewer) != "admin":
        raise Reject(403, "본인 진도만 볼 수 있습니다")


def summary(con, user):
    lessons = con.execute("SELECT lesson_id FROM ob_lessons ORDER BY seq").fetchall()
    done = {r["lesson_id"] for r in con.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
    states, opened = [], False
    for l in lessons:
        lid = l["lesson_id"]
        if lid in done:
            st = "done"
        elif not opened:
            st, opened = "open", True
        else:
            st = "locked"
        states.append({"lesson_id": lid, "state": st})
    n_done = sum(1 for s in states if s["state"] == "done")
    total = len(states)
    progress = n_done * 100 // total if total else 0
    att = con.execute("SELECT score, passed FROM ob_attempts WHERE user=?", (user,)).fetchall()
    best = max((a["score"] for a in att), default=0)
    passed = any(a["passed"] for a in att)
    return {
        "user": user,
        "lessons": states,
        "progress": progress,
        "attempts": len(att),
        "best_score": best,
        "passed": passed,
        "certified": passed and total > 0 and n_done == total,
        "attempts_left": max(0, MAX_ATTEMPTS - len(att)),
    }


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
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    con = db()
    rows = con.execute("SELECT user, role FROM ob_users").fetchall()
    con.close()
    return [{"user": r["user"], "role": r["role"]} for r in rows]


@app.get("/api/lessons")
def lessons():
    con = db()
    rows = con.execute("SELECT lesson_id, seq, title FROM ob_lessons ORDER BY seq").fetchall()
    con.close()
    return [{"lesson_id": r["lesson_id"], "seq": r["seq"], "title": r["title"]} for r in rows]


@app.get("/api/quiz")
def quiz():
    con = db()
    rows = con.execute("SELECT q_id, text, choices FROM ob_questions ORDER BY rowid").fetchall()
    con.close()
    return [{"q_id": r["q_id"], "text": r["text"], "choices": r["choices"].split("|")} for r in rows]


@app.get("/api/progress")
def get_progress(user: str = "", viewer: str = ""):
    if not user or not viewer:
        raise Reject(400, "user 와 viewer 가 필요합니다")
    con = db()
    try:
        check_viewer(con, user, viewer)
        require_user(con, user)
        return summary(con, user)
    finally:
        con.close()


@app.post("/api/lessons/{lesson_id}/complete")
async def complete(lesson_id: str, request: Request):
    body = await read_body(request)
    user = body.get("user")
    if not isinstance(user, str) or not user:
        raise Reject(400, "user 가 필요합니다")
    con = db()
    try:
        require_user(con, user)
        lesson = con.execute("SELECT seq FROM ob_lessons WHERE lesson_id=?", (lesson_id,)).fetchone()
        if lesson is None:
            raise Reject(404, "없는 레슨입니다")
        done = con.execute("SELECT 1 FROM ob_progress WHERE user=? AND lesson_id=?", (user, lesson_id)).fetchone()
        if not done:
            prev = con.execute(
                "SELECT COUNT(*) c FROM ob_lessons l WHERE l.seq < ? AND NOT EXISTS "
                "(SELECT 1 FROM ob_progress p WHERE p.user=? AND p.lesson_id=l.lesson_id)",
                (lesson["seq"], user),
            ).fetchone()["c"]
            if prev:
                raise Reject(409, "이전 레슨을 먼저 마치세요")
            con.execute("INSERT INTO ob_progress VALUES (?,?,?)",
                        (user, lesson_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
            con.commit()
        return summary(con, user)
    finally:
        con.close()


@app.post("/api/quiz/submit")
async def submit(request: Request):
    body = await read_body(request)
    user = body.get("user")
    answers = body.get("answers")
    con = db()
    try:
        questions = con.execute("SELECT answer FROM ob_questions ORDER BY rowid").fetchall()
        if (not isinstance(user, str) or not user or not isinstance(answers, list)
                or len(answers) != len(questions)
                or any(type(a) is not int or a < 0 or a > 3 for a in answers)):
            raise Reject(400, "answers 는 문항 수만큼의 0~3 정수여야 합니다")
        require_user(con, user)
        s = summary(con, user)
        if any(l["state"] != "done" for l in s["lessons"]):
            raise Reject(409, "레슨을 모두 마친 뒤 응시할 수 있습니다")
        if s["passed"] or s["attempts"] >= MAX_ATTEMPTS:
            raise Reject(409, "더 응시할 수 없습니다")
        right = sum(1 for a, q in zip(answers, questions) if a == q["answer"])
        score = right * 100 // len(questions)
        passed = score >= PASS_SCORE
        con.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,?)",
                    (user, s["attempts"] + 1, score, 1 if passed else 0, datetime.now().strftime("%Y-%m-%d %H:%M")))
        con.commit()
        s = summary(con, user)
        return {"score": score, "passed": passed, "attempt": s["attempts"],
                "attempts_left": s["attempts_left"], "certified": s["certified"]}
    finally:
        con.close()


@app.get("/api/admin/incomplete")
def admin_incomplete(viewer: str = ""):
    con = db()
    try:
        if not viewer:
            raise Reject(400, "viewer 가 필요합니다")
        if get_role(con, viewer) != "admin":
            raise Reject(403, "관리자만 볼 수 있습니다")
        out = []
        for u in con.execute("SELECT user FROM ob_users WHERE role='trainee'").fetchall():
            s = summary(con, u["user"])
            if not s["certified"]:
                out.append({"user": u["user"], "progress": s["progress"],
                            "attempts": s["attempts"], "best_score": s["best_score"]})
        out.sort(key=lambda r: (r["progress"], r["user"]))
        return out
    finally:
        con.close()
