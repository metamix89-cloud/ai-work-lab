# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수를 일부러 넣었다.
  취소 주문도 셈(R1) · 안전재고와 같아도 경고(R2) · 완료 문의도 셈(R3) · 주문 없는 날 막대 생략(R4) · 빈 데이터면 0(R5) · 갱신 시각 없음(R6)
  data-testid 없음(라벨 근처 숫자로 읽혀야 함) · /api/summary 없음(/api/stats).
기대: T1 · T2 통과, T3~T9 실패 → 2/9."""
import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
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


@app.get("/api/stats")
def stats():
    today = dt.date.today().isoformat()
    orders = rows("orders.csv")
    daily = {}
    for r in orders:
        daily[r[1][:10]] = daily.get(r[1][:10], 0) + 1
    return {"orders": sum(1 for r in orders if r[1][:10] == today),
            "alerts": sum(1 for r in rows("stock.csv") if int(r[2]) <= int(r[3])),
            "inq": len(rows("inquiries.csv")),
            "daily": sorted((d, c) for d, c in daily.items() if d > (dt.date.today() - dt.timedelta(days=7)).isoformat())}


@app.get("/", response_class=HTMLResponse)
def index():
    s = stats()
    bars = "".join('<div class="bar" style="height:%dpx"></div>' % (20 * c) for d, c in s["daily"])
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>오늘의 현황판</title>
<style>.bars{display:flex;gap:8px;align-items:flex-end;height:120px}.bar{width:30px;background:#6366F1}</style></head><body>
<h1>가나다식품 현황판</h1>
<div><span>오늘 주문</span> <b>%d</b>건</div>
<div><span>재고 경고</span> <b>%d</b>개</div>
<div><span>미처리 문의</span> <b>%d</b>건</div>
<div class="bars">%s</div></body></html>""" % (s["orders"], s["alerts"], s["inq"], bars)
