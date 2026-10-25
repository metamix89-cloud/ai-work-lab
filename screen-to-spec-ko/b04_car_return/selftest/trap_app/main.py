# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수를 일부러 넣었다. 정해진 테스트만 떨어져야 채점기가 그 실수를 잡는 것이다.
실수: ① 유예 30분을 '미만' 으로(30분도 청구) ② 지연 상한 없음 ③ 대여 전 손상도 청구 ④ 사진 0장도 받음 ⑤ 고객도 미리보기 · 반납 가능(권한 검사 없음)."""
import csv
import math
import os
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "rent.db")
app = FastAPI()
FMT = "%Y-%m-%d %H:%M"
GRADE_FEE = {"minor": 30000, "major": 150000, "severe": 500000}


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE rt_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE rt_cars(car_id TEXT PRIMARY KEY, plate TEXT, model TEXT);
    CREATE TABLE rt_rentals(rental_id TEXT PRIMARY KEY, car_id TEXT, customer_id TEXT, out_at TEXT, due_at TEXT, out_fuel INTEGER, out_km INTEGER, status TEXT);
    CREATE TABLE rt_pre_damages(rental_id TEXT, part TEXT);
    CREATE TABLE rt_returns(rental_id TEXT PRIMARY KEY, data TEXT);""")
    for name, table, n in (("users.csv", "rt_users", 3), ("cars.csv", "rt_cars", 3), ("rentals.csv", "rt_rentals", 8), ("pre_damages.csv", "rt_pre_damages", 2)):
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


def view(c, r):
    car = c.execute("SELECT * FROM rt_cars WHERE car_id=?", (r["car_id"],)).fetchone()
    cu = c.execute("SELECT name FROM rt_users WHERE user_id=?", (r["customer_id"],)).fetchone()
    return {"rental_id": r["rental_id"], "car_id": r["car_id"], "plate": car["plate"], "model": car["model"], "customer_id": r["customer_id"],
            "customer_name": cu["name"], "out_at": r["out_at"], "due_at": r["due_at"], "out_fuel": int(r["out_fuel"]), "out_km": int(r["out_km"]),
            "status": r["status"], "pre_damages": [x[0] for x in c.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (r["rental_id"],))]}


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>부릉부릉렌터카 반납 점검표</h1><select data-testid='user'><option value='s1'>한직원</option><option value='c1'>김고객</option></select><div data-testid='pre-damage'></div></body></html>"


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM rt_users ORDER BY rowid")]


@app.get("/api/rentals")
def rentals(viewer: str = Query(default="")):
    if not viewer:
        raise HTTPException(400, "사용자를 확인하세요")
    c = con()
    u = c.execute("SELECT * FROM rt_users WHERE user_id=?", (viewer,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    rows = c.execute("SELECT * FROM rt_rentals WHERE customer_id=? ORDER BY due_at, rental_id", (viewer,)) if u["role"] == "customer" else c.execute("SELECT * FROM rt_rentals ORDER BY due_at, rental_id")
    return [view(c, r) for r in rows.fetchall()]


@app.get("/api/rentals/{rid}")
def rental(rid: str, viewer: str = Query(default="")):
    if not viewer:
        raise HTTPException(400, "사용자를 확인하세요")
    c = con()
    r = c.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "대여 건이 없습니다")
    u = c.execute("SELECT * FROM rt_users WHERE user_id=?", (viewer,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    if u["role"] == "customer" and r["customer_id"] != viewer:
        raise HTTPException(403, "본인 대여 건만 볼 수 있습니다")
    v = view(c, r)
    x = c.execute("SELECT data FROM rt_returns WHERE rental_id=?", (rid,)).fetchone()
    import json
    v["charges"] = json.loads(x["data"]) if x else None
    return v


def calc(c, r, body):
    user = body.get("user")
    if not isinstance(user, str) or not user:
        raise HTTPException(400, "사용자를 확인하세요")
    fuel, km = body.get("fuel"), body.get("km")
    if not isinstance(fuel, int) or not 0 <= fuel <= 8:
        raise HTTPException(400, "연료 칸은 0~8 입니다")
    dm = body.get("damages") or []
    seen = set()
    for d in dm:
        if d.get("grade") not in GRADE_FEE:
            raise HTTPException(400, "손상 등급을 확인하세요")
        if d["part"] in seen:
            raise HTTPException(400, "같은 부위가 두 번 있습니다")
        seen.add(d["part"])
    when = body.get("returned_at") or datetime.now().strftime(FMT)
    ret_at, out_at, due_at = datetime.strptime(when, FMT), datetime.strptime(r["out_at"], FMT), datetime.strptime(r["due_at"], FMT)
    if ret_at < out_at:
        raise HTTPException(400, "반납 시각이 대여 시각보다 앞입니다")
    if km < int(r["out_km"]):
        raise HTTPException(400, "주행거리가 대여 때보다 적습니다")
    if r["status"] != "out":
        raise HTTPException(409, "이미 반납 처리된 건입니다")
    late_min = max(0, int((ret_at - due_at).total_seconds() // 60))
    late_fee = 0 if late_min < 30 else math.ceil(late_min / 60) * 10000          # ① 30분도 청구 ② 상한 없음
    fuel_fee = max(0, int(r["out_fuel"]) - fuel) * 15000
    items = [{"part": d["part"], "grade": d["grade"], "photos": int(d.get("photos", 0)), "fee": GRADE_FEE[d["grade"]], "pre_existing": False} for d in dm]   # ③ ④
    damage_fee = sum(i["fee"] for i in items)
    return {"returned_at": when, "fuel": fuel, "km": km, "late_minutes": late_min, "late_fee": late_fee, "fuel_fee": fuel_fee,
            "damage_fee": damage_fee, "total": late_fee + fuel_fee + damage_fee, "damages": items}


@app.post("/api/rentals/{rid}/quote")
def quote(rid: str, body: dict[str, Any] = Body(default={})):
    if not isinstance(body.get("user"), str) or not body.get("user"):
        raise HTTPException(400, "사용자를 확인하세요")
    c = con()
    r = c.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "대여 건이 없습니다")
    return calc(c, r, body)      # ⑤ 고객도 된다


@app.post("/api/rentals/{rid}/return", status_code=201)
def do_return(rid: str, body: dict[str, Any] = Body(default={})):
    import json
    if not isinstance(body.get("user"), str) or not body.get("user"):
        raise HTTPException(400, "사용자를 확인하세요")
    c = con()
    r = c.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "대여 건이 없습니다")
    q = calc(c, r, body)
    c.execute("INSERT INTO rt_returns VALUES (?,?)", (rid, json.dumps(q, ensure_ascii=False)))
    c.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=?", (rid,))
    c.commit()
    q["status"] = "returned"
    return q
