import csv
import os
import sqlite3
import threading
from datetime import date, datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "expiry.db")
LOCK = threading.Lock()

app = FastAPI()


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE ex_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE ex_items(item_id TEXT PRIMARY KEY, name TEXT, unit_price INTEGER, near_days INTEGER);
    CREATE TABLE ex_lots(lot_id TEXT PRIMARY KEY, item_id TEXT, produced_on TEXT, expires_on TEXT, qty INTEGER);
    CREATE TABLE ex_moves(lot_id TEXT, at TEXT, by TEXT, kind TEXT, qty INTEGER, note TEXT);
    """)
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO ex_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("items.csv"):
        con.execute("INSERT INTO ex_items VALUES(?,?,?,?)",
                    (r["item_id"], r["name"], int(r["unit_price"]), int(r["near_days"])))
    for r in read_csv("lots.csv"):
        con.execute("INSERT INTO ex_lots VALUES(?,?,?,?,?)",
                    (r["lot_id"], r["item_id"], r["produced_on"], r["expires_on"], int(r["qty"])))
    con.commit()
    con.close()


init_db()


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def state_of(days_left, near_days):
    if days_left < 0:
        return "expired"
    return "near" if days_left <= near_days else "ok"


def lot_dict(r, today):
    days = (date.fromisoformat(r["expires_on"]) - today).days
    return {"lot_id": r["lot_id"], "item_id": r["item_id"], "item_name": r["item_name"],
            "produced_on": r["produced_on"], "expires_on": r["expires_on"], "days_left": days,
            "qty": r["qty"], "state": state_of(days, r["near_days"]), "unit_price": r["unit_price"]}


LOT_SQL = ("SELECT l.*, i.name AS item_name, i.unit_price, i.near_days "
           "FROM ex_lots l JOIN ex_items i ON i.item_id = l.item_id")


def board(con):
    today = date.today()
    lots = [lot_dict(r, today) for r in con.execute(LOT_SQL + " WHERE l.qty > 0")]
    lots.sort(key=lambda x: (x["days_left"], x["lot_id"]))
    summary = {"near": sum(1 for x in lots if x["state"] == "near"),
               "expired": sum(1 for x in lots if x["state"] == "expired"),
               "near_value": sum(x["unit_price"] * x["qty"] for x in lots if x["state"] == "near")}
    return lots, summary, today


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def user_str(b):
    u = b.get("user")
    if not isinstance(u, str) or not u.strip():
        raise Reject(400, "사용자를 확인하세요")
    return u


def find_user(con, uid):
    u = con.execute("SELECT * FROM ex_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise Reject(404, "없는 사용자입니다")
    return u


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")


@app.get("/api/users")
def users():
    with LOCK, db() as con:
        return [dict(r) for r in con.execute("SELECT user_id, name, role FROM ex_users ORDER BY rowid")]


@app.get("/api/items")
def items():
    with LOCK, db() as con:
        return [dict(r) for r in con.execute("SELECT item_id, name, unit_price, near_days FROM ex_items ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    with LOCK, db() as con:
        ls, summary, today = board(con)
    return {"lots": ls, "summary": summary, "today": today.isoformat()}


@app.post("/api/ship")
async def ship(request: Request):
    b = await body_of(request)
    uid = user_str(b)
    qty = b.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise Reject(400, "수량을 확인하세요")
    item_id = b.get("item_id")
    if not isinstance(item_id, str):
        raise Reject(400, "품목을 확인하세요")
    with LOCK, db() as con:
        find_user(con, uid)
        if not con.execute("SELECT 1 FROM ex_items WHERE item_id=?", (item_id,)).fetchone():
            raise Reject(404, "없는 품목입니다")
        today = date.today()
        cands = [r for r in con.execute(LOT_SQL + " WHERE l.item_id=? AND l.qty>0 "
                                        "ORDER BY l.expires_on, l.lot_id", (item_id,))
                 if (date.fromisoformat(r["expires_on"]) - today).days >= 0]
        if sum(r["qty"] for r in cands) < qty:
            raise Reject(409, "재고가 부족합니다")
        left, alloc = qty, []
        now = datetime.now().isoformat(timespec="seconds")
        for r in cands:
            if left <= 0:
                break
            take = min(left, r["qty"])
            con.execute("UPDATE ex_lots SET qty=qty-? WHERE lot_id=?", (take, r["lot_id"]))
            con.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                        (r["lot_id"], now, uid, "ship", take, ""))
            alloc.append({"lot_id": r["lot_id"], "qty": take})
            left -= take
        con.commit()
        ls, summary, _ = board(con)
    return {"allocations": alloc, "lots": ls, "summary": summary}


@app.post("/api/lots/{lot_id}/dispose")
async def dispose(lot_id: str, request: Request):
    b = await body_of(request)
    uid = user_str(b)
    reason = b.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not 1 <= len(reason) <= 200:
        raise Reject(400, "사유를 입력하세요")
    with LOCK, db() as con:
        r = con.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone()
        if not r:
            raise Reject(404, "없는 로트입니다")
        user = find_user(con, uid)
        if user["role"] != "manager":
            raise Reject(403, "관리자만 할 수 있습니다")
        if r["qty"] <= 0:
            raise Reject(409, "이미 비어 있는 로트입니다")
        today = date.today()
        if lot_dict(r, today)["state"] != "expired":
            raise Reject(409, "만료된 로트만 폐기할 수 있습니다")
        con.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lot_id,))
        con.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                    (lot_id, datetime.now().isoformat(timespec="seconds"), uid, "dispose", r["qty"], reason))
        con.commit()
        row = con.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone()
        lot = lot_dict(row, today)
        _, summary, _ = board(con)
    return {"lot": lot, "summary": summary}
