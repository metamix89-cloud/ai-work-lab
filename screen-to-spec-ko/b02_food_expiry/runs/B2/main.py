import csv
import datetime as dt
import os
import sqlite3
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "expiry.db")
lock = threading.RLock()

app = FastAPI()


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE ex_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE ex_items(item_id TEXT PRIMARY KEY, name TEXT, unit_price INTEGER, near_days INTEGER);
        CREATE TABLE ex_lots(lot_id TEXT PRIMARY KEY, item_id TEXT, produced_on TEXT, expires_on TEXT, qty INTEGER);
        CREATE TABLE ex_moves(lot_id TEXT, at TEXT, by TEXT, kind TEXT, qty INTEGER, note TEXT);
        """
    )
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO ex_users VALUES(?,?,?)", (r["user_id"].strip(), r["name"].strip(), r["role"].strip()))
    for r in read_csv("items.csv"):
        con.execute("INSERT INTO ex_items VALUES(?,?,?,?)",
                    (r["item_id"].strip(), r["name"].strip(), int(r["unit_price"]), int(r["near_days"])))
    for r in read_csv("lots.csv"):
        con.execute("INSERT INTO ex_lots VALUES(?,?,?,?,?)",
                    (r["lot_id"].strip(), r["item_id"].strip(), r["produced_on"].strip(),
                     r["expires_on"].strip(), int(r["qty"])))
    con.commit()
    return con


db = init_db()


def fail(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


LOT_SQL = """SELECT l.lot_id, l.item_id, i.name AS item_name, l.produced_on, l.expires_on, l.qty,
                    i.unit_price, i.near_days
             FROM ex_lots l JOIN ex_items i ON i.item_id = l.item_id"""


def lot_row(r, today):
    days = (dt.date.fromisoformat(r["expires_on"]) - today).days
    if days < 0:
        state = "expired"
    elif days <= r["near_days"]:
        state = "near"
    else:
        state = "ok"
    return {
        "lot_id": r["lot_id"], "item_id": r["item_id"], "item_name": r["item_name"],
        "produced_on": r["produced_on"], "expires_on": r["expires_on"],
        "days_left": days, "qty": r["qty"], "state": state, "unit_price": r["unit_price"],
    }


def all_lots():
    today = dt.date.today()
    lots = [lot_row(r, today) for r in db.execute(LOT_SQL + " WHERE l.qty > 0")]
    lots.sort(key=lambda x: (x["days_left"], x["lot_id"]))
    return lots


def summary(lots):
    near = [l for l in lots if l["state"] == "near" and l["qty"] > 0]
    return {
        "near": len(near),
        "expired": sum(1 for l in lots if l["state"] == "expired" and l["qty"] > 0),
        "near_value": sum(l["unit_price"] * l["qty"] for l in near),
    }


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def valid_user(b):
    u = b.get("user")
    return u if isinstance(u, str) and u != "" else None


@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id, name, role FROM ex_users ORDER BY rowid")]


@app.get("/api/items")
def items():
    with lock:
        return [dict(r) for r in db.execute("SELECT item_id, name, unit_price, near_days FROM ex_items ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    with lock:
        ls = all_lots()
        return {"lots": ls, "summary": summary(ls), "today": dt.date.today().isoformat()}


@app.post("/api/ship")
async def ship(request: Request):
    b = await body_of(request)
    # 400: 본문만 보면 아는 것
    user = valid_user(b)
    if user is None:
        return fail(400, "사용자를 확인하세요")
    qty = b.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        return fail(400, "수량을 확인하세요")
    item_id = b.get("item_id")
    if not isinstance(item_id, str) or item_id == "":
        return fail(400, "품목을 확인하세요")
    with lock:
        # 404
        if not db.execute("SELECT 1 FROM ex_users WHERE user_id=?", (user,)).fetchone():
            return fail(404, "없는 사용자입니다")
        if not db.execute("SELECT 1 FROM ex_items WHERE item_id=?", (item_id,)).fetchone():
            return fail(404, "없는 품목입니다")
        # 409
        cand = [l for l in all_lots() if l["item_id"] == item_id and l["state"] != "expired"]
        cand.sort(key=lambda l: (l["expires_on"], l["lot_id"]))
        if sum(l["qty"] for l in cand) < qty:
            return fail(409, "재고가 부족합니다")
        left, allocs = qty, []
        now = dt.datetime.now().isoformat(timespec="seconds")
        for l in cand:
            if left <= 0:
                break
            take = min(left, l["qty"])
            db.execute("UPDATE ex_lots SET qty = qty - ? WHERE lot_id=?", (take, l["lot_id"]))
            db.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)", (l["lot_id"], now, user, "ship", take, ""))
            allocs.append({"lot_id": l["lot_id"], "qty": take})
            left -= take
        db.commit()
        ls = all_lots()
        return {"allocations": allocs, "lots": ls, "summary": summary(ls)}


@app.post("/api/lots/{lot_id}/dispose")
async def dispose(lot_id: str, request: Request):
    b = await body_of(request)
    user = valid_user(b)
    if user is None:
        return fail(400, "사용자를 확인하세요")
    reason = b.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not (1 <= len(reason) <= 200):
        return fail(400, "사유를 입력하세요")
    with lock:
        u = db.execute("SELECT role FROM ex_users WHERE user_id=?", (user,)).fetchone()
        if not u:
            return fail(404, "없는 사용자입니다")
        if not db.execute("SELECT 1 FROM ex_lots WHERE lot_id=?", (lot_id,)).fetchone():
            return fail(404, "없는 로트입니다")
        if u["role"] != "manager":
            return fail(403, "관리자만 할 수 있습니다")
        today = dt.date.today()
        cur = lot_row(db.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone(), today)
        if cur["qty"] <= 0:
            return fail(409, "이미 비어 있는 로트입니다")
        if cur["state"] != "expired":
            return fail(409, "만료된 로트만 폐기할 수 있습니다")
        db.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lot_id,))
        db.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                   (lot_id, dt.datetime.now().isoformat(timespec="seconds"), user, "dispose", cur["qty"], reason))
        db.commit()
        row = lot_row(db.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone(), today)
        return {"lot": row, "summary": summary(all_lots())}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")
