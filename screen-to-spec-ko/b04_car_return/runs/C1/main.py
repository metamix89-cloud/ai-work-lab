import csv
import os
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "rent.db")
FMT = "%Y-%m-%d %H:%M"
GRADE_FEE = {"minor": 30000, "major": 150000, "severe": 500000}
LOCK = threading.Lock()

app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = connect()
    con.executescript("""
    CREATE TABLE rt_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE rt_cars(car_id TEXT PRIMARY KEY, plate TEXT, model TEXT);
    CREATE TABLE rt_rentals(rental_id TEXT PRIMARY KEY, car_id TEXT, customer_id TEXT, out_at TEXT, due_at TEXT,
                            out_fuel INTEGER, out_km INTEGER, status TEXT);
    CREATE TABLE rt_pre_damages(rental_id TEXT, part TEXT);
    CREATE TABLE rt_returns(rental_id TEXT PRIMARY KEY, returned_at TEXT, fuel INTEGER, km INTEGER, late_minutes INTEGER,
                            late_fee INTEGER, fuel_fee INTEGER, damage_fee INTEGER, total INTEGER, by TEXT);
    CREATE TABLE rt_damages(rental_id TEXT, part TEXT, grade TEXT, photos INTEGER, fee INTEGER, pre_existing INTEGER);
    """)
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO rt_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("cars.csv"):
        con.execute("INSERT INTO rt_cars VALUES(?,?,?)", (r["car_id"], r["plate"], r["model"]))
    for r in read_csv("rentals.csv"):
        con.execute("INSERT INTO rt_rentals VALUES(?,?,?,?,?,?,?,?)",
                    (r["rental_id"], r["car_id"], r["customer_id"], r["out_at"], r["due_at"],
                     int(r["out_fuel"]), int(r["out_km"]), r["status"]))
    for r in read_csv("pre_damages.csv"):
        con.execute("INSERT INTO rt_pre_damages VALUES(?,?)", (r["rental_id"], r["part"]))
    con.commit()
    con.close()


init_db()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_user(con, uid):
    row = con.execute("SELECT * FROM rt_users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        raise Reject(404, "없는 사용자입니다")
    return row


def rental_dict(con, row):
    pre = [p["part"] for p in con.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (row["rental_id"],))]
    car = con.execute("SELECT * FROM rt_cars WHERE car_id=?", (row["car_id"],)).fetchone()
    cust = con.execute("SELECT name FROM rt_users WHERE user_id=?", (row["customer_id"],)).fetchone()
    return {"rental_id": row["rental_id"], "car_id": row["car_id"],
            "plate": car["plate"] if car else "", "model": car["model"] if car else "",
            "customer_id": row["customer_id"], "customer_name": cust["name"] if cust else "",
            "out_at": row["out_at"], "due_at": row["due_at"], "out_fuel": row["out_fuel"],
            "out_km": row["out_km"], "status": row["status"], "pre_damages": pre}


def charges_of(con, rid):
    r = con.execute("SELECT * FROM rt_returns WHERE rental_id=?", (rid,)).fetchone()
    if not r:
        return None
    dmg = [{"part": d["part"], "grade": d["grade"], "photos": d["photos"], "fee": d["fee"],
            "pre_existing": bool(d["pre_existing"])}
           for d in con.execute("SELECT * FROM rt_damages WHERE rental_id=? ORDER BY rowid", (rid,))]
    return {"returned_at": r["returned_at"], "fuel": r["fuel"], "km": r["km"], "late_minutes": r["late_minutes"],
            "late_fee": r["late_fee"], "fuel_fee": r["fuel_fee"], "damage_fee": r["damage_fee"],
            "total": r["total"], "damages": dmg}


def viewer_of(request):
    v = request.query_params.get("viewer")
    if not v:
        raise Reject(400, "사용자를 확인하세요")
    return v


@app.get("/api/users")
def users():
    con = connect()
    try:
        return [{"user_id": u["user_id"], "name": u["name"], "role": u["role"]}
                for u in con.execute("SELECT * FROM rt_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/rentals")
def rentals(request: Request):
    viewer = viewer_of(request)
    con = connect()
    try:
        u = get_user(con, viewer)
        rows = con.execute("SELECT * FROM rt_rentals ORDER BY due_at, rental_id").fetchall()
        if u["role"] != "staff":
            rows = [r for r in rows if r["customer_id"] == u["user_id"]]
        return [rental_dict(con, r) for r in rows]
    finally:
        con.close()


@app.get("/api/rentals/{rental_id}")
def rental_one(rental_id: str, request: Request):
    viewer = viewer_of(request)
    con = connect()
    try:
        u = get_user(con, viewer)
        row = con.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rental_id,)).fetchone()
        if not row:
            raise Reject(404, "없는 대여 건입니다")
        if u["role"] != "staff" and row["customer_id"] != u["user_id"]:
            raise Reject(403, "본인 대여 건만 볼 수 있습니다")
        d = rental_dict(con, row)
        d["charges"] = charges_of(con, rental_id) if row["status"] == "returned" else None
        return d
    finally:
        con.close()


def parse_time(s):
    try:
        return datetime.strptime(s, FMT)
    except (TypeError, ValueError):
        return None


def check_body(body):
    """본문만 보면 아는 400 들."""
    if not isinstance(body, dict) or not isinstance(body.get("user"), str) or not body["user"]:
        raise Reject(400, "사용자를 확인하세요")
    fuel = body.get("fuel")
    if not is_int(fuel) or not 0 <= fuel <= 8:
        raise Reject(400, "연료 칸은 0~8 입니다")
    dmgs = body.get("damages")
    if dmgs is None:
        dmgs = []
    if not isinstance(dmgs, list):
        raise Reject(400, "손상 항목을 확인하세요")
    seen = set()
    for d in dmgs:
        if not isinstance(d, dict) or not isinstance(d.get("part"), str) or not d["part"]:
            raise Reject(400, "손상 부위를 확인하세요")
        if d.get("grade") not in GRADE_FEE:
            raise Reject(400, "손상 등급을 확인하세요")
        if not is_int(d.get("photos")) or d["photos"] < 1:
            raise Reject(400, "손상 사진이 없습니다 (%s)" % d["part"])
        if d["part"] in seen:
            raise Reject(400, "같은 부위가 두 번 있습니다")
        seen.add(d["part"])
    if not is_int(body.get("km")):
        raise Reject(400, "주행거리를 확인하세요")
    ra = body.get("returned_at")
    if ra is not None and ra != "" and parse_time(ra) is None:
        raise Reject(400, "반납 시각 형식을 확인하세요")
    return dmgs


def compute(con, rental, body, dmgs):
    ret_at = parse_time(body.get("returned_at")) if body.get("returned_at") else datetime.now().replace(second=0, microsecond=0)
    if ret_at < parse_time(rental["out_at"]):
        raise Reject(400, "반납 시각이 대여 시각보다 앞입니다")
    if body["km"] < rental["out_km"]:
        raise Reject(400, "주행거리가 대여 때보다 적습니다")
    late = int((ret_at - parse_time(rental["due_at"])).total_seconds() // 60)
    late = max(late, 0)
    late_fee = 0 if late <= 30 else min(80000, -(-late // 60) * 10000)
    fuel_fee = max(0, rental["out_fuel"] - body["fuel"]) * 15000
    pre = {p["part"] for p in con.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (rental["rental_id"],))}
    out = []
    for d in dmgs:
        existing = d["part"] in pre
        out.append({"part": d["part"], "grade": d["grade"], "photos": d["photos"],
                    "fee": 0 if existing else GRADE_FEE[d["grade"]], "pre_existing": existing})
    dfee = sum(d["fee"] for d in out)
    return {"returned_at": ret_at.strftime(FMT), "late_minutes": late, "late_fee": late_fee, "fuel_fee": fuel_fee,
            "damage_fee": dfee, "total": late_fee + fuel_fee + dfee, "damages": out}


async def handle(rental_id, request, commit):
    try:
        body = await request.json()
    except Exception:
        body = None
    dmgs = check_body(body)
    with LOCK:
        con = connect()
        try:
            u = get_user(con, body["user"])
            rental = con.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rental_id,)).fetchone()
            if not rental:
                raise Reject(404, "없는 대여 건입니다")
            if u["role"] != "staff":
                raise Reject(403, "직원만 할 수 있습니다")
            res = compute(con, rental, body, dmgs)
            if rental["status"] != "out":
                raise Reject(409, "이미 반납 처리된 건입니다")
            if commit:
                con.execute("INSERT INTO rt_returns VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (rental_id, res["returned_at"], body["fuel"], body["km"], res["late_minutes"],
                             res["late_fee"], res["fuel_fee"], res["damage_fee"], res["total"], u["user_id"]))
                for d in res["damages"]:
                    con.execute("INSERT INTO rt_damages VALUES(?,?,?,?,?,?)",
                                (rental_id, d["part"], d["grade"], d["photos"], d["fee"], int(d["pre_existing"])))
                con.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=?", (rental_id,))
                con.commit()
            res.pop("returned_at")
            return res
        finally:
            con.close()


@app.post("/api/rentals/{rental_id}/quote")
async def quote(rental_id: str, request: Request):
    return await handle(rental_id, request, False)


@app.post("/api/rentals/{rental_id}/return")
async def do_return(rental_id: str, request: Request):
    res = await handle(rental_id, request, True)
    res["status"] = "returned"
    return JSONResponse(res, status_code=201)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
