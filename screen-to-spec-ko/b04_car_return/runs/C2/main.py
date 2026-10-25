import csv
import os
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "rent.db")
FMT = "%Y-%m-%d %H:%M"
PARTS = ["앞범퍼", "뒷범퍼", "운전석문", "조수석문", "보닛", "트렁크", "앞유리", "휠"]
GRADE_FEE = {"minor": 30000, "major": 150000, "severe": 500000}

SCHEMA = """
CREATE TABLE rt_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
CREATE TABLE rt_cars(car_id TEXT PRIMARY KEY, plate TEXT, model TEXT);
CREATE TABLE rt_rentals(rental_id TEXT PRIMARY KEY, car_id TEXT, customer_id TEXT, out_at TEXT, due_at TEXT,
  out_fuel INTEGER, out_km INTEGER, status TEXT);
CREATE TABLE rt_pre_damages(rental_id TEXT, part TEXT);
CREATE TABLE rt_returns(rental_id TEXT PRIMARY KEY, returned_at TEXT, fuel INTEGER, km INTEGER, late_minutes INTEGER,
  late_fee INTEGER, fuel_fee INTEGER, damage_fee INTEGER, total INTEGER, by TEXT);
CREATE TABLE rt_damages(rental_id TEXT, part TEXT, grade TEXT, photos INTEGER, fee INTEGER, pre_existing INTEGER);
"""


def conn():
    c = sqlite3.connect(DB, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    c = conn()
    c.executescript(SCHEMA)
    for r in read_csv("users.csv"):
        c.execute("INSERT INTO rt_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("cars.csv"):
        c.execute("INSERT INTO rt_cars VALUES(?,?,?)", (r["car_id"], r["plate"], r["model"]))
    for r in read_csv("rentals.csv"):
        c.execute("INSERT INTO rt_rentals VALUES(?,?,?,?,?,?,?,?)",
                  (r["rental_id"], r["car_id"], r["customer_id"], r["out_at"], r["due_at"],
                   int(r["out_fuel"]), int(r["out_km"]), r["status"]))
    for r in read_csv("pre_damages.csv"):
        c.execute("INSERT INTO rt_pre_damages VALUES(?,?)", (r["rental_id"], r["part"]))
    c.close()


init_db()
app = FastAPI()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def on_reject(request: Request, e: Reject):
    return JSONResponse({"detail": e.detail}, status_code=e.code)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def rental_dict(c, r):
    pre = [x["part"] for x in c.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (r["rental_id"],))]
    return {"rental_id": r["rental_id"], "car_id": r["car_id"], "plate": r["plate"], "model": r["model"],
            "customer_id": r["customer_id"], "customer_name": r["customer_name"], "out_at": r["out_at"],
            "due_at": r["due_at"], "out_fuel": r["out_fuel"], "out_km": r["out_km"], "status": r["status"],
            "pre_damages": pre}


RENTAL_SQL = """SELECT r.*, c.plate, c.model, u.name AS customer_name FROM rt_rentals r
  LEFT JOIN rt_cars c ON c.car_id=r.car_id LEFT JOIN rt_users u ON u.user_id=r.customer_id"""


def get_viewer(c, viewer):
    if not isinstance(viewer, str) or not viewer:
        raise Reject(400, "사용자를 확인하세요")
    u = c.execute("SELECT * FROM rt_users WHERE user_id=?", (viewer,)).fetchone()
    if not u:
        raise Reject(404, "없는 사용자입니다")
    return u


def charges_of(c, rid):
    t = c.execute("SELECT * FROM rt_returns WHERE rental_id=?", (rid,)).fetchone()
    if not t:
        return None
    dm = [{"part": d["part"], "grade": d["grade"], "photos": d["photos"], "fee": d["fee"],
           "pre_existing": bool(d["pre_existing"])}
          for d in c.execute("SELECT * FROM rt_damages WHERE rental_id=? ORDER BY rowid", (rid,))]
    return {"returned_at": t["returned_at"], "fuel": t["fuel"], "km": t["km"], "late_minutes": t["late_minutes"],
            "late_fee": t["late_fee"], "fuel_fee": t["fuel_fee"], "damage_fee": t["damage_fee"],
            "total": t["total"], "damages": dm}


@app.get("/api/users")
def users():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT user_id, name, role FROM rt_users ORDER BY rowid")]
    finally:
        c.close()


@app.get("/api/rentals")
def rentals(viewer: str = None):
    c = conn()
    try:
        u = get_viewer(c, viewer)
        sql = RENTAL_SQL
        args = ()
        if u["role"] != "staff":
            sql += " WHERE r.customer_id=?"
            args = (u["user_id"],)
        rows = c.execute(sql + " ORDER BY r.due_at, r.rental_id", args).fetchall()
        return [rental_dict(c, r) for r in rows]
    finally:
        c.close()


@app.get("/api/rentals/{rental_id}")
def rental_one(rental_id: str, viewer: str = None):
    c = conn()
    try:
        u = get_viewer(c, viewer)
        r = c.execute(RENTAL_SQL + " WHERE r.rental_id=?", (rental_id,)).fetchone()
        if not r:
            raise Reject(404, "없는 대여 건입니다")
        if u["role"] != "staff" and r["customer_id"] != u["user_id"]:
            raise Reject(403, "본인 대여 건만 볼 수 있습니다")
        d = rental_dict(c, r)
        d["charges"] = charges_of(c, rental_id) if r["status"] == "returned" else None
        return d
    finally:
        c.close()


def parse_body(body):
    """본문만 보면 아는 검사(400)."""
    if not isinstance(body, dict):
        raise Reject(400, "사용자를 확인하세요")
    user = body.get("user")
    if not isinstance(user, str) or not user:
        raise Reject(400, "사용자를 확인하세요")
    fuel = body.get("fuel")
    if not is_int(fuel) or not 0 <= fuel <= 8:
        raise Reject(400, "연료 칸은 0~8 입니다")
    raw = body.get("damages")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise Reject(400, "손상 항목을 확인하세요")
    seen = set()
    damages = []
    for d in raw:
        if not isinstance(d, dict):
            raise Reject(400, "손상 항목을 확인하세요")
        part, grade, photos = d.get("part"), d.get("grade"), d.get("photos")
        if not isinstance(grade, str) or grade not in GRADE_FEE:
            raise Reject(400, "손상 등급을 확인하세요")
        if not isinstance(part, str) or part not in PARTS:
            raise Reject(400, "손상 부위를 확인하세요")
        if not is_int(photos) or photos < 1:
            raise Reject(400, "손상 사진이 없습니다 (%s)" % part)
        if part in seen:
            raise Reject(400, "같은 부위가 두 번 있습니다")
        seen.add(part)
        damages.append((part, grade, photos))
    km = body.get("km")
    if not is_int(km):
        raise Reject(400, "주행거리를 확인하세요")
    at = body.get("returned_at")
    if at in (None, ""):
        when = datetime.now().replace(second=0, microsecond=0)
    else:
        try:
            when = datetime.strptime(at, FMT) if isinstance(at, str) else None
        except ValueError:
            when = None
        if when is None:
            raise Reject(400, "반납 시각 형식을 확인하세요")
    return user, fuel, km, damages, when


def compute(c, user, r, fuel, km, damages, when):
    if user["role"] != "staff":
        raise Reject(403, "직원만 할 수 있습니다")
    if km < r["out_km"]:
        raise Reject(400, "주행거리가 대여 때보다 적습니다")
    if when < datetime.strptime(r["out_at"], FMT):
        raise Reject(400, "반납 시각이 대여 시각보다 앞입니다")
    if r["status"] != "out":
        raise Reject(409, "이미 반납 처리된 건입니다")
    late = max(0, int((when - datetime.strptime(r["due_at"], FMT)).total_seconds() // 60))
    late_fee = 0 if late <= 30 else min(80000, -(-late // 60) * 10000)
    fuel_fee = max(0, r["out_fuel"] - fuel) * 15000
    pre = {x["part"] for x in c.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (r["rental_id"],))}
    items = []
    for part, grade, photos in damages:
        existing = part in pre
        items.append({"part": part, "grade": grade, "photos": photos,
                      "fee": 0 if existing else GRADE_FEE[grade], "pre_existing": existing})
    damage_fee = sum(i["fee"] for i in items)
    return {"late_minutes": late, "late_fee": late_fee, "fuel_fee": fuel_fee, "damage_fee": damage_fee,
            "total": late_fee + fuel_fee + damage_fee, "damages": items}


def handle(rental_id, body, commit):
    user_id, fuel, km, damages, when = parse_body(body)
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        user = c.execute("SELECT * FROM rt_users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            raise Reject(404, "없는 사용자입니다")
        r = c.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rental_id,)).fetchone()
        if not r:
            raise Reject(404, "없는 대여 건입니다")
        res = compute(c, user, r, fuel, km, damages, when)
        if commit:
            c.execute("INSERT INTO rt_returns VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (rental_id, when.strftime(FMT), fuel, km, res["late_minutes"], res["late_fee"],
                       res["fuel_fee"], res["damage_fee"], res["total"], user_id))
            for d in res["damages"]:
                c.execute("INSERT INTO rt_damages VALUES(?,?,?,?,?,?)",
                          (rental_id, d["part"], d["grade"], d["photos"], d["fee"], int(d["pre_existing"])))
            c.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=?", (rental_id,))
            res["status"] = "returned"
        c.execute("COMMIT")
        return res
    finally:
        c.close()


async def json_body(request: Request):
    try:
        return await request.json()
    except Exception:
        return None


@app.post("/api/rentals/{rental_id}/quote")
async def quote(rental_id: str, request: Request):
    return handle(rental_id, await json_body(request), False)


@app.post("/api/rentals/{rental_id}/return")
async def do_return(rental_id: str, request: Request):
    return JSONResponse(handle(rental_id, await json_body(request), True), status_code=201)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
