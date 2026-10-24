"""꼬르륵식품 유통기한 임박 재고 알림판 (FastAPI + SQLite)."""
import hmac
import os
import random
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("KORREUK_DB", str(BASE / "korreuk.db"))
ADMIN_PIN = os.environ.get("KORREUK_ADMIN_PIN", "1234")
DANGER_DAYS = 7    # D-7 이내: 긴급
WARN_DAYS = 30     # D-30 이내: 임박

app = FastAPI(title="꼬르륵식품 유통기한 알림판")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'EA'
);
CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    lot_no TEXT UNIQUE NOT NULL,
    expiry_date TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK (qty >= 0),
    location TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    disposed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lots_fefo ON lots(product_id, expiry_date);
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES lots(id),
    kind TEXT NOT NULL CHECK (kind IN ('IN','OUT','DISPOSE')),
    qty INTEGER NOT NULL,
    at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
"""


def seed(con):
    today = date.today()
    products = [
        ("KR-001", "꼬르륵 왕김밥", "EA"), ("KR-002", "꼬르륵 참치마요 삼각김밥", "EA"),
        ("KR-003", "꼬르륵 순두부찌개 밀키트", "BOX"), ("KR-004", "꼬르륵 수제 만두 1kg", "BAG"),
        ("KR-005", "꼬르륵 딸기우유 200ml", "EA"), ("KR-006", "꼬르륵 포기김치 3kg", "BOX"),
        ("KR-007", "꼬르륵 두부 300g", "EA"), ("KR-008", "꼬르륵 컵라면 큰사발", "BOX"),
    ]
    con.executemany("INSERT INTO products(sku,name,unit) VALUES (?,?,?)", products)
    pid = {r["sku"]: r["id"] for r in con.execute("SELECT id, sku FROM products")}
    # (sku, 유통기한까지 남은 일수, 수량, 위치)  음수 = 이미 만료
    plan = [
        ("KR-001", -3, 40, "A-01"), ("KR-001", 1, 60, "A-01"), ("KR-001", 6, 120, "A-02"), ("KR-001", 20, 200, "A-02"),
        ("KR-002", -1, 35, "A-03"), ("KR-002", 2, 80, "A-03"), ("KR-002", 9, 150, "A-04"),
        ("KR-003", 5, 24, "B-01"), ("KR-003", 25, 60, "B-01"), ("KR-003", 70, 100, "B-02"),
        ("KR-004", -10, 18, "C-01"), ("KR-004", 28, 90, "C-01"), ("KR-004", 120, 300, "C-02"),
        ("KR-005", 3, 96, "D-01"), ("KR-005", 14, 240, "D-01"), ("KR-005", 40, 480, "D-02"),
        ("KR-006", 12, 40, "C-03"), ("KR-006", 45, 70, "C-03"), ("KR-006", 90, 120, "C-04"),
        ("KR-007", -2, 52, "D-03"), ("KR-007", 4, 110, "D-03"), ("KR-007", 18, 180, "D-04"),
        ("KR-008", 60, 400, "E-01"), ("KR-008", 150, 800, "E-02"), ("KR-008", 240, 1200, "E-02"),
    ]
    n = 0
    for sku, days, qty, loc in plan:
        n += 1
        exp = today + timedelta(days=days)
        rec = today - timedelta(days=random.randint(10, 40))
        lot_no = f"L{exp:%y%m%d}-{sku[-3:]}-{n:02d}"
        cur = con.execute(
            "INSERT INTO lots(product_id,lot_no,expiry_date,qty,location,received_at) VALUES (?,?,?,?,?,?)",
            (pid[sku], lot_no, exp.isoformat(), qty, loc, rec.isoformat()))
        con.execute("INSERT INTO movements(lot_id,kind,qty,at,note) VALUES (?,?,?,?,?)",
                    (cur.lastrowid, "IN", qty, f"{rec.isoformat()} 09:00:00", "입고(가상 데이터)"))


def init_db():
    with closing(db()) as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            seed(con)
        con.commit()


init_db()


def status_of(days_left: int) -> str:
    if days_left < 0:
        return "expired"
    if days_left <= DANGER_DAYS:
        return "danger"
    if days_left <= WARN_DAYS:
        return "warn"
    return "ok"


def lot_row(r) -> dict:
    d = dict(r)
    d["days_left"] = (date.fromisoformat(d["expiry_date"]) - date.today()).days
    d["status"] = status_of(d["days_left"])
    return d


LOT_SQL = """SELECT l.id, l.lot_no, l.expiry_date, l.qty, l.location, l.received_at,
                    p.id AS product_id, p.sku, p.name, p.unit
             FROM lots l JOIN products p ON p.id = l.product_id
             WHERE l.disposed = 0 AND l.qty > 0"""


def require_admin(x_admin_pin: str = Header(default="")):
    if not hmac.compare_digest(x_admin_pin.encode(), ADMIN_PIN.encode()):
        raise HTTPException(403, "관리자 PIN이 올바르지 않습니다.")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/lots")
def list_lots():
    with closing(db()) as con:
        rows = con.execute(LOT_SQL + " ORDER BY l.expiry_date, p.name").fetchall()
    return [lot_row(r) for r in rows]


@app.get("/api/summary")
def summary():
    lots = list_lots()
    out = {s: {"lots": 0, "qty": 0} for s in ("expired", "danger", "warn", "ok")}
    for l in lots:
        out[l["status"]]["lots"] += 1
        out[l["status"]]["qty"] += l["qty"]
    return {"today": date.today().isoformat(), "danger_days": DANGER_DAYS,
            "warn_days": WARN_DAYS, "counts": out}


@app.get("/api/products")
def list_products():
    """제품별 출고 가능 수량(만료 제외)과 다음 출고될 로트(FEFO)."""
    today = date.today().isoformat()
    with closing(db()) as con:
        prods = con.execute("SELECT * FROM products ORDER BY name").fetchall()
        res = []
        for p in prods:
            lots = con.execute(
                "SELECT lot_no, expiry_date, qty FROM lots WHERE product_id=? AND disposed=0 AND qty>0 "
                "AND expiry_date >= ? ORDER BY expiry_date, id", (p["id"], today)).fetchall()
            res.append({**dict(p), "available": sum(l["qty"] for l in lots),
                        "next_lot": dict(lots[0]) if lots else None})
    return res


class ShipIn(BaseModel):
    product_id: int
    qty: int = Field(gt=0)
    note: str = ""


@app.post("/api/ship")
def ship(body: ShipIn):
    """FEFO 출고: 유통기한이 가까운 로트부터 차감. 만료 로트는 출고 대상에서 제외."""
    today = date.today().isoformat()
    with closing(db()) as con:
        con.execute("BEGIN IMMEDIATE")
        lots = con.execute(
            "SELECT id, lot_no, expiry_date, qty FROM lots WHERE product_id=? AND disposed=0 "
            "AND qty>0 AND expiry_date >= ? ORDER BY expiry_date, id", (body.product_id, today)).fetchall()
        avail = sum(l["qty"] for l in lots)
        if avail < body.qty:
            con.rollback()
            raise HTTPException(400, f"출고 가능 재고 부족 (요청 {body.qty}, 가능 {avail}; 만료 재고 제외)")
        left, picks = body.qty, []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for l in lots:
            if left == 0:
                break
            take = min(l["qty"], left)
            con.execute("UPDATE lots SET qty = qty - ? WHERE id=?", (take, l["id"]))
            con.execute("INSERT INTO movements(lot_id,kind,qty,at,note) VALUES (?,?,?,?,?)",
                        (l["id"], "OUT", take, now, body.note or "FEFO 출고"))
            picks.append({"lot_no": l["lot_no"], "expiry_date": l["expiry_date"], "qty": take})
            left -= take
        con.commit()
    return {"shipped": body.qty, "picks": picks}


class LotIn(BaseModel):
    product_id: int
    lot_no: str = Field(min_length=1)
    expiry_date: date
    qty: int = Field(gt=0)
    location: str = ""


@app.post("/api/lots")
def receive(body: LotIn):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(db()) as con:
        try:
            cur = con.execute(
                "INSERT INTO lots(product_id,lot_no,expiry_date,qty,location,received_at) VALUES (?,?,?,?,?,?)",
                (body.product_id, body.lot_no, body.expiry_date.isoformat(), body.qty,
                 body.location, date.today().isoformat()))
        except sqlite3.IntegrityError as e:
            raise HTTPException(400, f"입고 실패: 로트번호 중복 또는 제품 없음 ({e})")
        con.execute("INSERT INTO movements(lot_id,kind,qty,at,note) VALUES (?,?,?,?,?)",
                    (cur.lastrowid, "IN", body.qty, now, "입고"))
        con.commit()
    return {"ok": True}


@app.post("/api/lots/{lot_id}/dispose", dependencies=[Depends(require_admin)])
def dispose(lot_id: int):
    """만료된 로트 폐기 (관리자 전용). 만료되지 않은 로트는 폐기 불가."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(db()) as con:
        con.execute("BEGIN IMMEDIATE")
        l = con.execute("SELECT * FROM lots WHERE id=? AND disposed=0", (lot_id,)).fetchone()
        if not l:
            con.rollback()
            raise HTTPException(404, "폐기할 로트가 없습니다.")
        if l["expiry_date"] >= date.today().isoformat():
            con.rollback()
            raise HTTPException(400, "유통기한이 지나지 않은 로트는 폐기할 수 없습니다.")
        con.execute("UPDATE lots SET disposed=1, qty=0 WHERE id=?", (lot_id,))
        con.execute("INSERT INTO movements(lot_id,kind,qty,at,note) VALUES (?,?,?,?,?)",
                    (lot_id, "DISPOSE", l["qty"], now, "만료 폐기"))
        con.commit()
    return {"disposed": l["lot_no"], "qty": l["qty"]}


@app.post("/api/admin/check", dependencies=[Depends(require_admin)])
def admin_check():
    return {"ok": True}


@app.get("/api/movements")
def movements(limit: int = 50):
    with closing(db()) as con:
        rows = con.execute(
            "SELECT m.at, m.kind, m.qty, m.note, l.lot_no, p.name FROM movements m "
            "JOIN lots l ON l.id=m.lot_id JOIN products p ON p.id=l.product_id "
            "WHERE m.kind != 'IN' OR m.note NOT LIKE '%가상%' "
            "ORDER BY m.id DESC LIMIT ?", (min(limit, 200),)).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
