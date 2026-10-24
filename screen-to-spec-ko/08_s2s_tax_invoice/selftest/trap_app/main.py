# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수.
  줄마다 세액을 반올림해 더함(R1, 300) · 요청의 금액을 그대로 믿음(R1) · 번호는 전체 일련번호(R3) · 제자리 수정(PUT, R4) · 검증 없음(R2) · 월 합계에 모든 상태 포함(R6).
기대: T1 만 통과 → 1/9."""
import csv
import os

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
app = FastAPI()
INV = {}
p = os.path.join(SEED, "invoices.csv")
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        for r in list(csv.reader(f))[1:]:
            INV[r[0]] = {"invoice_no": r[0], "issued": r[1], "biz_no": r[2], "supply": int(r[3]), "tax": int(r[4]), "total": int(r[5]),
                         "status": r[6], "amends": "", "amended_by": "", "lines": []}


def calc(lines):
    supply = sum(l.get("qty", 0) * l.get("unit_price", 0) for l in lines)
    tax = sum(round(l.get("qty", 0) * l.get("unit_price", 0) * 0.1) for l in lines)
    return supply, tax


@app.post("/api/invoices", status_code=201)
def create(body: dict = Body(...)):
    s, t = calc(body.get("lines", []))
    s, t = body.get("supply", s), body.get("tax", t)
    no = "INV-%04d" % (len(INV) + 1)
    INV[no] = {"invoice_no": no, "issued": body.get("issued"), "biz_no": body.get("biz_no"), "supply": s, "tax": t, "total": s + t,
               "status": "발행", "amends": "", "amended_by": "", "lines": body.get("lines", [])}
    return INV[no]


@app.put("/api/invoices/{no}")
def edit(no: str, body: dict = Body(...)):
    INV[no].update(body)
    return INV[no]


@app.get("/api/invoices")
def ledger(month: str = ""):
    items = list(INV.values())
    return {"count": len(items), "totals": {k: sum(i[k] for i in items) for k in ("supply", "tax", "total")}, "items": items}


@app.get("/api/invoices/{no}")
def detail(no: str):
    if no not in INV:
        raise HTTPException(404, "없음")
    return INV[no]


@app.get("/", response_class=HTMLResponse)
def index():
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>세금계산서</title></head><body><h1>가나다식품 세금계산서</h1></body></html>"
