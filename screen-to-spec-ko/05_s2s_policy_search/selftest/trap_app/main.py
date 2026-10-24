# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수.
  개정 전 조항도 결과에 섞임(R1) · 단어 하나라도 들어가면 매칭(OR, R3) · 없으면 '비슷한 조항' 을 보여 줌(R4) · 정렬은 id 순(R5) · 빈 검색어 200(R7) · 이력 API 없음.
기대: T1 · T8(id 순 정렬이 우연히 제목 매칭 순과 같음) 통과 → 2/9."""
import csv
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
app = FastAPI()
ROWS = []
p = os.path.join(SEED, "clauses.csv")
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        for r in list(csv.reader(f))[1:]:
            ROWS.append({"clause_id": r[0], "doc": r[1], "article": r[2], "title": r[3], "body": r[4], "effective_from": r[5], "effective_to": r[6]})


@app.get("/api/search")
def search(q: str = ""):
    words = q.lower().split()
    hits = [r for r in ROWS if any(w in (r["title"] + r["body"]).lower() for w in words)] if words else ROWS
    if not hits:
        hits = ROWS[:3]      # '비슷한' 조항 대신 보여 주기 — R4 위반
    return {"query": q, "count": len(hits), "results": [dict(r, snippet=r["body"][:60], has_history=False) for r in hits]}


@app.get("/api/clauses/{clause_id}")
def clause(clause_id: str):
    for r in ROWS:
        if r["clause_id"] == clause_id:
            return r
    raise HTTPException(404, "없음")


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>규정 검색</title></head><body>
<h1>다온소프트 규정 검색</h1><input id="q" placeholder="검색어"><button>검색</button><div id="list"></div></body></html>"""
