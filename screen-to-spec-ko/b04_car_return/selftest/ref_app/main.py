# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R9 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
지연 = 유예 30분(포함) · 시작된 1시간마다 10,000 · 상한 80,000. 연료 = 모자란 칸당 15,000. 손상 = 30,000 · 150,000 · 500,000, 대여 전 손상은 0원 · 사진 필수."""
import csv
import math
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "rent.db")
LOCK = threading.Lock()
app = FastAPI()
FMT = "%Y-%m-%d %H:%M"
GRACE_MIN, LATE_PER_HOUR, LATE_CAP = 30, 10000, 80000
FUEL_PER_BAR = 15000
GRADE_FEE = {"minor": 30000, "major": 150000, "severe": 500000}
PARTS = ["앞범퍼", "뒷범퍼", "운전석문", "조수석문", "보닛", "트렁크", "앞유리", "휠"]


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE rt_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE rt_cars(car_id TEXT PRIMARY KEY, plate TEXT, model TEXT);
    CREATE TABLE rt_rentals(rental_id TEXT PRIMARY KEY, car_id TEXT, customer_id TEXT, out_at TEXT, due_at TEXT, out_fuel INTEGER, out_km INTEGER, status TEXT);
    CREATE TABLE rt_pre_damages(rental_id TEXT, part TEXT);
    CREATE TABLE rt_returns(rental_id TEXT PRIMARY KEY, returned_at TEXT, fuel INTEGER, km INTEGER, late_minutes INTEGER, late_fee INTEGER, fuel_fee INTEGER, damage_fee INTEGER, total INTEGER, by TEXT);
    CREATE TABLE rt_damages(rental_id TEXT, part TEXT, grade TEXT, photos INTEGER, fee INTEGER, pre_existing INTEGER);""")
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


def need_user(uid):
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, "사용자를 확인하세요")


def find_user(c, uid):
    u = c.execute("SELECT * FROM rt_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    return u


def find_rental(c, rid):
    r = c.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "대여 건이 없습니다")
    return r


def pre_parts(c, rid):
    return [x[0] for x in c.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (rid,))]


def rental_view(c, r):
    car = c.execute("SELECT * FROM rt_cars WHERE car_id=?", (r["car_id"],)).fetchone()
    cu = c.execute("SELECT name FROM rt_users WHERE user_id=?", (r["customer_id"],)).fetchone()
    return {"rental_id": r["rental_id"], "car_id": r["car_id"], "plate": car["plate"] if car else None, "model": car["model"] if car else None,
            "customer_id": r["customer_id"], "customer_name": cu["name"] if cu else r["customer_id"], "out_at": r["out_at"], "due_at": r["due_at"],
            "out_fuel": int(r["out_fuel"]), "out_km": int(r["out_km"]), "status": r["status"], "pre_damages": pre_parts(c, r["rental_id"])}


def charges_view(c, rid):
    x = c.execute("SELECT * FROM rt_returns WHERE rental_id=?", (rid,)).fetchone()
    if not x:
        return None
    dm = [{"part": d["part"], "grade": d["grade"], "photos": int(d["photos"]), "fee": int(d["fee"]), "pre_existing": bool(d["pre_existing"])}
          for d in c.execute("SELECT * FROM rt_damages WHERE rental_id=?", (rid,))]
    return {"returned_at": x["returned_at"], "fuel": int(x["fuel"]), "km": int(x["km"]), "late_minutes": int(x["late_minutes"]), "late_fee": int(x["late_fee"]),
            "fuel_fee": int(x["fuel_fee"]), "damage_fee": int(x["damage_fee"]), "total": int(x["total"]), "damages": dm}


def parse_body(body):
    """본문만 보고 아는 400 — 사용자 · 연료 칸 · 등급 · 사진 · 같은 부위 두 번 (R9 첫 단계)"""
    need_user(body.get("user"))
    fuel, km = body.get("fuel"), body.get("km")
    if not isinstance(fuel, int) or isinstance(fuel, bool) or not 0 <= fuel <= 8:
        raise HTTPException(400, "연료 칸은 0~8 입니다")
    if not isinstance(km, int) or isinstance(km, bool) or km < 0:
        raise HTTPException(400, "주행거리를 확인하세요")
    dm = body.get("damages") or []
    if not isinstance(dm, list):
        raise HTTPException(400, "손상 목록을 확인하세요")
    seen = set()
    for d in dm:
        part, grade, photos = (d or {}).get("part"), (d or {}).get("grade"), (d or {}).get("photos")
        if not isinstance(part, str) or not part:
            raise HTTPException(400, "손상 부위를 확인하세요")
        if grade not in GRADE_FEE:
            raise HTTPException(400, "손상 등급을 확인하세요")
        if not isinstance(photos, int) or isinstance(photos, bool) or photos < 1:
            raise HTTPException(400, "손상 사진이 없습니다 (%s)" % part)
        if part in seen:
            raise HTTPException(400, "같은 부위가 두 번 있습니다")
        seen.add(part)
    when = body.get("returned_at")
    if when is None or when == "":
        when = datetime.now().strftime(FMT)
    try:
        datetime.strptime(when, FMT)
    except (TypeError, ValueError):
        raise HTTPException(400, "반납 시각 형식은 YYYY-MM-DD HH:MM 입니다")
    return when, fuel, km, dm


def calc(c, r, when, fuel, km, dm):
    """대여 건을 찾아야 아는 400 → 409 → 계산 (R1~R7)"""
    out_at, due_at = datetime.strptime(r["out_at"], FMT), datetime.strptime(r["due_at"], FMT)
    ret_at = datetime.strptime(when, FMT)
    if ret_at < out_at:
        raise HTTPException(400, "반납 시각이 대여 시각보다 앞입니다")
    if km < int(r["out_km"]):
        raise HTTPException(400, "주행거리가 대여 때보다 적습니다")
    if r["status"] != "out":
        raise HTTPException(409, "이미 반납 처리된 건입니다")
    late_min = max(0, int((ret_at - due_at).total_seconds() // 60))
    late_fee = 0 if late_min <= GRACE_MIN else min(LATE_CAP, math.ceil(late_min / 60) * LATE_PER_HOUR)
    fuel_fee = max(0, int(r["out_fuel"]) - fuel) * FUEL_PER_BAR
    pre = set(pre_parts(c, r["rental_id"]))
    items = []
    for d in dm:
        pe = d["part"] in pre
        items.append({"part": d["part"], "grade": d["grade"], "photos": int(d["photos"]), "fee": 0 if pe else GRADE_FEE[d["grade"]], "pre_existing": pe})
    damage_fee = sum(i["fee"] for i in items)
    return {"returned_at": when, "fuel": fuel, "km": km, "late_minutes": late_min, "late_fee": late_fee, "fuel_fee": fuel_fee,
            "damage_fee": damage_fee, "total": late_fee + fuel_fee + damage_fee, "damages": items}


def staff_only(c, uid):
    u = find_user(c, uid)
    if u["role"] != "staff":
        raise HTTPException(403, "직원만 할 수 있습니다")
    return u


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM rt_users ORDER BY rowid")]


@app.get("/api/rentals")
def rentals(viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    u = find_user(c, viewer)
    q = "SELECT * FROM rt_rentals"
    rows = c.execute(q + " WHERE customer_id=? ORDER BY due_at, rental_id", (viewer,)) if u["role"] == "customer" else c.execute(q + " ORDER BY due_at, rental_id")
    return [rental_view(c, r) for r in rows.fetchall()]


@app.get("/api/rentals/{rid}")
def rental(rid: str, viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    r = find_rental(c, rid)
    u = find_user(c, viewer)
    if u["role"] == "customer" and r["customer_id"] != u["user_id"]:
        raise HTTPException(403, "본인 대여 건만 볼 수 있습니다")
    v = rental_view(c, r)
    v["charges"] = charges_view(c, rid)
    return v


@app.post("/api/rentals/{rid}/quote")
def quote(rid: str, body: dict[str, Any] = Body(default={})):
    when, fuel, km, dm = parse_body(body)
    c = con()
    r = find_rental(c, rid)
    staff_only(c, body["user"])
    return calc(c, r, when, fuel, km, dm)


@app.post("/api/rentals/{rid}/return", status_code=201)
def do_return(rid: str, body: dict[str, Any] = Body(default={})):
    when, fuel, km, dm = parse_body(body)
    with LOCK:
        c = con()
        r = find_rental(c, rid)
        u = staff_only(c, body["user"])
        q = calc(c, r, when, fuel, km, dm)
        c.execute("INSERT INTO rt_returns VALUES (?,?,?,?,?,?,?,?,?,?)", (rid, when, fuel, km, q["late_minutes"], q["late_fee"], q["fuel_fee"], q["damage_fee"], q["total"], u["user_id"]))
        c.executemany("INSERT INTO rt_damages VALUES (?,?,?,?,?,?)", [(rid, d["part"], d["grade"], d["photos"], d["fee"], 1 if d["pre_existing"] else 0) for d in q["damages"]])
        c.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=?", (rid,))
        c.commit()
        q["status"] = "returned"
        return q
