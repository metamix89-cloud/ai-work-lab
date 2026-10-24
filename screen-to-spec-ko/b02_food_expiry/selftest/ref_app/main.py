# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R8 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
출고는 선기한선출(FEFO): 만료 아닌 로트를 expires_on · lot_id 순으로 배분, 모자라면 전부 거부."""
import csv
import os
import sqlite3
import threading
from datetime import date, datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "expiry.db")
LOCK = threading.Lock()
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE ex_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE ex_items(item_id TEXT PRIMARY KEY, name TEXT, unit_price INTEGER, near_days INTEGER);
    CREATE TABLE ex_lots(lot_id TEXT PRIMARY KEY, item_id TEXT, produced_on TEXT, expires_on TEXT, qty INTEGER CHECK (qty >= 0));
    CREATE TABLE ex_moves(lot_id TEXT, at TEXT, by TEXT, kind TEXT, qty INTEGER, note TEXT);""")
    for name, table, n in (("users.csv", "ex_users", 3), ("items.csv", "ex_items", 4), ("lots.csv", "ex_lots", 5)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def view(c, l):
    it = c.execute("SELECT * FROM ex_items WHERE item_id=?", (l["item_id"],)).fetchone()
    days = (date.fromisoformat(l["expires_on"]) - date.today()).days
    state = "expired" if days < 0 else ("near" if days <= int(it["near_days"]) else "ok")
    return {"lot_id": l["lot_id"], "item_id": l["item_id"], "item_name": it["name"], "produced_on": l["produced_on"], "expires_on": l["expires_on"],
            "days_left": days, "qty": int(l["qty"]), "state": state, "unit_price": int(it["unit_price"])}


def listing(c):
    rows = [view(c, l) for l in c.execute("SELECT * FROM ex_lots WHERE qty > 0").fetchall()]
    rows.sort(key=lambda r: (r["days_left"], r["lot_id"]))
    near = [r for r in rows if r["state"] == "near"]
    return {"lots": rows, "summary": {"near": len(near), "expired": sum(1 for r in rows if r["state"] == "expired"),
                                     "near_value": sum(r["unit_price"] * r["qty"] for r in near)}, "today": date.today().isoformat()}


def need_user(uid):
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, "사용자를 확인하세요")


def find_user(c, uid):
    u = c.execute("SELECT * FROM ex_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    return u


def is_int(v, lo):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo


def log(c, lid, by, kind, qty, note=""):
    c.execute("INSERT INTO ex_moves VALUES (?,?,?,?,?,?)", (lid, datetime.now().strftime("%Y-%m-%d %H:%M"), by, kind, qty, note))


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM ex_users ORDER BY rowid")]


@app.get("/api/items")
def items():
    return [{"item_id": i["item_id"], "name": i["name"], "unit_price": int(i["unit_price"]), "near_days": int(i["near_days"])}
            for i in con().execute("SELECT * FROM ex_items ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    return listing(con())


@app.post("/api/ship")
def ship(body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    qty = body.get("qty")
    if not is_int(qty, 1):
        raise HTTPException(400, "수량을 확인하세요")
    with LOCK:
        c = con()
        u = find_user(c, body["user"])
        if not c.execute("SELECT 1 FROM ex_items WHERE item_id=?", (body.get("item_id"),)).fetchone():
            raise HTTPException(404, "품목이 없습니다")
        today = date.today().isoformat()
        cands = [l for l in c.execute("SELECT * FROM ex_lots WHERE item_id=? AND qty > 0 ORDER BY expires_on, lot_id", (body["item_id"],))
                 if l["expires_on"] >= today]
        if sum(int(l["qty"]) for l in cands) < qty:
            raise HTTPException(409, "재고가 부족합니다")
        left, allocs = qty, []
        for l in cands:
            take = min(int(l["qty"]), left)
            if take <= 0:
                break
            c.execute("UPDATE ex_lots SET qty=qty-? WHERE lot_id=?", (take, l["lot_id"]))
            log(c, l["lot_id"], u["user_id"], "ship", take)
            allocs.append({"lot_id": l["lot_id"], "qty": take})
            left -= take
        c.commit()
        out = listing(c)
        return {"allocations": allocs, "lots": out["lots"], "summary": out["summary"]}


@app.post("/api/lots/{lid}/dispose")
def dispose(lid: str, body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    reason = body.get("reason")
    if not (isinstance(reason, str) and 1 <= len(reason.strip()) <= 200):
        raise HTTPException(400, "사유를 입력하세요")
    with LOCK:
        c = con()
        l = c.execute("SELECT * FROM ex_lots WHERE lot_id=?", (lid,)).fetchone()
        if not l:
            raise HTTPException(404, "로트가 없습니다")
        u = find_user(c, body["user"])
        if u["role"] != "manager":
            raise HTTPException(403, "관리자만 할 수 있습니다")
        v = view(c, l)
        if v["qty"] == 0:
            raise HTTPException(409, "이미 비어 있는 로트입니다")
        if v["state"] != "expired":
            raise HTTPException(409, "만료된 로트만 폐기할 수 있습니다")
        c.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lid,))
        log(c, lid, u["user_id"], "dispose", v["qty"], reason.strip())
        c.commit()
        return {"lot": view(c, c.execute("SELECT * FROM ex_lots WHERE lot_id=?", (lid,)).fetchone()), "summary": listing(c)["summary"]}
