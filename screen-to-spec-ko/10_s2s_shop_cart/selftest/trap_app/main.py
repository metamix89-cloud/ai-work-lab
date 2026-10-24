# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수.
  품절도 담김(R1) · 옵션 검사 없음(R2) · 정가로 계산(할인가 무시, R3) · 한도 없음(R4) · 배송비 30,000 초과만 무료(>, R5) · 검증 없음 · 화면 손잡이 없음.
기대: T1 만 통과 → 1/9 (T2 는 sale_price 빈칸을 '' 로 돌려줘서 실패)."""
import csv
import os
import uuid

from fastapi import Body, FastAPI, HTTPException
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


P = {r[0]: {"product_id": r[0], "name": r[1], "price": int(r[2]), "sale_price": r[3], "stock": int(r[4]), "max_per_order": int(r[5])} for r in rows("products.csv")}
CARTS = {}


@app.get("/api/products")
def products():
    return [dict(p, sold_out=False, options=[]) for p in P.values()]


@app.post("/api/carts")
def new():
    cid = uuid.uuid4().hex[:8]
    CARTS[cid] = []
    return {"cart_id": cid}


def view(cid):
    items = [dict(i, unit_price=P[i["product_id"]]["price"], line_total=P[i["product_id"]]["price"] * i["qty"]) for i in CARTS[cid]]
    sub = sum(i["line_total"] for i in items)
    ship = 0 if sub > 30000 else 3000
    return {"cart_id": cid, "items": items, "subtotal": sub, "shipping": ship, "total": sub + ship}


@app.get("/api/carts/{cid}")
def get(cid: str):
    return view(cid)


@app.post("/api/carts/{cid}/items")
def add(cid: str, body: dict = Body(...)):
    if cid not in CARTS:
        raise HTTPException(404, "없음")
    CARTS[cid].append({"item_id": uuid.uuid4().hex[:6], "product_id": body.get("product_id"), "option_id": body.get("option_id"), "qty": body.get("qty", 1)})
    return view(cid)


@app.get("/", response_class=HTMLResponse)
def index():
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>쇼핑몰</title></head><body><h1>가나다식품 쇼핑몰 장바구니</h1></body></html>"
