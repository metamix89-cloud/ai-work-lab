# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수.
  어떤 상태로든 이동 허용(건너뛰기 · 되돌리기 · 종결 후 이동, R1 · R5) · 담당자 · 답변 검사 없음(R2 · R3) · 기한 당일도 넘김(>=, R4) · 종결도 넘김 계산 · 이력 없음 · 화면 손잡이 없음.
기대: T1 · T4(접수 → 배정은 됨) 통과 → 2/9."""
import csv
import datetime as dt
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
COLS = ["complaint_id", "title", "category", "received", "status", "assignee", "answer"]
app = FastAPI()
ROWS = {}
p = os.path.join(SEED, "complaints.csv")
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        for r in list(csv.reader(f))[1:]:
            ROWS[r[0]] = dict(zip(COLS, r))


def view(r):
    d = dict(r)
    due = dt.date.fromisoformat(d["received"]) + dt.timedelta(days=7)
    d.update(due=due.isoformat(), days_left=(due - dt.date.today()).days, overdue=dt.date.today() >= due)
    return d


class Move(BaseModel):
    to: str = ""
    by: str = ""
    assignee: str = ""
    answer: str = ""


@app.get("/api/summary")
def summary():
    vs = [view(r) for r in ROWS.values()]
    return {"counts": {s: sum(1 for v in vs if v["status"] == s) for s in ("접수", "배정", "처리중", "종결")}, "overdue": sum(v["overdue"] for v in vs)}


@app.get("/api/complaints")
def complaints():
    return {"items": [view(r) for r in ROWS.values()]}


@app.post("/api/complaints/{cid}/transition")
def transition(cid: str, m: Move):
    if cid not in ROWS:
        raise HTTPException(404, "없음")
    ROWS[cid].update(status=m.to, assignee=m.assignee or ROWS[cid]["assignee"], answer=m.answer or ROWS[cid]["answer"])
    return view(ROWS[cid])


@app.get("/", response_class=HTMLResponse)
def index():
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>민원 현황</title></head><body><h1>푸른구청 민원 현황판</h1></body></html>"
