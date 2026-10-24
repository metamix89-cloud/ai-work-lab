# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R8 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import datetime as dt
import os
import sqlite3
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "onboard.db")
app = FastAPI()
TABLES = [("users.csv", "ob_users", "user TEXT, role TEXT"), ("lessons.csv", "ob_lessons", "lesson_id TEXT, seq INTEGER, title TEXT"),
          ("questions.csv", "ob_questions", "q_id TEXT, text TEXT, choices TEXT, answer INTEGER"),
          ("progress.csv", "ob_progress", "user TEXT, lesson_id TEXT, completed_at TEXT"),
          ("attempts.csv", "ob_attempts", "user TEXT, attempt INTEGER, score INTEGER, passed INTEGER, at TEXT")]


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    for fname, table, cols in TABLES:
        con.execute("CREATE TABLE %s(%s)" % (table, cols))
        p = os.path.join(SEED, fname)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            if rows:
                con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(rows[0]))), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def role(c, user):
    r = c.execute("SELECT role FROM ob_users WHERE user=?", (user,)).fetchone()
    return r["role"] if r else None


def state(c, user):
    lessons = [r["lesson_id"] for r in c.execute("SELECT lesson_id FROM ob_lessons ORDER BY seq")]
    done = {r["lesson_id"] for r in c.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
    out, opened = [], False
    for l in lessons:
        if l in done:
            out.append({"lesson_id": l, "state": "done"})
        elif not opened:
            out.append({"lesson_id": l, "state": "open"})
            opened = True
        else:
            out.append({"lesson_id": l, "state": "locked"})
    att = [dict(r) for r in c.execute("SELECT * FROM ob_attempts WHERE user=? ORDER BY attempt", (user,))]
    passed = any(int(a["passed"]) for a in att)
    all_done = len(done & set(lessons)) == len(lessons)
    return {"user": user, "lessons": out, "progress": len(done & set(lessons)) * 100 // max(1, len(lessons)), "attempts": len(att),
            "best_score": max([int(a["score"]) for a in att], default=None), "passed": passed, "certified": all_done and passed,
            "attempts_left": 0 if passed else max(0, 3 - len(att))}


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(r) for r in con().execute("SELECT * FROM ob_users")]


@app.get("/api/lessons")
def lessons():
    return [dict(r) for r in con().execute("SELECT * FROM ob_lessons ORDER BY seq")]


@app.get("/api/quiz")
def quiz():
    return [{"q_id": r["q_id"], "text": r["text"], "choices": r["choices"].split("|")} for r in con().execute("SELECT * FROM ob_questions")]


@app.get("/api/progress")
def progress(user: str, viewer: str = ""):
    c = con()
    vr = role(c, viewer)
    if viewer != user and vr != "admin":
        raise HTTPException(403, "본인 진도만 볼 수 있습니다")
    if role(c, user) is None:
        raise HTTPException(404, "사용자가 없습니다")
    return state(c, user)


@app.post("/api/lessons/{lesson_id}/complete")
def complete(lesson_id: str, body: dict[str, Any] = Body(...)):
    c = con()
    user = body.get("user")
    if not isinstance(user, str) or not user:
        raise HTTPException(400, "user 가 필요합니다")
    if role(c, user) is None:
        raise HTTPException(404, "사용자가 없습니다")
    seq = c.execute("SELECT seq FROM ob_lessons WHERE lesson_id=?", (lesson_id,)).fetchone()
    if not seq:
        raise HTTPException(404, "레슨이 없습니다")
    done = {r["lesson_id"] for r in c.execute("SELECT lesson_id FROM ob_progress WHERE user=?", (user,))}
    if lesson_id not in done:
        before = [r["lesson_id"] for r in c.execute("SELECT lesson_id FROM ob_lessons WHERE seq<?", (seq["seq"],))]
        if any(b not in done for b in before):
            raise HTTPException(409, "이전 레슨을 먼저 마치세요")
        c.execute("INSERT INTO ob_progress VALUES (?,?,?)", (user, lesson_id, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()
    return state(c, user)


@app.post("/api/quiz/submit")
def submit(body: dict[str, Any] = Body(...)):
    c = con()
    user, answers = body.get("user"), body.get("answers")
    qs = [r["answer"] for r in c.execute("SELECT answer FROM ob_questions")]
    if not isinstance(user, str) or not isinstance(answers, list) or len(answers) != len(qs) or \
            not all(isinstance(a, int) and not isinstance(a, bool) and 0 <= a <= 3 for a in answers):
        raise HTTPException(400, "answers 는 문항 수만큼의 0~3 정수입니다")
    if role(c, user) is None:
        raise HTTPException(404, "사용자가 없습니다")
    st = state(c, user)
    if st["progress"] < 100:
        raise HTTPException(409, "레슨을 모두 마친 뒤 응시할 수 있습니다")
    if st["passed"] or st["attempts"] >= 3:
        raise HTTPException(409, "더 응시할 수 없습니다")
    score = sum(1 for a, k in zip(answers, qs) if a == int(k)) * 100 // len(qs)
    passed = score >= 80
    attempt = st["attempts"] + 1
    c.execute("INSERT INTO ob_attempts VALUES (?,?,?,?,?)", (user, attempt, score, int(passed), dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    c.commit()
    st = state(c, user)
    return {"score": score, "passed": passed, "attempt": attempt, "attempts_left": st["attempts_left"], "certified": st["certified"]}


@app.get("/api/admin/incomplete")
def incomplete(viewer: str = ""):
    c = con()
    if role(c, viewer) != "admin":
        raise HTTPException(403, "관리자만 볼 수 있습니다")
    rows = []
    for r in c.execute("SELECT user FROM ob_users WHERE role='trainee'"):
        st = state(c, r["user"])
        if not st["certified"]:
            rows.append({"user": r["user"], "progress": st["progress"], "attempts": st["attempts"], "best_score": st["best_score"]})
    return sorted(rows, key=lambda x: (x["progress"], x["user"]))
