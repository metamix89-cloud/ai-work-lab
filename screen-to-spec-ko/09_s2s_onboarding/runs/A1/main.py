import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from content import LESSONS, PASS_SCORE, QUIZ
from seed import seed

BASE = Path(__file__).parent
DB_PATH = BASE / "onboarding.db"
SESSIONS: dict[str, int] = {}  # token -> employee id (데모용 인메모리 세션)


@asynccontextmanager
async def lifespan(_):
    seed(DB_PATH)
    yield


app = FastAPI(title="다온소프트 신입사원 온보딩", lifespan=lifespan)


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    finally:
        con.close()


def current_user(authorization: str = Header(default=""), con=Depends(db)):
    token = authorization.removeprefix("Bearer ").strip()
    emp_id = SESSIONS.get(token)
    row = con.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone() if emp_id else None
    if not row:
        raise HTTPException(401, "로그인이 필요합니다.")
    return row


def hr_user(user=Depends(current_user)):
    if user["role"] != "hr":
        raise HTTPException(403, "인사팀 권한이 필요합니다.")
    return user


def trainee_user(user=Depends(current_user)):
    if user["role"] != "trainee":
        raise HTTPException(403, "신입사원 전용 기능입니다.")
    return user


def done_lessons(con, emp_id) -> set[int]:
    return {r[0] for r in con.execute("SELECT lesson_id FROM lesson_progress WHERE employee_id=?", (emp_id,))}


def require_unlocked(con, emp_id, lid):
    if not any(l[0] == lid for l in LESSONS):
        raise HTTPException(404, "레슨이 없습니다.")
    if lid > 1 and (lid - 1) not in done_lessons(con, emp_id):
        raise HTTPException(403, "이전 레슨을 먼저 완료하세요.")


def require_all_lessons(con, emp_id):
    if len(done_lessons(con, emp_id)) < len(LESSONS):
        raise HTTPException(403, "모든 레슨을 완료해야 퀴즈를 풀 수 있습니다.")


class LoginIn(BaseModel):
    emp_no: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, con=Depends(db)):
    row = con.execute("SELECT * FROM employees WHERE emp_no=?", (body.emp_no.strip(),)).fetchone()
    if not row or not secrets.compare_digest(row["password"], body.password):
        raise HTTPException(401, "사번 또는 비밀번호가 올바르지 않습니다.")
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = row["id"]
    return {"token": token, "name": row["name"], "role": row["role"]}


@app.get("/api/lessons")
def lessons(user=Depends(trainee_user), con=Depends(db)):
    done = done_lessons(con, user["id"])
    out = [{"id": lid, "title": title, "done": lid in done, "unlocked": lid == 1 or (lid - 1) in done}
           for lid, title, _ in LESSONS]
    stats = con.execute("SELECT MAX(passed), MAX(score) FROM quiz_attempts WHERE employee_id=?",
                        (user["id"],)).fetchone()
    return {"lessons": out, "quiz_unlocked": len(done) == len(LESSONS), "passed": bool(stats[0]),
            "best_score": stats[1], "pass_score": PASS_SCORE}


@app.get("/api/lessons/{lid}")
def lesson(lid: int, user=Depends(trainee_user), con=Depends(db)):
    require_unlocked(con, user["id"], lid)
    _, title, html = next(l for l in LESSONS if l[0] == lid)
    return {"id": lid, "title": title, "html": html, "last": lid == len(LESSONS)}


@app.post("/api/lessons/{lid}/complete")
def complete(lid: int, user=Depends(trainee_user), con=Depends(db)):
    require_unlocked(con, user["id"], lid)
    con.execute("INSERT OR IGNORE INTO lesson_progress(employee_id, lesson_id, completed_at) VALUES(?,?,?)",
                (user["id"], lid, datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return {"ok": True}


@app.get("/api/quiz")
def quiz(user=Depends(trainee_user), con=Depends(db)):
    require_all_lessons(con, user["id"])
    return {"pass_score": PASS_SCORE,
            "questions": [{"id": q[0], "text": q[1], "choices": q[2]} for q in QUIZ]}


class QuizIn(BaseModel):
    answers: dict[int, int]  # question id -> choice index


@app.post("/api/quiz/submit")
def submit(body: QuizIn, user=Depends(trainee_user), con=Depends(db)):
    require_all_lessons(con, user["id"])
    correct = sum(1 for qid, _, _, ans in QUIZ if body.answers.get(qid) == ans)
    score = round(correct * 100 / len(QUIZ))
    passed = score >= PASS_SCORE
    con.execute("INSERT INTO quiz_attempts(employee_id, score, passed, taken_at) VALUES(?,?,?,?)",
                (user["id"], score, int(passed), datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return {"score": score, "correct": correct, "total": len(QUIZ), "passed": passed, "pass_score": PASS_SCORE}


def status_rows(con):
    rows = con.execute("""
        SELECT e.emp_no, e.name, e.department, e.hired_at,
          (SELECT COUNT(*) FROM lesson_progress p WHERE p.employee_id=e.id) AS lessons_done,
          (SELECT MAX(score) FROM quiz_attempts q WHERE q.employee_id=e.id) AS best_score,
          (SELECT COUNT(*) FROM quiz_attempts q WHERE q.employee_id=e.id) AS attempts,
          COALESCE((SELECT MAX(passed) FROM quiz_attempts q WHERE q.employee_id=e.id), 0) AS passed
        FROM employees e WHERE e.role='trainee' ORDER BY e.hired_at, e.emp_no""").fetchall()
    return [dict(r) | {"passed": bool(r["passed"])} for r in rows]


@app.get("/api/hr/incomplete")
def incomplete(_=Depends(hr_user), con=Depends(db)):
    rows = status_rows(con)
    return {"total": len(rows), "incomplete": [r for r in rows if not r["passed"]], "lesson_count": len(LESSONS)}


@app.get("/api/hr/all")
def all_status(_=Depends(hr_user), con=Depends(db)):
    return {"employees": status_rows(con), "lesson_count": len(LESSONS)}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
