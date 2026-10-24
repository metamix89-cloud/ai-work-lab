# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수.
  퀴즈 API 가 정답까지 보냄(R7) · 순서 검사 없음(R1) · 레슨 전 응시 허용(R2) · 80 초과만 합격(> 80, R3) · 응시 무제한(R4) · 권한 없음(R6) · 검증 없음.
기대: T1 만 통과 → 1/9."""
import csv
import os

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
app = FastAPI()


def rows(name):
    p = os.path.join(SEED, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [r for r in csv.reader(f)][1:]


Q = [{"q_id": r[0], "text": r[1], "choices": r[2].split("|"), "answer": int(r[3])} for r in rows("questions.csv")]
DONE = {}
for u, l, _ in rows("progress.csv"):
    DONE.setdefault(u, set()).add(l)


@app.get("/api/quiz")
def quiz():
    return Q


@app.post("/api/lessons/{lid}/complete")
def complete(lid: str, body: dict = Body(...)):
    DONE.setdefault(body.get("user"), set()).add(lid)
    return {"progress": len(DONE[body.get("user")]) * 25}


@app.post("/api/quiz/submit")
def submit(body: dict = Body(...)):
    a = body.get("answers", [])
    score = sum(1 for x, q in zip(a, Q) if x == q["answer"]) * 20
    return {"score": score, "passed": score > 80, "results": [x == q["answer"] for x, q in zip(a, Q)]}


@app.get("/api/progress")
def progress(user: str, viewer: str = ""):
    return {"user": user, "progress": len(DONE.get(user, ())) * 25, "lessons": []}


@app.get("/", response_class=HTMLResponse)
def index():
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>온보딩</title></head><body><h1>다온소프트 온보딩 교육</h1></body></html>"
