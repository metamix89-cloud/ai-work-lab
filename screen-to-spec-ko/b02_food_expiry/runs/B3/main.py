import csv
import os
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "expiry.db"
LOCK = threading.RLock()

app = FastAPI()
db: sqlite3.Connection


def init_db():
    global db
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(str(DB_PATH) + suffix)
        except OSError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE ex_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE ex_items(item_id TEXT PRIMARY KEY, name TEXT, unit_price INTEGER, near_days INTEGER);
        CREATE TABLE ex_lots(lot_id TEXT PRIMARY KEY, item_id TEXT, produced_on TEXT, expires_on TEXT, qty INTEGER);
        CREATE TABLE ex_moves(lot_id TEXT, at TEXT, by TEXT, kind TEXT, qty INTEGER, note TEXT);
        """
    )

    def read(name):
        with open(BASE / "seed" / name, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    db.executemany("INSERT INTO ex_users VALUES(?,?,?)",
                   [(r["user_id"].strip(), r["name"].strip(), r["role"].strip()) for r in read("users.csv")])
    db.executemany("INSERT INTO ex_items VALUES(?,?,?,?)",
                   [(r["item_id"].strip(), r["name"].strip(), int(r["unit_price"]), int(r["near_days"]))
                    for r in read("items.csv")])
    db.executemany("INSERT INTO ex_lots VALUES(?,?,?,?,?)",
                   [(r["lot_id"].strip(), r["item_id"].strip(), r["produced_on"].strip(),
                     r["expires_on"].strip(), int(r["qty"])) for r in read("lots.csv")])
    db.commit()


init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def state_of(days_left, near_days):
    if days_left < 0:
        return "expired"
    if days_left <= near_days:
        return "near"
    return "ok"


def lot_dict(r, today):
    days_left = (date.fromisoformat(r["expires_on"]) - today).days
    return {
        "lot_id": r["lot_id"], "item_id": r["item_id"], "item_name": r["item_name"],
        "produced_on": r["produced_on"], "expires_on": r["expires_on"],
        "days_left": days_left, "qty": r["qty"],
        "state": state_of(days_left, r["near_days"]), "unit_price": r["unit_price"],
    }


LOT_SQL = """SELECT l.*, i.name AS item_name, i.unit_price, i.near_days
             FROM ex_lots l JOIN ex_items i ON i.item_id = l.item_id"""


def all_lots(today):
    rows = db.execute(LOT_SQL + " WHERE l.qty > 0").fetchall()
    lots = [lot_dict(r, today) for r in rows]
    lots.sort(key=lambda x: (x["days_left"], x["lot_id"]))
    return lots


def summarize(lots):
    near = [x for x in lots if x["state"] == "near"]
    return {
        "near": len(near),
        "expired": sum(1 for x in lots if x["state"] == "expired"),
        "near_value": sum(x["unit_price"] * x["qty"] for x in near),
    }


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/users")
def users():
    with LOCK:
        return [dict(r) for r in db.execute("SELECT * FROM ex_users ORDER BY rowid")]


@app.get("/api/items")
def items():
    with LOCK:
        return [dict(r) for r in db.execute("SELECT * FROM ex_items ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    with LOCK:
        today = date.today()
        ls = all_lots(today)
        return {"lots": ls, "summary": summarize(ls), "today": today.isoformat()}


@app.post("/api/ship")
async def ship(request: Request):
    body = await body_of(request)
    user, item_id, qty = body.get("user"), body.get("item_id"), body.get("qty")
    if not isinstance(user, str) or not user:
        return err(400, "사용자를 확인하세요")
    if not is_int(qty) or qty < 1:
        return err(400, "수량을 확인하세요")
    if not isinstance(item_id, str) or not item_id:
        return err(400, "품목을 확인하세요")
    with LOCK:
        if not db.execute("SELECT 1 FROM ex_users WHERE user_id=?", (user,)).fetchone():
            return err(404, "없는 사용자입니다")
        if not db.execute("SELECT 1 FROM ex_items WHERE item_id=?", (item_id,)).fetchone():
            return err(404, "없는 품목입니다")
        today = date.today()
        rows = db.execute(LOT_SQL + " WHERE l.item_id=? AND l.qty>0 ORDER BY l.expires_on, l.lot_id",
                          (item_id,)).fetchall()
        usable = [r for r in rows if lot_dict(r, today)["state"] != "expired"]
        if sum(r["qty"] for r in usable) < qty:
            return err(409, "재고가 부족합니다")
        need, allocs = qty, []
        now = datetime.now().isoformat(timespec="seconds")
        for r in usable:
            if need <= 0:
                break
            take = min(need, r["qty"])
            db.execute("UPDATE ex_lots SET qty=qty-? WHERE lot_id=?", (take, r["lot_id"]))
            db.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                       (r["lot_id"], now, user, "ship", take, ""))
            allocs.append({"lot_id": r["lot_id"], "qty": take})
            need -= take
        db.commit()
        ls = all_lots(today)
        return {"allocations": allocs, "lots": ls, "summary": summarize(ls)}


@app.post("/api/lots/{lot_id}/dispose")
async def dispose(lot_id: str, request: Request):
    body = await body_of(request)
    user, reason = body.get("user"), body.get("reason")
    if not isinstance(user, str) or not user:
        return err(400, "사용자를 확인하세요")
    if not isinstance(reason, str) or not (1 <= len(reason.strip()) <= 200):
        return err(400, "사유를 입력하세요")
    reason = reason.strip()
    with LOCK:
        u = db.execute("SELECT * FROM ex_users WHERE user_id=?", (user,)).fetchone()
        if not u:
            return err(404, "없는 사용자입니다")
        r = db.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone()
        if not r:
            return err(404, "없는 로트입니다")
        if u["role"] != "manager":
            return err(403, "관리자만 할 수 있습니다")
        if r["qty"] <= 0:
            return err(409, "이미 비어 있는 로트입니다")
        today = date.today()
        if lot_dict(r, today)["state"] != "expired":
            return err(409, "만료된 로트만 폐기할 수 있습니다")
        db.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lot_id,))
        db.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                   (lot_id, datetime.now().isoformat(timespec="seconds"), user, "dispose", r["qty"], reason))
        db.commit()
        lot = lot_dict(db.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone(), today)
        return {"lot": lot, "summary": summarize(all_lots(today))}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
