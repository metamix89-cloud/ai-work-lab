"""꼬르륵식품 유통기한 임박 재고 알림판 (FastAPI + SQLite)"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("GGORUREUK_DB", str(BASE / "inventory.db"))
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
URGENT_DAYS = 7    # 임박: D-7 이내
WARN_DAYS = 30     # 주의: D-30 이내

app = FastAPI(title="꼬르륵식품 유통기한 알림판")


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS lots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT NOT NULL, name TEXT NOT NULL, lot_no TEXT NOT NULL UNIQUE,
  qty INTEGER NOT NULL CHECK(qty >= 0),
  expiry TEXT NOT NULL, location TEXT NOT NULL DEFAULT '',
  disposed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
  kind TEXT NOT NULL, sku TEXT, name TEXT, lot_no TEXT, qty INTEGER, note TEXT);
"""


def add_log(con, kind, lot, qty, note=""):
    con.execute(
        "INSERT INTO log(at,kind,sku,name,lot_no,qty,note) VALUES(?,?,?,?,?,?,?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kind, lot["sku"], lot["name"], lot["lot_no"], qty, note),
    )


def seed(con):
    today = date.today()
    items = [  # sku, 상품명, 로트, 수량, 유통기한까지 남은 일수, 위치
        ("RMN-001", "꼬르륵 매운라면 5입", "L2601-A", 120, -5, "A-01"),
        ("RMN-001", "꼬르륵 매운라면 5입", "L2607-B", 300, 3, "A-01"),
        ("RMN-001", "꼬르륵 매운라면 5입", "L2609-C", 500, 120, "A-02"),
        ("DMP-002", "꼬르륵 왕만두 1kg", "L2608-A", 80, -2, "C-03"),
        ("DMP-002", "꼬르륵 왕만두 1kg", "L2609-B", 150, 6, "C-03"),
        ("DMP-002", "꼬르륵 왕만두 1kg", "L2610-C", 220, 45, "C-04"),
        ("SOY-003", "꼬르륵 간장 1.8L", "L2512-A", 60, 25, "B-02"),
        ("SOY-003", "꼬르륵 간장 1.8L", "L2603-B", 200, 240, "B-02"),
        ("KMC-004", "꼬르륵 포기김치 3kg", "L2610-A", 90, 1, "C-01"),
        ("KMC-004", "꼬르륵 포기김치 3kg", "L2610-B", 140, 14, "C-01"),
        ("KMC-004", "꼬르륵 포기김치 3kg", "L2611-C", 180, 40, "C-02"),
        ("SNK-005", "꼬르륵 쌀과자 오리지널", "L2605-A", 400, 18, "A-05"),
        ("SNK-005", "꼬르륵 쌀과자 오리지널", "L2608-B", 350, 75, "A-05"),
        ("MLK-006", "꼬르륵 바나나우유 6입", "L2610-M", 70, 0, "C-06"),
        ("MLK-006", "꼬르륵 바나나우유 6입", "L2611-N", 160, 9, "C-06"),
        ("CUR-007", "꼬르륵 3분 카레 순한맛", "L2604-A", 260, 300, "B-04"),
    ]
    for sku, name, lot, qty, d, loc in items:
        con.execute(
            "INSERT INTO lots(sku,name,lot_no,qty,expiry,location) VALUES(?,?,?,?,?,?)",
            (sku, name, lot, qty, (today + timedelta(days=d)).isoformat(), loc),
        )


@app.on_event("startup")
def init():
    with db() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM lots").fetchone()[0] == 0:
            seed(con)


def classify(expiry: str):
    days = (date.fromisoformat(expiry) - date.today()).days
    if days < 0:
        return days, "expired"
    if days <= URGENT_DAYS:
        return days, "urgent"
    if days <= WARN_DAYS:
        return days, "warn"
    return days, "ok"


def lot_dict(r):
    d = dict(r)
    d["days_left"], d["status"] = classify(d["expiry"])
    return d


def require_admin(pin):
    if pin != ADMIN_PIN:
        raise HTTPException(403, "관리자 PIN이 올바르지 않습니다.")


@app.get("/api/lots")
def lots():
    with db() as con:
        rows = con.execute(
            "SELECT * FROM lots WHERE disposed=0 AND qty>0 ORDER BY expiry, lot_no").fetchall()
    return [lot_dict(r) for r in rows]


@app.get("/api/summary")
def summary():
    out = {k: {"lots": 0, "qty": 0} for k in ("expired", "urgent", "warn", "ok")}
    for l in lots():
        out[l["status"]]["lots"] += 1
        out[l["status"]]["qty"] += l["qty"]
    return {"summary": out, "urgent_days": URGENT_DAYS, "warn_days": WARN_DAYS, "today": date.today().isoformat()}


@app.get("/api/products")
def products():
    """출고 가능(미만료) 재고를 SKU별로 집계"""
    agg = {}
    for l in lots():
        p = agg.setdefault(l["sku"], {"sku": l["sku"], "name": l["name"], "available": 0})
        if l["status"] != "expired":
            p["available"] += l["qty"]
    return sorted(agg.values(), key=lambda p: p["sku"])


class Ship(BaseModel):
    sku: str
    qty: int = Field(gt=0)


@app.post("/api/ship")
def ship(req: Ship):
    """FEFO 출고: 유통기한이 가까운 로트부터 차감. 만료 로트는 출고 불가."""
    today = date.today().isoformat()
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        rows = con.execute(
            "SELECT * FROM lots WHERE sku=? AND disposed=0 AND qty>0 AND expiry>=? ORDER BY expiry, id",
            (req.sku, today)).fetchall()
        if not rows:
            raise HTTPException(404, "출고 가능한 재고가 없습니다.")
        avail = sum(r["qty"] for r in rows)
        if avail < req.qty:
            raise HTTPException(409, f"재고 부족: 출고 가능 {avail}개 (만료분 제외)")
        left, picks = req.qty, []
        for r in rows:
            if left == 0:
                break
            take = min(left, r["qty"])
            con.execute("UPDATE lots SET qty=qty-? WHERE id=?", (take, r["id"]))
            add_log(con, "ship", r, take, "FEFO 출고")
            picks.append({"lot_no": r["lot_no"], "expiry": r["expiry"], "qty": take, "location": r["location"]})
            left -= take
    return {"sku": req.sku, "qty": req.qty, "picks": picks}


@app.post("/api/lots/{lot_id}/dispose")
def dispose(lot_id: int, x_admin_pin: str = Header(default="")):
    require_admin(x_admin_pin)
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        r = con.execute("SELECT * FROM lots WHERE id=? AND disposed=0 AND qty>0", (lot_id,)).fetchone()
        if not r:
            raise HTTPException(404, "로트를 찾을 수 없습니다.")
        if classify(r["expiry"])[1] != "expired":
            raise HTTPException(409, "만료된 로트만 폐기할 수 있습니다.")
        con.execute("UPDATE lots SET disposed=1 WHERE id=?", (lot_id,))
        add_log(con, "dispose", r, r["qty"], "만료 폐기")
    return {"ok": True, "lot_no": r["lot_no"], "qty": r["qty"]}


@app.get("/api/log")
def get_log():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM log ORDER BY id DESC LIMIT 50")]


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
