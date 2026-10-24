# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수.
  폐지도 섞어 보여 줌(R2) · 출처 없는 행도 보여 줌(R3) · 요약이 없으면 원문 앞 30자를 잘라 채움(R4) · 상태 없음(R1) · OR 검색(R5) · 400 없음(R7) · as_of 없음.
기대: T1 만 통과 → 1/9."""
import csv
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
COLS = ["notice_id", "title", "category", "issuer", "published", "effective_from", "repealed", "source_url", "original", "summary"]
app = FastAPI()
ROWS = []
p = os.path.join(SEED, "notices.csv")
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        ROWS = [dict(zip(COLS, r)) for r in list(csv.reader(f))[1:]]


def item(r):
    d = dict(r)
    d["summary"] = d["summary"] or d["original"][:30] + "…"
    d["has_summary"] = True
    d["status"] = "게시"
    d["days_until"] = None
    return d


@app.get("/api/notices")
def notices(category: str = "", q: str = "", include_repealed: str = "0"):
    words = q.split()
    out = [item(r) for r in ROWS if (not category or r["category"] == category)
           and (not words or any(w in r["title"] + r["original"] for w in words))]
    return {"count": len(out), "items": out}


@app.get("/api/notices/{notice_id}")
def notice(notice_id: str):
    for r in ROWS:
        if r["notice_id"] == notice_id:
            return item(r)
    raise HTTPException(404, "없음")


@app.get("/", response_class=HTMLResponse)
def index():
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>고시 열람</title></head><body><h1>푸른구청 고시 · 공고</h1><div id='list'></div></body></html>"
