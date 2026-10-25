import csv
import math
import os
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "rent.db")
FMT = "%Y-%m-%d %H:%M"
GRADE_FEE = {"minor": 30000, "major": 150000, "severe": 500000}

SCHEMA = """
CREATE TABLE rt_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
CREATE TABLE rt_cars(car_id TEXT PRIMARY KEY, plate TEXT, model TEXT);
CREATE TABLE rt_rentals(rental_id TEXT PRIMARY KEY, car_id TEXT, customer_id TEXT,
  out_at TEXT, due_at TEXT, out_fuel INTEGER, out_km INTEGER, status TEXT);
CREATE TABLE rt_pre_damages(rental_id TEXT, part TEXT);
CREATE TABLE rt_returns(rental_id TEXT PRIMARY KEY, returned_at TEXT, fuel INTEGER, km INTEGER,
  late_minutes INTEGER, late_fee INTEGER, fuel_fee INTEGER, damage_fee INTEGER, total INTEGER, by TEXT);
CREATE TABLE rt_damages(rental_id TEXT, part TEXT, grade TEXT, photos INTEGER, fee INTEGER, pre_existing INTEGER);
"""


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO rt_users VALUES(?,?,?)", (r["user_id"].strip(), r["name"].strip(), r["role"].strip()))
    for r in read_csv("cars.csv"):
        con.execute("INSERT INTO rt_cars VALUES(?,?,?)", (r["car_id"].strip(), r["plate"].strip(), r["model"].strip()))
    for r in read_csv("rentals.csv"):
        con.execute(
            "INSERT INTO rt_rentals VALUES(?,?,?,?,?,?,?,?)",
            (r["rental_id"].strip(), r["car_id"].strip(), r["customer_id"].strip(), r["out_at"].strip(),
             r["due_at"].strip(), int(r["out_fuel"]), int(r["out_km"]), r["status"].strip()),
        )
    for r in read_csv("pre_damages.csv"):
        con.execute("INSERT INTO rt_pre_damages VALUES(?,?)", (r["rental_id"].strip(), r["part"].strip()))
    con.commit()
    con.close()


init_db()
app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def db():
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_user(uid):
    if not isinstance(uid, str) or not uid:
        raise Reject(400, "사용자를 확인하세요")
    return uid


def find_user(con, uid):
    row = con.execute("SELECT * FROM rt_users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return row


RENTAL_SQL = """SELECT r.*, c.plate, c.model, u.name AS customer_name FROM rt_rentals r
  LEFT JOIN rt_cars c ON c.car_id=r.car_id LEFT JOIN rt_users u ON u.user_id=r.customer_id"""


def rental_dict(con, row):
    d = {k: row[k] for k in ("rental_id", "car_id", "plate", "model", "customer_id", "customer_name",
                              "out_at", "due_at", "out_fuel", "out_km", "status")}
    d["pre_damages"] = [p["part"] for p in con.execute(
        "SELECT part FROM rt_pre_damages WHERE rental_id=? ORDER BY rowid", (row["rental_id"],))]
    return d


def charges(con, rid):
    r = con.execute("SELECT * FROM rt_returns WHERE rental_id=?", (rid,)).fetchone()
    if not r:
        return None
    out = {k: r[k] for k in ("returned_at", "fuel", "km", "late_minutes", "late_fee", "fuel_fee", "damage_fee", "total")}
    out["damages"] = [
        {"part": d["part"], "grade": d["grade"], "photos": d["photos"], "fee": d["fee"],
         "pre_existing": bool(d["pre_existing"])}
        for d in con.execute("SELECT * FROM rt_damages WHERE rental_id=? ORDER BY rowid", (rid,))
    ]
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT user_id,name,role FROM rt_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/rentals")
def rentals(viewer: str = None):
    check_user(viewer)
    con = db()
    try:
        u = find_user(con, viewer)
        sql = RENTAL_SQL
        args = ()
        if u["role"] != "staff":
            sql += " WHERE r.customer_id=?"
            args = (viewer,)
        sql += " ORDER BY r.due_at, r.rental_id"
        return [rental_dict(con, r) for r in con.execute(sql, args)]
    finally:
        con.close()


@app.get("/api/rentals/{rental_id}")
def rental(rental_id: str, viewer: str = None):
    check_user(viewer)
    con = db()
    try:
        u = find_user(con, viewer)
        row = con.execute(RENTAL_SQL + " WHERE r.rental_id=?", (rental_id,)).fetchone()
        if not row:
            raise Reject(404, "대여 건을 찾을 수 없습니다")
        if u["role"] != "staff" and row["customer_id"] != viewer:
            raise Reject(403, "본인 대여 건만 볼 수 있습니다")
        d = rental_dict(con, row)
        d["charges"] = charges(con, rental_id) if row["status"] == "returned" else None
        return d
    finally:
        con.close()


def parse_time(s):
    try:
        return datetime.strptime(s, FMT)
    except (ValueError, TypeError):
        raise Reject(400, "시각 형식을 확인하세요 (YYYY-MM-DD HH:MM)")


def check_body(body):
    """Rejections that need only the request body."""
    if not isinstance(body, dict):
        raise Reject(400, "사용자를 확인하세요")
    check_user(body.get("user"))
    fuel = body.get("fuel")
    if not is_int(fuel) or fuel < 0 or fuel > 8:
        raise Reject(400, "연료 칸은 0~8 입니다")
    dmgs = body.get("damages")
    if dmgs is None:
        dmgs = []
    if not isinstance(dmgs, list):
        raise Reject(400, "손상 항목을 확인하세요")
    seen = set()
    for d in dmgs:
        if not isinstance(d, dict):
            raise Reject(400, "손상 항목을 확인하세요")
        part = d.get("part")
        if not isinstance(part, str) or not part:
            raise Reject(400, "손상 부위를 확인하세요")
        if d.get("grade") not in GRADE_FEE:
            raise Reject(400, "손상 등급을 확인하세요")
        if not is_int(d.get("photos")) or d["photos"] < 1:
            raise Reject(400, f"손상 사진이 없습니다 ({part})")
        if part in seen:
            raise Reject(400, "같은 부위가 두 번 있습니다")
        seen.add(part)
    return dmgs


def compute(con, rid, body, dmgs):
    u = con.execute("SELECT * FROM rt_users WHERE user_id=?", (body["user"],)).fetchone()
    row = con.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rid,)).fetchone()
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    if not row:
        raise Reject(404, "대여 건을 찾을 수 없습니다")
    if u["role"] != "staff":
        raise Reject(403, "직원만 할 수 있습니다")
    km = body.get("km")
    if not is_int(km):
        raise Reject(400, "주행거리를 확인하세요")
    if km < row["out_km"]:
        raise Reject(400, "주행거리가 대여 때보다 적습니다")
    rat = body.get("returned_at")
    if rat is None or rat == "":
        rt = datetime.now().replace(second=0, microsecond=0)
    else:
        if not isinstance(rat, str):
            raise Reject(400, "시각 형식을 확인하세요 (YYYY-MM-DD HH:MM)")
        rt = parse_time(rat.strip())
    if rt < parse_time(row["out_at"]):
        raise Reject(400, "반납 시각이 대여 시각보다 앞입니다")
    if row["status"] != "out":
        raise Reject(409, "이미 반납 처리된 건입니다")

    late = max(0, int((rt - parse_time(row["due_at"])).total_seconds() // 60))
    late_fee = 0 if late <= 30 else min(80000, math.ceil(late / 60) * 10000)
    fuel_fee = max(0, row["out_fuel"] - body["fuel"]) * 15000
    pre = {p["part"] for p in con.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (rid,))}
    items = []
    damage_fee = 0
    for d in dmgs:
        existing = d["part"] in pre
        fee = 0 if existing else GRADE_FEE[d["grade"]]
        damage_fee += fee
        items.append({"part": d["part"], "grade": d["grade"], "photos": d["photos"], "fee": fee,
                      "pre_existing": existing})
    return {
        "returned_at": rt.strftime(FMT), "fuel": body["fuel"], "km": km,
        "late_minutes": late, "late_fee": late_fee, "fuel_fee": fuel_fee, "damage_fee": damage_fee,
        "total": late_fee + fuel_fee + damage_fee, "damages": items,
    }


async def read_body(request: Request):
    try:
        return await request.json()
    except Exception:
        return None


@app.post("/api/rentals/{rental_id}/quote")
async def quote(rental_id: str, request: Request):
    body = await read_body(request)
    dmgs = check_body(body)
    con = db()
    try:
        res = compute(con, rental_id, body, dmgs)
    finally:
        con.close()
    return {k: res[k] for k in ("late_minutes", "late_fee", "fuel_fee", "damage_fee", "total", "damages")}


@app.post("/api/rentals/{rental_id}/return")
async def do_return(rental_id: str, request: Request):
    body = await read_body(request)
    dmgs = check_body(body)
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            res = compute(con, rental_id, body, dmgs)
            con.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=?", (rental_id,))
            con.execute("INSERT INTO rt_returns VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (rental_id, res["returned_at"], res["fuel"], res["km"], res["late_minutes"],
                         res["late_fee"], res["fuel_fee"], res["damage_fee"], res["total"], body["user"]))
            for d in res["damages"]:
                con.execute("INSERT INTO rt_damages VALUES(?,?,?,?,?,?)",
                            (rental_id, d["part"], d["grade"], d["photos"], d["fee"], int(d["pre_existing"])))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    out = {k: res[k] for k in ("returned_at", "late_minutes", "late_fee", "fuel_fee", "damage_fee", "total", "damages")}
    out["status"] = "returned"
    return JSONResponse(out, status_code=201)
