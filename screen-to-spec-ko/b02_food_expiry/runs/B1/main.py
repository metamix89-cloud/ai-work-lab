import csv
import os
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "expiry.db"
lock = threading.RLock()


def read_csv(name):
    with open(BASE / "seed" / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
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
    con.executemany(
        "INSERT INTO ex_users VALUES(?,?,?)",
        [(r["user_id"].strip(), r["name"].strip(), r["role"].strip()) for r in read_csv("users.csv")],
    )
    con.executemany(
        "INSERT INTO ex_items VALUES(?,?,?,?)",
        [(r["item_id"].strip(), r["name"].strip(), int(r["unit_price"]), int(r["near_days"])) for r in read_csv("items.csv")],
    )
    con.executemany(
        "INSERT INTO ex_lots VALUES(?,?,?,?,?)",
        [
            (r["lot_id"].strip(), r["item_id"].strip(), r["produced_on"].strip(), r["expires_on"].strip(), int(r["qty"]))
            for r in read_csv("lots.csv")
        ],
    )
    con.commit()
    return con


db = init_db()
app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def today():
    return date.today()


def lot_row(r, t):
    days = (date.fromisoformat(r["expires_on"]) - t).days
    if days < 0:
        state = "expired"
    elif days <= r["near_days"]:
        state = "near"
    else:
        state = "ok"
    return {
        "lot_id": r["lot_id"],
        "item_id": r["item_id"],
        "item_name": r["item_name"],
        "produced_on": r["produced_on"],
        "expires_on": r["expires_on"],
        "days_left": days,
        "qty": r["qty"],
        "state": state,
        "unit_price": r["unit_price"],
    }


LOT_SQL = """
SELECT l.lot_id, l.item_id, i.name AS item_name, l.produced_on, l.expires_on, l.qty,
       i.unit_price, i.near_days
FROM ex_lots l JOIN ex_items i ON i.item_id = l.item_id
"""


def all_lots(include_empty=False):
    t = today()
    sql = LOT_SQL + ("" if include_empty else " WHERE l.qty > 0")
    rows = [lot_row(r, t) for r in db.execute(sql)]
    rows.sort(key=lambda x: (x["days_left"], x["lot_id"]))
    return rows


def summarize(lots):
    near = [l for l in lots if l["state"] == "near" and l["qty"] > 0]
    exp = [l for l in lots if l["state"] == "expired" and l["qty"] > 0]
    return {
        "near": len(near),
        "expired": len(exp),
        "near_value": sum(l["unit_price"] * l["qty"] for l in near),
    }


async def read_body(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    return body if isinstance(body, dict) else {}


def check_user_field(body):
    u = body.get("user")
    if not isinstance(u, str) or not u:
        raise Reject(400, "사용자를 확인하세요")
    return u


def find_user(uid):
    row = db.execute("SELECT * FROM ex_users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return row


@app.get("/api/users")
def users():
    return [dict(r) for r in db.execute("SELECT user_id,name,role FROM ex_users ORDER BY rowid")]


@app.get("/api/items")
def items():
    return [dict(r) for r in db.execute("SELECT item_id,name,unit_price,near_days FROM ex_items ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    with lock:
        ls = all_lots()
        return {"lots": ls, "summary": summarize(ls), "today": today().isoformat()}


@app.post("/api/ship")
async def ship(request: Request):
    body = await read_body(request)
    with lock:
        uid = check_user_field(body)
        qty = body.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise Reject(400, "수량을 확인하세요")
        item_id = body.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise Reject(400, "품목을 확인하세요")
        find_user(uid)
        if not db.execute("SELECT 1 FROM ex_items WHERE item_id=?", (item_id,)).fetchone():
            raise Reject(404, "품목을 찾을 수 없습니다")
        t = today()
        cands = [
            lot_row(r, t)
            for r in db.execute(LOT_SQL + " WHERE l.item_id=? AND l.qty>0", (item_id,))
        ]
        cands = [c for c in cands if c["state"] != "expired"]
        cands.sort(key=lambda c: (c["expires_on"], c["lot_id"]))
        if sum(c["qty"] for c in cands) < qty:
            raise Reject(409, "재고가 부족합니다")
        remain, allocs = qty, []
        now = datetime.now().isoformat(timespec="seconds")
        for c in cands:
            if remain == 0:
                break
            take = min(remain, c["qty"])
            db.execute("UPDATE ex_lots SET qty=qty-? WHERE lot_id=?", (take, c["lot_id"]))
            db.execute(
                "INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                (c["lot_id"], now, uid, "ship", take, ""),
            )
            allocs.append({"lot_id": c["lot_id"], "qty": take})
            remain -= take
        db.commit()
        ls = all_lots()
        return {"allocations": allocs, "lots": ls, "summary": summarize(ls)}


@app.post("/api/lots/{lot_id}/dispose")
async def dispose(lot_id: str, request: Request):
    body = await read_body(request)
    with lock:
        uid = check_user_field(body)
        reason = body.get("reason")
        reason = reason.strip() if isinstance(reason, str) else ""
        if not 1 <= len(reason) <= 200:
            raise Reject(400, "사유를 입력하세요")
        user = find_user(uid)
        row = db.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone()
        if not row:
            raise Reject(404, "로트를 찾을 수 없습니다")
        if user["role"] != "manager":
            raise Reject(403, "관리자만 할 수 있습니다")
        if row["qty"] <= 0:
            raise Reject(409, "이미 비어 있는 로트입니다")
        lot = lot_row(row, today())
        if lot["state"] != "expired":
            raise Reject(409, "만료된 로트만 폐기할 수 있습니다")
        db.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lot_id,))
        db.execute(
            "INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
            (lot_id, datetime.now().isoformat(timespec="seconds"), uid, "dispose", lot["qty"], reason),
        )
        db.commit()
        lot["qty"] = 0
        return {"lot": lot, "summary": summarize(all_lots())}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
