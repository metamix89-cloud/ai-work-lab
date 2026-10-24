# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수: 라운드 로빈으로 돌려 채운다.
  제외일 무시(R2) · 지난달 경계 무시(R3, 10-31 김민수 → 11-01 김민수) · 주말 공평 안 봄(R5) · 바꾸기 검사 없음(R6) · 확정 없음(R7) · 화면 손잡이 없음.
기대: T1 · T2 · T5(라운드 로빈은 총 횟수는 공평) 통과 → 3/9. (T4 는 경계에서 실패, T6 은 주말이 특정 사람에게 몰릴 수 있어 실패/우연 통과 — 6명 · 7일 주기라 요일이 고정돼 실패)"""
import calendar
import csv
import datetime as dt
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
app = FastAPI()
ROSTER = {}


def rows(name):
    p = os.path.join(SEED, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [r for r in csv.reader(f)][1:]


NAMES = [r[0] for r in rows("staff.csv")]


class MonthIn(BaseModel):
    month: str


class SwapIn(BaseModel):
    date_a: str
    date_b: str


def days_of(month):
    y, m = int(month[:4]), int(month[5:7])
    return ["%04d-%02d-%02d" % (y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


@app.get("/api/roster")
def roster(month: str):
    return {"month": month, "status": "생성됨" if any(d.startswith(month) for d in ROSTER) else "미생성",
            "days": [{"date": d, "name": ROSTER.get(d, ""), "weekend": dt.date.fromisoformat(d).weekday() >= 5} for d in days_of(month)]}


@app.post("/api/roster/generate")
def gen(m: MonthIn):
    for i, d in enumerate(days_of(m.month)):
        ROSTER[d] = NAMES[i % len(NAMES)]
    return roster(m.month)


@app.post("/api/roster/swap")
def swap(s: SwapIn):
    ROSTER[s.date_a], ROSTER[s.date_b] = ROSTER.get(s.date_b, ""), ROSTER.get(s.date_a, "")
    return roster(s.date_a[:7])


@app.post("/api/roster/confirm")
def confirm(m: MonthIn):
    return roster(m.month)


@app.get("/api/stats")
def stats(month: str):
    return [{"name": n, "total": sum(1 for d, x in ROSTER.items() if d.startswith(month) and x == n), "weekend": 0} for n in NAMES]


@app.get("/", response_class=HTMLResponse)
def index():
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>당직표</title></head><body><h1>3병동 야간 당직 순번표</h1><button>생성</button></body></html>"
