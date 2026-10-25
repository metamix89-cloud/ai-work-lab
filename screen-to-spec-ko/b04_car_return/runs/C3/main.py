import csv
import os
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "rent.db")
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


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal"):
        try:
            os.remove(DB + suffix)
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
    c.commit()
    c.close()


init_db()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def rental_dict(c, row):
    d = dict(row)
    d["pre_damages"] = [p["part"] for p in c.execute(
        "SELECT part FROM rt_pre_damages WHERE rental_id=? ORDER BY rowid", (row["rental_id"],))]
    return d


RENTAL_SQL = """SELECT r.rental_id, r.car_id, c.plate, c.model, r.customer_id, u.name AS customer_name,
    r.out_at, r.due_at, r.out_fuel, r.out_km, r.status
    FROM rt_rentals r LEFT JOIN rt_cars c ON c.car_id=r.car_id LEFT JOIN rt_users u ON u.user_id=r.customer_id"""


def get_user(c, uid):
    return c.execute("SELECT * FROM rt_users WHERE user_id=?", (uid,)).fetchone()


def check_viewer(viewer):
    if not isinstance(viewer, str) or not viewer:
        raise Reject(400, "사용자를 확인하세요")


@app.get("/api/users")
def users():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT user_id, name, role FROM rt_users ORDER BY rowid")]
    finally:
        c.close()


@app.get("/api/rentals")
def rentals(viewer: str = None):
    check_viewer(viewer)
    c = conn()
    try:
        u = get_user(c, viewer)
        if not u:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        sql = RENTAL_SQL
        args = ()
        if u["role"] != "staff":
            sql += " WHERE r.customer_id=?"
            args = (viewer,)
        sql += " ORDER BY r.due_at, r.rental_id"
        return [rental_dict(c, r) for r in c.execute(sql, args)]
    finally:
        c.close()


def load_charges(c, rid):
    r = c.execute("SELECT * FROM rt_returns WHERE rental_id=?", (rid,)).fetchone()
    if not r:
        return None
    d = {k: r[k] for k in ("returned_at", "fuel", "km", "late_minutes", "late_fee", "fuel_fee", "damage_fee", "total")}
    d["damages"] = [{"part": x["part"], "grade": x["grade"], "photos": x["photos"], "fee": x["fee"],
                     "pre_existing": bool(x["pre_existing"])}
                    for x in c.execute("SELECT * FROM rt_damages WHERE rental_id=? ORDER BY rowid", (rid,))]
    return d


@app.get("/api/rentals/{rental_id}")
def rental_one(rental_id: str, viewer: str = None):
    check_viewer(viewer)
    c = conn()
    try:
        u = get_user(c, viewer)
        if not u:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        row = c.execute(RENTAL_SQL + " WHERE r.rental_id=?", (rental_id,)).fetchone()
        if not row:
            raise Reject(404, "대여 건을 찾을 수 없습니다")
        if u["role"] != "staff" and row["customer_id"] != viewer:
            raise Reject(403, "본인 대여 건만 볼 수 있습니다")
        d = rental_dict(c, row)
        d["charges"] = load_charges(c, rental_id) if row["status"] == "returned" else None
        return d
    finally:
        c.close()


def parse_body(body):
    """본문만 보면 아는 검사(400). 정리된 값을 돌려준다."""
    if not isinstance(body, dict):
        body = {}
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
        raise Reject(400, "손상 항목을 확인하세요")
    seen = set()
    items = []
    for d in damages:
        if not isinstance(d, dict):
            raise Reject(400, "손상 항목을 확인하세요")
        part, grade, photos = d.get("part"), d.get("grade"), d.get("photos")
        if not isinstance(part, str) or not part:
            raise Reject(400, "손상 부위를 확인하세요")
        if not isinstance(grade, str) or grade not in GRADE_FEE:
            raise Reject(400, "손상 등급을 확인하세요")
        if not is_int(photos) or photos < 1:
            raise Reject(400, "손상 사진이 없습니다 (%s)" % part)
        if part in seen:
            raise Reject(400, "같은 부위가 두 번 있습니다")
        seen.add(part)
        items.append((part, grade, photos))
    km = body.get("km")
    if not is_int(km):
        raise Reject(400, "주행거리를 확인하세요")
    returned_at = body.get("returned_at")
    if returned_at is None or returned_at == "":
        when = datetime.now().replace(second=0, microsecond=0)
    else:
        try:
            when = datetime.strptime(returned_at, FMT) if isinstance(returned_at, str) else None
        except ValueError:
            when = None
        if when is None:
            raise Reject(400, "반납 시각을 확인하세요")
    return user, fuel, items, km, when


def compute(c, row, fuel, items, km, when, user_id):
    """대여 건을 찾아야 아는 검사(400) → 상태(409) → 요금 계산."""
    if km < row["out_km"]:
        raise Reject(400, "주행거리가 대여 때보다 적습니다")
    if when < datetime.strptime(row["out_at"], FMT):
        raise Reject(400, "반납 시각이 대여 시각보다 앞입니다")
    if row["status"] != "out":
        raise Reject(409, "이미 반납 처리된 건입니다")
    late = int((when - datetime.strptime(row["due_at"], FMT)).total_seconds() // 60)
    late = max(late, 0)
    late_fee = 0 if late <= 30 else min(-(-late // 60) * 10000, 80000)
    fuel_fee = max(row["out_fuel"] - fuel, 0) * 15000
    pre = {p["part"] for p in c.execute("SELECT part FROM rt_pre_damages WHERE rental_id=?", (row["rental_id"],))}
    damages = []
    for part, grade, photos in items:
        existing = part in pre
        damages.append({"part": part, "grade": grade, "photos": photos,
                        "fee": 0 if existing else GRADE_FEE[grade], "pre_existing": existing})
    damage_fee = sum(d["fee"] for d in damages)
    return {"late_minutes": late, "late_fee": late_fee, "fuel_fee": fuel_fee, "damage_fee": damage_fee,
            "total": late_fee + fuel_fee + damage_fee, "damages": damages}


async def read_body(request):
    try:
        return await request.json()
    except Exception:
        return {}


def handle(rental_id, body, commit):
    user, fuel, items, km, when = parse_body(body)
    with LOCK:
        c = conn()
        try:
            u = get_user(c, user)
            if not u:
                raise Reject(404, "사용자를 찾을 수 없습니다")
            row = c.execute("SELECT * FROM rt_rentals WHERE rental_id=?", (rental_id,)).fetchone()
            if not row:
                raise Reject(404, "대여 건을 찾을 수 없습니다")
            if u["role"] != "staff":
                raise Reject(403, "직원만 할 수 있습니다")
            res = compute(c, row, fuel, items, km, when, user)
            if commit:
                c.execute("INSERT INTO rt_returns VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (rental_id, when.strftime(FMT), fuel, km, res["late_minutes"], res["late_fee"],
                           res["fuel_fee"], res["damage_fee"], res["total"], user))
                for d in res["damages"]:
                    c.execute("INSERT INTO rt_damages VALUES(?,?,?,?,?,?)",
                              (rental_id, d["part"], d["grade"], d["photos"], d["fee"], int(d["pre_existing"])))
                c.execute("UPDATE rt_rentals SET status='returned' WHERE rental_id=?", (rental_id,))
                c.commit()
                res["status"] = "returned"
            return res
        finally:
            c.close()


@app.post("/api/rentals/{rental_id}/quote")
async def quote(rental_id: str, request: Request):
    return handle(rental_id, await read_body(request), False)


@app.post("/api/rentals/{rental_id}/return")
async def do_return(rental_id: str, request: Request):
    return JSONResponse(handle(rental_id, await read_body(request), True), status_code=201)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
