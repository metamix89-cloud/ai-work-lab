# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수만 모았다. T1 · T2 · T3 만 통과해야 채점기가 맞다(목록 · 상태 계산은 맞고, 배분 · 폐기 · 순서가 틀림).
실수: 선입선출(생산일 순) · 만료 로트도 배분 · 모자라면 있는 만큼만(부분 출고) · 누구나 · 어느 로트나 폐기 · 로트를 본문보다 먼저 찾음 · 화면 없음."""
import csv
import os
import sqlite3
from datetime import date
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "expiry.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE ex_users(user_id TEXT, name TEXT, role TEXT);
    CREATE TABLE ex_items(item_id TEXT, name TEXT, unit_price INTEGER, near_days INTEGER);
    CREATE TABLE ex_lots(lot_id TEXT, item_id TEXT, produced_on TEXT, expires_on TEXT, qty INTEGER);""")
    for name, table, n in (("users.csv", "ex_users", 3), ("items.csv", "ex_items", 4), ("lots.csv", "ex_lots", 5)):
        with open(os.path.join(SEED, name), encoding="utf-8") as f:
            c.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    c.commit()
    c.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def view(c, l):
    it = c.execute("SELECT * FROM ex_items WHERE item_id=?", (l["item_id"],)).fetchone()
    days = (date.fromisoformat(l["expires_on"]) - date.today()).days
    return {"lot_id": l["lot_id"], "item_id": l["item_id"], "item_name": it["name"], "produced_on": l["produced_on"], "expires_on": l["expires_on"],
            "days_left": days, "qty": int(l["qty"]), "state": "expired" if days < 0 else ("near" if days <= int(it["near_days"]) else "ok"),
            "unit_price": int(it["unit_price"])}


def listing(c):
    rows = sorted((view(c, l) for l in c.execute("SELECT * FROM ex_lots WHERE qty > 0")), key=lambda r: (r["days_left"], r["lot_id"]))
    near = [r for r in rows if r["state"] == "near"]
    return {"lots": rows, "summary": {"near": len(near), "expired": sum(1 for r in rows if r["state"] == "expired"),
                                     "near_value": sum(r["unit_price"] * r["qty"] for r in near)}, "today": date.today().isoformat()}


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>유통기한 재고</h1></body></html>"


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM ex_users")]


@app.get("/api/items")
def items():
    return [{"item_id": i["item_id"], "name": i["name"], "unit_price": int(i["unit_price"]), "near_days": int(i["near_days"])} for i in con().execute("SELECT * FROM ex_items")]


@app.get("/api/lots")
def lots():
    return listing(con())


@app.post("/api/ship")
def ship(body: dict[str, Any] = Body(default={})):
    c = con()
    if not c.execute("SELECT 1 FROM ex_items WHERE item_id=?", (body.get("item_id"),)).fetchone():
        raise HTTPException(404, "품목이 없습니다")
    qty = body.get("qty")
    if not isinstance(qty, int) or qty < 1:
        raise HTTPException(400, "수량을 확인하세요")
    left, allocs = qty, []
    for l in c.execute("SELECT * FROM ex_lots WHERE item_id=? AND qty > 0 ORDER BY produced_on, lot_id", (body["item_id"],)).fetchall():   # 실수: 생산일 순 · 만료 포함
        take = min(int(l["qty"]), left)
        c.execute("UPDATE ex_lots SET qty=qty-? WHERE lot_id=?", (take, l["lot_id"]))
        allocs.append({"lot_id": l["lot_id"], "qty": take})
        left -= take
        if left == 0:
            break
    c.commit()                                                          # 실수: 모자라도 있는 만큼 나간다
    out = listing(c)
    return {"allocations": allocs, "lots": out["lots"], "summary": out["summary"]}


@app.post("/api/lots/{lid}/dispose")
def dispose(lid: str, body: dict[str, Any] = Body(default={})):
    c = con()
    l = c.execute("SELECT * FROM ex_lots WHERE lot_id=?", (lid,)).fetchone()
    if not l:
        raise HTTPException(404, "로트가 없습니다")                      # 실수: 본문(400)보다 먼저
    if not (body.get("reason") or "").strip():
        raise HTTPException(400, "사유를 입력하세요")
    c.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lid,))      # 실수: 누구나 · 어느 로트나
    c.commit()
    return {"lot": view(c, c.execute("SELECT * FROM ex_lots WHERE lot_id=?", (lid,)).fetchone()), "summary": listing(c)["summary"]}
