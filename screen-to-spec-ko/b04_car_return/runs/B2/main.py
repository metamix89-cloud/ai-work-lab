import csv
import math
import os
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "rent.db")
FMT = "%Y-%m-%d %H:%M"
GRADE_FEE = {"minor": 30000, "major": 150000, "severe": 500000}

app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def _reject(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(ROOT, "seed", name), encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def init_db():
    for ext in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(DB + ext)
        except OSError:
            pass
    c = conn()
    c.executescript("""
    CREATE TABLE rt_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE rt_cars(car_id TEXT PRIMARY KEY, plate TEXT, model TEXT);
    CREATE TABLE rt_rentals(rental_id TEXT PRIMARY KEY, car_id TEXT, customer_id TEXT, out_at TEXT,
        due_at TEXT, out_fuel INTEGER, out_km INTEGER, status TEXT);
    CREATE TABLE rt_pre_damages(rental_id TEXT, part TEXT);
    CREATE TABLE rt_returns(rental_id TEXT PRIMARY KEY, returned_at TEXT, fuel INTEGER, km INTEGER,
        late_minutes INTEGER, late_fee INTEGER, fuel_fee INTEGER, damage_fee INTEGER, total INTEGER, by TEXT);
    CREATE TABLE rt_damages(rental_id TEXT, part TEXT, grade TEXT, photos INTEGER, fee INTEGER, pre_existing INTEGER);
    """)
    c.executemany("INSERT INTO rt_users VALUES(?,?,?)",
                  [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    c.executemany("INSERT INTO rt_cars VALUES(?,?,?)",
                  [(r["car_id"], r["plate"], r["model"]) for r in read_csv("cars.csv")])
    c.executemany("INSERT INTO rt_rentals VALUES(?,?,?,?,?,?,?,?)",
                  [(r["rental_id"], r["car_id"], r["customer_id"], r["out_at"], r["due_at"],
                    int(r["out_fuel"]), int(r["out_km"]), r["status"]) for r in read_csv("rentals.csv")])
    c.executemany("INSERT INTO rt_pre_damages VALUES(?,?)",
                  [(r["rental_id"], r["part"]) for r in read_csv("pre_damages.csv")])
    c.commit()
    c.close()


init_db()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


BASE_SQL = """SELECT r.*, c.plate, c.model, u.name AS customer_name FROM rt_rentals r
    LEFT JOIN rt_cars c ON c.car_id=r.car_id LEFT JOIN rt_users u ON u.user_id=r.customer_id"""


def rental_dict(c, row):
    d = {k: row[k] for k in ("rental_id", "car_id", "plate", "model", "customer_id", "customer_name",
                             "out_at", "due_at", "out_fuel", "out_km", "status")}
    d["pre_damages"] = [r["part"] for r in c.execute(
        "SELECT part FROM rt_pre_damages WHERE rental_id=? ORDER BY rowid", (row["rental_id"],))]
    return d


def check_viewer(c, viewer):
    if not isinstance(viewer, str) or not viewer:
        raise Reject(400, "사용자를 확인하세요")
    u = c.execute("SELECT * FROM rt_users WHERE user_id=?", (viewer,)).fetchone()
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return u


@app.get("/api/users")
def users():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT user_id,name,role FROM rt_users ORDER BY rowid")]
    finally:
        c.close()


@app.get("/api/rentals")
def rentals(viewer: str = None):
    c = conn()
    try:
        u = check_viewer(c, viewer)
        rows = c.execute(BASE_SQL + " ORDER BY r.due_at, r.rental_id").fetchall()
        if u["role"] != "staff":
            rows = [r for r in rows if r["customer_id"] == u["user_id"]]
        return [rental_dict(c, r) for r in rows]
    finally:
        c.close()


def charges_of(c, rental_id, due_at):
    r = c.execute("SELECT * FROM rt_returns WHERE rental_id=?", (rental_id,)).fetchone()
    dm = [{"part": d["part"], "grade": d["grade"], "photos": d["photos"], "fee": d["fee"],
           "pre_existing": bool(d["pre_existing"])}
          for d in c.execute("SELECT * FROM rt_damages WHERE rental_id=? ORDER BY rowid", (rental_id,))]
    if r:
        return {"returned_at": r["returned_at"], "fuel": r["fuel"], "km": r["km"],
                "late_minutes": r["late_minutes"], "late_fee": r["late_fee"], "fuel_fee": r["fuel_fee"],
                "damage_fee": r["damage_fee"], "total": r["total"], "damages": dm}
    # 시드에서 이미 반납 완료로 들어온 건: 기록이 없으므로 청구 0원
    return {"returned_at": due_at, "fuel": None, "km": None, "late_minutes": 0, "late_fee": 0,
            "fuel_fee": 0, "damage_fee": 0, "total": 0, "damages": dm}


@app.get("/api/rentals/{rental_id}")
def rental_one(rental_id: str, viewer: str = None):
    c = conn()
    try:
        u = check_viewer(c, viewer)
        row = c.execute(BASE_SQL + " WHERE r.rental_id=?", (rental_id,)).fetchone()
        if not row:
            raise Reject(404, "대여 건을 찾을 수 없습니다")
        if u["role"] != "staff" and row["customer_id"] != u["user_id"]:
            raise Reject(403, "본인 대여 건만 볼 수 있습니다")
        d = rental_dict(c, row)
        d["charges"] = charges_of(c, rental_id, row["due_at"]) if row["status"] == "returned" else None
        return d
    finally:
        c.close()


def process(rental_id, body, commit):
    # 1) 본문만 보면 아는 400
    if not isinstance(body, dict):
        raise Reject(400, "사용자를 확인하세요")
    user = body.get("user")
    if not isinstance(user, str) or not user:
        raise Reject(400, "사용자를 확인하세요")
    fuel = body.get("fuel")
    if not is_int(fuel) or not 0 <= fuel <= 8:
        raise Reject(400, "연료 칸은 0~8 입니다")
    damages = body.get("damages")
    if damages is None:
        damages = []
    if not isinstance(damages, list):
        raise Reject(400, "손상 등급을 확인하세요")
    seen = set()
    for d in damages:
        if not isinstance(d, dict):
            raise Reject(400, "손상 등급을 확인하세요")
        part, grade, photos = d.get("part"), d.get("grade"), d.get("photos")
        if grade not in GRADE_FEE:
            raise Reject(400, "손상 등급을 확인하세요")
        if not is_int(photos) or photos < 1:
            raise Reject(400, "손상 사진이 없습니다 (%s)" % part)
        if part in seen:
            raise Reject(400, "같은 부위가 두 번 있습니다")
        seen.add(part)
    c = conn()
    try:
        # 2) 404 → 3) 403 → 4) 대여 건을 찾아야 아는 400 → 5) 409
        u = c.execute("SELECT * FROM rt_users WHERE user_id=?", (user,)).fetchone()
        if not u:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        row = c.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rental_id,)).fetchone()
        if not row:
            raise Reject(404, "대여 건을 찾을 수 없습니다")
        if u["role"] != "staff":
            raise Reject(403, "직원만 할 수 있습니다")
        km = body.get("km")
        if not is_int(km) or km < row["out_km"]:
            raise Reject(400, "주행거리가 대여 때보다 적습니다")
        ra = body.get("returned_at")
        if ra is None or ra == "":
            returned = datetime.now().replace(second=0, microsecond=0)
        else:
            try:
                returned = datetime.strptime(ra, FMT)
            except (TypeError, ValueError):
                raise Reject(400, "반납 시각 형식을 확인하세요 (YYYY-MM-DD HH:MM)")
        if returned < datetime.strptime(row["out_at"], FMT):
            raise Reject(400, "반납 시각이 대여 시각보다 앞입니다")
        if row["status"] != "out":
            raise Reject(409, "이미 반납 처리된 건입니다")

        due = datetime.strptime(row["due_at"], FMT)
        late = max(0, int((returned - due).total_seconds() // 60))
        late_fee = 0 if late <= 30 else min(80000, 10000 * math.ceil(late / 60))
        fuel_fee = max(0, row["out_fuel"] - fuel) * 15000
        pre = {r["part"] for r in c.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (rental_id,))}
        items = []
        for d in damages:
            existing = d["part"] in pre
            items.append({"part": d["part"], "grade": d["grade"], "photos": d["photos"],
                          "fee": 0 if existing else GRADE_FEE[d["grade"]], "pre_existing": existing})
        damage_fee = sum(i["fee"] for i in items)
        total = late_fee + fuel_fee + damage_fee
        out = {"late_minutes": late, "late_fee": late_fee, "fuel_fee": fuel_fee, "damage_fee": damage_fee,
               "total": total, "damages": items}
        if commit:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=? AND status='out'",
                            (rental_id,))
            if cur.rowcount != 1:
                c.rollback()
                raise Reject(409, "이미 반납 처리된 건입니다")
            c.execute("INSERT INTO rt_returns VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (rental_id, returned.strftime(FMT), fuel, km, late, late_fee, fuel_fee, damage_fee,
                       total, user))
            c.executemany("INSERT INTO rt_damages VALUES(?,?,?,?,?,?)",
                          [(rental_id, i["part"], i["grade"], i["photos"], i["fee"], int(i["pre_existing"]))
                           for i in items])
            c.commit()
            out["status"] = "returned"
        return out
    finally:
        c.close()


async def read_body(request: Request):
    try:
        return await request.json()
    except Exception:
        return None


@app.post("/api/rentals/{rental_id}/quote")
async def quote(rental_id: str, request: Request):
    return process(rental_id, await read_body(request), False)


@app.post("/api/rentals/{rental_id}/return")
async def do_return(rental_id: str, request: Request):
    return JSONResponse(process(rental_id, await read_body(request), True), status_code=201)


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))
