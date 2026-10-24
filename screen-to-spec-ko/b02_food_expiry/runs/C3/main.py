import csv
import os
import sqlite3
import threading
from datetime import date, datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "expiry.db")
lock = threading.Lock()


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE ex_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE ex_items(item_id TEXT PRIMARY KEY, name TEXT, unit_price INTEGER, near_days INTEGER);
    CREATE TABLE ex_lots(lot_id TEXT PRIMARY KEY, item_id TEXT, produced_on TEXT, expires_on TEXT, qty INTEGER);
    CREATE TABLE ex_moves(lot_id TEXT, at TEXT, by TEXT, kind TEXT, qty INTEGER, note TEXT);
    """)
    con.executemany("INSERT INTO ex_users VALUES(?,?,?)",
                    [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    con.executemany("INSERT INTO ex_items VALUES(?,?,?,?)",
                    [(r["item_id"], r["name"], int(r["unit_price"]), int(r["near_days"])) for r in read_csv("items.csv")])
    con.executemany("INSERT INTO ex_lots VALUES(?,?,?,?,?)",
                    [(r["lot_id"], r["item_id"], r["produced_on"], r["expires_on"], int(r["qty"])) for r in read_csv("lots.csv")])
    con.commit()
    con.close()


init_db()
app = FastAPI()


def conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def fail(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


def lot_view(r, today):
    left = (date.fromisoformat(r["expires_on"]) - today).days
    state = "expired" if left < 0 else ("near" if left <= r["near_days"] else "ok")
    return {"lot_id": r["lot_id"], "item_id": r["item_id"], "item_name": r["name"],
            "produced_on": r["produced_on"], "expires_on": r["expires_on"], "days_left": left,
            "qty": r["qty"], "state": state, "unit_price": r["unit_price"]}


LOT_SQL = ("SELECT l.*, i.name, i.unit_price, i.near_days FROM ex_lots l "
           "JOIN ex_items i ON i.item_id=l.item_id")


def board(con, only_id=None):
    today = date.today()
    rows = [lot_view(r, today) for r in con.execute(LOT_SQL)]
    if only_id:
        return next(x for x in rows if x["lot_id"] == only_id)
    lots = sorted((x for x in rows if x["qty"] > 0), key=lambda x: (x["days_left"], x["lot_id"]))
    return lots, summary(lots), today.isoformat()


def summary(lots):
    near = [x for x in lots if x["state"] == "near"]
    return {"near": len(near),
            "expired": sum(1 for x in lots if x["state"] == "expired"),
            "near_value": sum(x["unit_price"] * x["qty"] for x in near)}


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with conn() as con:
        return [dict(r) for r in con.execute("SELECT user_id,name,role FROM ex_users")]


@app.get("/api/items")
def items():
    with conn() as con:
        return [dict(r) for r in con.execute("SELECT item_id,name,unit_price,near_days FROM ex_items")]


@app.get("/api/lots")
def lots():
    with conn() as con:
        l, s, t = board(con)
    return {"lots": l, "summary": s, "today": t}


@app.post("/api/ship")
async def ship(request: Request):
    b = await body_of(request)
    user, item_id, qty = b.get("user"), b.get("item_id"), b.get("qty")
    if not isinstance(user, str) or not user:
        return fail(400, "사용자를 확인하세요")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        return fail(400, "수량을 확인하세요")
    with lock, conn() as con:
        if not con.execute("SELECT 1 FROM ex_users WHERE user_id=?", (user,)).fetchone():
            return fail(404, "없는 사용자입니다")
        if not isinstance(item_id, str) or not con.execute(
                "SELECT 1 FROM ex_items WHERE item_id=?", (item_id,)).fetchone():
            return fail(404, "없는 품목입니다")
        today = date.today()
        cand = [lot_view(r, today) for r in con.execute(LOT_SQL + " WHERE l.item_id=?", (item_id,))]
        cand = sorted((x for x in cand if x["state"] != "expired" and x["qty"] > 0),
                      key=lambda x: (x["expires_on"], x["lot_id"]))
        if sum(x["qty"] for x in cand) < qty:
            return fail(409, "재고가 부족합니다")
        need, alloc = qty, []
        now = datetime.now().isoformat(timespec="seconds")
        for x in cand:
            if need == 0:
                break
            take = min(need, x["qty"])
            con.execute("UPDATE ex_lots SET qty=qty-? WHERE lot_id=?", (take, x["lot_id"]))
            con.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                        (x["lot_id"], now, user, "ship", take, ""))
            alloc.append({"lot_id": x["lot_id"], "qty": take})
            need -= take
        con.commit()
        l, s, _ = board(con)
    return {"allocations": alloc, "lots": l, "summary": s}


@app.post("/api/lots/{lot_id}/dispose")
async def dispose(lot_id: str, request: Request):
    b = await body_of(request)
    user, reason = b.get("user"), b.get("reason")
    if not isinstance(user, str) or not user:
        return fail(400, "사용자를 확인하세요")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 200:
        return fail(400, "사유를 입력하세요")
    with lock, conn() as con:
        u = con.execute("SELECT role FROM ex_users WHERE user_id=?", (user,)).fetchone()
        if not u:
            return fail(404, "없는 사용자입니다")
        if not con.execute("SELECT 1 FROM ex_lots WHERE lot_id=?", (lot_id,)).fetchone():
            return fail(404, "없는 로트입니다")
        if u["role"] != "manager":
            return fail(403, "관리자만 할 수 있습니다")
        cur = board(con, lot_id)
        if cur["qty"] == 0:
            return fail(409, "이미 비어 있는 로트입니다")
        if cur["state"] != "expired":
            return fail(409, "만료된 로트만 폐기할 수 있습니다")
        con.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lot_id,))
        con.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                    (lot_id, datetime.now().isoformat(timespec="seconds"), user, "dispose",
                     cur["qty"], reason.strip()))
        con.commit()
        lot = board(con, lot_id)
        _, s, _ = board(con)
    return {"lot": lot, "summary": s}
