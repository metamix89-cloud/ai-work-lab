import csv
import os
import sqlite3
import threading
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "expiry.db")
LOCK = threading.Lock()

app = FastAPI()


def connect():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    con = connect()
    con.executescript("""
        CREATE TABLE ex_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE ex_items(item_id TEXT PRIMARY KEY, name TEXT, unit_price INTEGER, near_days INTEGER);
        CREATE TABLE ex_lots(lot_id TEXT PRIMARY KEY, item_id TEXT, produced_on TEXT, expires_on TEXT, qty INTEGER);
        CREATE TABLE ex_moves(lot_id TEXT, at TEXT, by TEXT, kind TEXT, qty INTEGER, note TEXT);
    """)
    con.executemany("INSERT INTO ex_users VALUES(?,?,?)",
                    [(r["user_id"].strip(), r["name"].strip(), r["role"].strip()) for r in read_csv("users.csv")])
    con.executemany("INSERT INTO ex_items VALUES(?,?,?,?)",
                    [(r["item_id"].strip(), r["name"].strip(), int(r["unit_price"]), int(r["near_days"]))
                     for r in read_csv("items.csv")])
    con.executemany("INSERT INTO ex_lots VALUES(?,?,?,?,?)",
                    [(r["lot_id"].strip(), r["item_id"].strip(), r["produced_on"].strip(), r["expires_on"].strip(),
                      int(r["qty"])) for r in read_csv("lots.csv")])
    con.commit()
    con.close()


init_db()


def lot_dict(r, today):
    days = (date.fromisoformat(r["expires_on"]) - today).days
    state = "expired" if days < 0 else ("near" if days <= r["near_days"] else "ok")
    return {"lot_id": r["lot_id"], "item_id": r["item_id"], "item_name": r["item_name"],
            "produced_on": r["produced_on"], "expires_on": r["expires_on"], "days_left": days,
            "qty": r["qty"], "state": state, "unit_price": r["unit_price"]}


LOT_SQL = ("SELECT l.*, i.name AS item_name, i.unit_price, i.near_days "
           "FROM ex_lots l JOIN ex_items i ON i.item_id = l.item_id")


def board(con):
    today = date.today()
    lots = [lot_dict(r, today) for r in con.execute(LOT_SQL + " WHERE l.qty > 0")]
    lots.sort(key=lambda x: (x["days_left"], x["lot_id"]))
    near = [x for x in lots if x["state"] == "near"]
    summary = {"near": len(near),
               "expired": sum(1 for x in lots if x["state"] == "expired"),
               "near_value": sum(x["unit_price"] * x["qty"] for x in near)}
    return {"lots": lots, "summary": summary, "today": today.isoformat()}


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def check_user_field(data):
    u = data.get("user")
    if not isinstance(u, str) or not u:
        raise HTTPException(400, "사용자를 확인하세요")
    return u


def find_user(con, uid):
    r = con.execute("SELECT * FROM ex_users WHERE user_id=?", (uid,)).fetchone()
    if r is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다")
    return r


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html")


@app.get("/api/users")
def users():
    con = connect()
    try:
        return [dict(r) for r in con.execute("SELECT user_id, name, role FROM ex_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/items")
def items():
    con = connect()
    try:
        return [dict(r) for r in con.execute("SELECT item_id, name, unit_price, near_days FROM ex_items ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/lots")
def lots():
    con = connect()
    try:
        return board(con)
    finally:
        con.close()


@app.post("/api/ship")
async def ship(request: Request):
    data = await body_of(request)
    uid = check_user_field(data)
    qty = data.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise HTTPException(400, "수량을 확인하세요")
    item_id = data.get("item_id")
    with LOCK:
        con = connect()
        try:
            find_user(con, uid)
            if not isinstance(item_id, str) or con.execute(
                    "SELECT 1 FROM ex_items WHERE item_id=?", (item_id,)).fetchone() is None:
                raise HTTPException(404, "품목을 찾을 수 없습니다")
            today = date.today()
            cands = [lot_dict(r, today) for r in con.execute(LOT_SQL + " WHERE l.item_id=? AND l.qty>0", (item_id,))]
            cands = [x for x in cands if x["state"] != "expired"]
            cands.sort(key=lambda x: (x["expires_on"], x["lot_id"]))
            if sum(x["qty"] for x in cands) < qty:
                raise HTTPException(409, "재고가 부족합니다")
            left, allocs = qty, []
            now = datetime.now().isoformat(timespec="seconds")
            for x in cands:
                if left <= 0:
                    break
                take = min(left, x["qty"])
                con.execute("UPDATE ex_lots SET qty=qty-? WHERE lot_id=?", (take, x["lot_id"]))
                con.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)", (x["lot_id"], now, uid, "ship", take, ""))
                allocs.append({"lot_id": x["lot_id"], "qty": take})
                left -= take
            con.commit()
            b = board(con)
            return {"allocations": allocs, "lots": b["lots"], "summary": b["summary"]}
        finally:
            con.close()


@app.post("/api/lots/{lot_id}/dispose")
async def dispose(lot_id: str, request: Request):
    data = await body_of(request)
    uid = check_user_field(data)
    reason = data.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not 1 <= len(reason) <= 200:
        raise HTTPException(400, "사유를 입력하세요")
    with LOCK:
        con = connect()
        try:
            user = find_user(con, uid)
            row = con.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "로트를 찾을 수 없습니다")
            if user["role"] != "manager":
                raise HTTPException(403, "관리자만 할 수 있습니다")
            if row["qty"] <= 0:
                raise HTTPException(409, "이미 비어 있는 로트입니다")
            if lot_dict(row, date.today())["state"] != "expired":
                raise HTTPException(409, "만료된 로트만 폐기할 수 있습니다")
            con.execute("UPDATE ex_lots SET qty=0 WHERE lot_id=?", (lot_id,))
            con.execute("INSERT INTO ex_moves VALUES(?,?,?,?,?,?)",
                        (lot_id, datetime.now().isoformat(timespec="seconds"), uid, "dispose", row["qty"], reason))
            con.commit()
            lot = lot_dict(con.execute(LOT_SQL + " WHERE l.lot_id=?", (lot_id,)).fetchone(), date.today())
            return {"lot": lot, "summary": board(con)["summary"]}
        finally:
            con.close()
