import csv
import os
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "rent.db")
FMT = "%Y-%m-%d %H:%M"
GRADE_FEE = {"minor": 30000, "major": 150000, "severe": 500000}

app = FastAPI()
lock = threading.RLock()
db = None


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def read_csv(name):
    with open(os.path.join(SEED, name), newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def init_db():
    global db
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE rt_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE rt_cars(car_id TEXT PRIMARY KEY, plate TEXT, model TEXT);
        CREATE TABLE rt_rentals(rental_id TEXT PRIMARY KEY, car_id TEXT, customer_id TEXT,
            out_at TEXT, due_at TEXT, out_fuel INTEGER, out_km INTEGER, status TEXT);
        CREATE TABLE rt_pre_damages(rental_id TEXT, part TEXT);
        CREATE TABLE rt_returns(rental_id TEXT PRIMARY KEY, returned_at TEXT, fuel INTEGER, km INTEGER,
            late_minutes INTEGER, late_fee INTEGER, fuel_fee INTEGER, damage_fee INTEGER,
            total INTEGER, by TEXT);
        CREATE TABLE rt_damages(rental_id TEXT, part TEXT, grade TEXT, photos INTEGER,
            fee INTEGER, pre_existing INTEGER);
        """
    )
    for r in read_csv("users.csv"):
        db.execute("INSERT INTO rt_users VALUES(?,?,?)", (r["user_id"].strip(), r["name"].strip(), r["role"].strip()))
    for r in read_csv("cars.csv"):
        db.execute("INSERT INTO rt_cars VALUES(?,?,?)", (r["car_id"].strip(), r["plate"].strip(), r["model"].strip()))
    for r in read_csv("rentals.csv"):
        db.execute(
            "INSERT INTO rt_rentals VALUES(?,?,?,?,?,?,?,?)",
            (r["rental_id"].strip(), r["car_id"].strip(), r["customer_id"].strip(), r["out_at"].strip(),
             r["due_at"].strip(), int(r["out_fuel"]), int(r["out_km"]), r["status"].strip()),
        )
    for r in read_csv("pre_damages.csv"):
        db.execute("INSERT INTO rt_pre_damages VALUES(?,?)", (r["rental_id"].strip(), r["part"].strip()))
    db.commit()


init_db()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def fmt_min(dt):
    return dt.strftime(FMT)


def parse_time(s):
    try:
        return datetime.strptime(s, FMT)
    except (ValueError, TypeError):
        raise Reject(400, "시각 형식을 확인하세요")


def get_user(uid):
    row = db.execute("SELECT * FROM rt_users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        raise Reject(404, "없는 사용자입니다")
    return row


def rental_dict(row):
    pre = [p["part"] for p in db.execute(
        "SELECT part FROM rt_pre_damages WHERE rental_id=? ORDER BY rowid", (row["rental_id"],))]
    car = db.execute("SELECT * FROM rt_cars WHERE car_id=?", (row["car_id"],)).fetchone()
    cust = db.execute("SELECT name FROM rt_users WHERE user_id=?", (row["customer_id"],)).fetchone()
    return {
        "rental_id": row["rental_id"],
        "car_id": row["car_id"],
        "plate": car["plate"] if car else None,
        "model": car["model"] if car else None,
        "customer_id": row["customer_id"],
        "customer_name": cust["name"] if cust else None,
        "out_at": row["out_at"],
        "due_at": row["due_at"],
        "out_fuel": row["out_fuel"],
        "out_km": row["out_km"],
        "status": row["status"],
        "pre_damages": pre,
    }


def viewer_of(request):
    v = request.query_params.get("viewer")
    if not isinstance(v, str) or not v:
        raise Reject(400, "사용자를 확인하세요")
    return v


@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id,name,role FROM rt_users ORDER BY rowid")]


@app.get("/api/rentals")
def rentals(request: Request):
    viewer = viewer_of(request)
    with lock:
        u = get_user(viewer)
        rows = db.execute("SELECT * FROM rt_rentals ORDER BY due_at, rental_id").fetchall()
        if u["role"] != "staff":
            rows = [r for r in rows if r["customer_id"] == u["user_id"]]
        return [rental_dict(r) for r in rows]


def charges_of(rental_id):
    r = db.execute("SELECT * FROM rt_returns WHERE rental_id=?", (rental_id,)).fetchone()
    if not r:
        return None
    dmg = [
        {"part": d["part"], "grade": d["grade"], "photos": d["photos"], "fee": d["fee"],
         "pre_existing": bool(d["pre_existing"])}
        for d in db.execute("SELECT * FROM rt_damages WHERE rental_id=? ORDER BY rowid", (rental_id,))
    ]
    return {
        "returned_at": r["returned_at"], "fuel": r["fuel"], "km": r["km"],
        "late_minutes": r["late_minutes"], "late_fee": r["late_fee"], "fuel_fee": r["fuel_fee"],
        "damage_fee": r["damage_fee"], "total": r["total"], "damages": dmg,
    }


@app.get("/api/rentals/{rental_id}")
def rental_one(rental_id: str, request: Request):
    viewer = viewer_of(request)
    with lock:
        u = get_user(viewer)
        row = db.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rental_id,)).fetchone()
        if not row:
            raise Reject(404, "없는 대여 건입니다")
        if u["role"] != "staff" and row["customer_id"] != u["user_id"]:
            raise Reject(403, "본인 대여 건만 볼 수 있습니다")
        d = rental_dict(row)
        d["charges"] = charges_of(rental_id) if row["status"] == "returned" else None
        return d


def late_fee_of(minutes):
    if minutes <= 30:
        return 0
    hours = (minutes + 59) // 60
    return min(80000, 10000 * hours)


async def read_body(request):
    try:
        body = await request.json()
    except Exception:
        body = None
    return body if isinstance(body, dict) else {}


def process(rental_id, body, commit):
    # 1) 본문만 보면 아는 것 (400)
    user = body.get("user")
    if not isinstance(user, str) or not user:
        raise Reject(400, "사용자를 확인하세요")
    fuel = body.get("fuel")
    if not is_int(fuel) or fuel < 0 or fuel > 8:
        raise Reject(400, "연료 칸은 0~8 입니다")
    damages = body.get("damages")
    if damages is None:
        damages = []
    if not isinstance(damages, list):
        raise Reject(400, "손상 항목을 확인하세요")
    for d in damages:
        if not isinstance(d, dict):
            raise Reject(400, "손상 항목을 확인하세요")
        if d.get("grade") not in GRADE_FEE:
            raise Reject(400, "손상 등급을 확인하세요")
    for d in damages:
        part = d.get("part")
        if not is_int(d.get("photos")) or d["photos"] < 1:
            raise Reject(400, "손상 사진이 없습니다 (%s)" % (part,))
    seen = set()
    for d in damages:
        part = d.get("part")
        if not isinstance(part, str) or not part:
            raise Reject(400, "손상 부위를 확인하세요")
        if part in seen:
            raise Reject(400, "같은 부위가 두 번 있습니다")
        seen.add(part)
    km = body.get("km")
    if not is_int(km):
        raise Reject(400, "주행거리를 확인하세요")
    raw_at = body.get("returned_at")
    if raw_at is None or raw_at == "":
        returned_at = datetime.now().replace(second=0, microsecond=0)
    elif isinstance(raw_at, str):
        returned_at = parse_time(raw_at.strip())
    else:
        raise Reject(400, "시각 형식을 확인하세요")

    # 2) 없는 사용자 · 대여 건 (404)
    u = get_user(user)
    row = db.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rental_id,)).fetchone()
    if not row:
        raise Reject(404, "없는 대여 건입니다")
    # 3) 권한 (403)
    if u["role"] != "staff":
        raise Reject(403, "직원만 할 수 있습니다")
    # 4) 대여 건을 찾아야 아는 400
    if km < row["out_km"]:
        raise Reject(400, "주행거리가 대여 때보다 적습니다")
    if returned_at < parse_time(row["out_at"]):
        raise Reject(400, "반납 시각이 대여 시각보다 앞입니다")
    # 5) 상태 (409)
    if row["status"] != "out":
        raise Reject(409, "이미 반납 처리된 건입니다")

    due = parse_time(row["due_at"])
    late_minutes = max(0, int((returned_at - due).total_seconds() // 60))
    late_fee = late_fee_of(late_minutes)
    fuel_fee = max(0, row["out_fuel"] - fuel) * 15000
    pre = {p["part"] for p in db.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (rental_id,))}
    items = []
    for d in damages:
        existing = d["part"] in pre
        items.append({"part": d["part"], "grade": d["grade"], "photos": d["photos"],
                      "fee": 0 if existing else GRADE_FEE[d["grade"]], "pre_existing": existing})
    damage_fee = sum(i["fee"] for i in items)
    total = late_fee + fuel_fee + damage_fee
    result = {"late_minutes": late_minutes, "late_fee": late_fee, "fuel_fee": fuel_fee,
              "damage_fee": damage_fee, "total": total, "damages": items}
    if commit:
        db.execute("INSERT INTO rt_returns VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (rental_id, fmt_min(returned_at), fuel, km, late_minutes, late_fee, fuel_fee,
                    damage_fee, total, user))
        for i in items:
            db.execute("INSERT INTO rt_damages VALUES(?,?,?,?,?,?)",
                       (rental_id, i["part"], i["grade"], i["photos"], i["fee"], int(i["pre_existing"])))
        db.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=?", (rental_id,))
        db.commit()
        result["status"] = "returned"
        result["returned_at"] = fmt_min(returned_at)
    return result


@app.post("/api/rentals/{rental_id}/quote")
async def quote(rental_id: str, request: Request):
    body = await read_body(request)
    with lock:
        return process(rental_id, body, False)


@app.post("/api/rentals/{rental_id}/return")
async def do_return(rental_id: str, request: Request):
    body = await read_body(request)
    with lock:
        return JSONResponse(process(rental_id, body, True), status_code=201)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
