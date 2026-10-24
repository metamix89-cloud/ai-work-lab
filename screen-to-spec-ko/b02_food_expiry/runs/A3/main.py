"""꼬르륵식품 유통기한 임박 재고 알림판 - FastAPI + SQLite"""
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("GGORUREUK_DB", str(BASE / "inventory.db"))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "admin1234")  # 운영 시 환경변수로 교체
IMMINENT_DAYS = 7   # 이 일수 이내면 '임박'
WARNING_DAYS = 30   # 이 일수 이내면 '주의'

app = FastAPI(title="꼬르륵식품 재고 알림판")


# ---------- DB ----------
@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
    finally:
        con.close()


def init_db():
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS products(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'EA');
            CREATE TABLE IF NOT EXISTS lots(
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                lot_no TEXT NOT NULL UNIQUE,
                expiry_date TEXT NOT NULL,
                qty INTEGER NOT NULL CHECK(qty >= 0),
                received_at TEXT NOT NULL,
                disposed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS movements(
                id INTEGER PRIMARY KEY,
                lot_id INTEGER NOT NULL REFERENCES lots(id),
                kind TEXT NOT NULL CHECK(kind IN ('SHIP','DISPOSE','RECEIVE')),
                qty INTEGER NOT NULL, at TEXT NOT NULL, note TEXT);
            CREATE INDEX IF NOT EXISTS ix_lots_fefo ON lots(product_id, expiry_date);
            """
        )
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            seed(con)


def seed(con):
    today = date.today()
    products = [("꼬르륵 왕만두", "BOX"), ("꼬르륵 우유식빵", "EA"), ("꼬르륵 딸기잼", "EA"),
                ("꼬르륵 순두부", "EA"), ("꼬르륵 즉석국밥", "BOX"), ("꼬르륵 크림치즈", "EA")]
    con.executemany("INSERT INTO products(name, unit) VALUES (?,?)", products)
    # (제품idx, 만료까지 일수(음수=이미 만료), 수량)
    lots = [
        (1, -9, 24), (1, 3, 40), (1, 25, 120), (1, 90, 300),
        (2, -2, 15), (2, 1, 30), (2, 5, 60),
        (3, 12, 80), (3, 140, 200), (3, 240, 150),
        (4, -5, 18), (4, 2, 35), (4, 9, 50),
        (5, 18, 70), (5, 60, 160), (5, 180, 220),
        (6, -1, 12), (6, 6, 45), (6, 33, 90), (6, 75, 130),
    ]
    for i, (pid, d, q) in enumerate(lots, 1):
        exp = (today + timedelta(days=d)).isoformat()
        rec = (today - timedelta(days=30 + i)).isoformat()
        con.execute(
            "INSERT INTO lots(product_id, lot_no, expiry_date, qty, received_at) VALUES (?,?,?,?,?)",
            (pid, f"L{today:%y%m}-{i:03d}", exp, q, rec),
        )


init_db()


# ---------- 공통 ----------
def classify(expiry: str) -> tuple[str, int]:
    days = (date.fromisoformat(expiry) - date.today()).days
    if days < 0:
        return "expired", days
    if days <= IMMINENT_DAYS:
        return "imminent", days
    if days <= WARNING_DAYS:
        return "warning", days
    return "ok", days


def lot_dict(r) -> dict:
    status, days = classify(r["expiry_date"])
    return {
        "id": r["id"], "product_id": r["product_id"], "product": r["name"], "unit": r["unit"],
        "lot_no": r["lot_no"], "expiry_date": r["expiry_date"], "qty": r["qty"],
        "received_at": r["received_at"], "status": status, "days_left": days,
    }


def require_admin(x_admin_token: str = Header(default="")):
    if not secrets.compare_digest(x_admin_token.encode(), ADMIN_TOKEN.encode()):
        raise HTTPException(401, "관리자 권한이 필요합니다.")


ACTIVE_LOTS = """
SELECT l.*, p.name, p.unit FROM lots l JOIN products p ON p.id = l.product_id
WHERE l.disposed = 0 AND l.qty > 0
"""


# ---------- API ----------
@app.get("/api/lots")
def list_lots():
    """유통기한 빠른 순(FEFO 순서)으로 활성 로트 반환"""
    with db() as con:
        rows = con.execute(ACTIVE_LOTS + " ORDER BY l.expiry_date, l.id").fetchall()
    return [lot_dict(r) for r in rows]


@app.get("/api/summary")
def summary():
    out = {k: {"lots": 0, "qty": 0} for k in ("expired", "imminent", "warning", "ok")}
    for l in list_lots():
        out[l["status"]]["lots"] += 1
        out[l["status"]]["qty"] += l["qty"]
    return {"today": date.today().isoformat(), "imminent_days": IMMINENT_DAYS,
            "warning_days": WARNING_DAYS, **out}


@app.get("/api/products")
def products():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM products ORDER BY name")]


class ShipReq(BaseModel):
    product_id: int
    qty: int = Field(gt=0)


@app.post("/api/ship")
def ship(req: ShipReq):
    """FEFO 출고: 만료되지 않은 로트를 유통기한 빠른 순으로 차감. 만료분은 출고 불가."""
    with db() as con:
        con.execute("BEGIN IMMEDIATE")  # 동시 출고 경쟁 방지
        try:
            if not con.execute("SELECT 1 FROM products WHERE id=?", (req.product_id,)).fetchone():
                raise HTTPException(404, "제품이 없습니다.")
            today = date.today().isoformat()
            lots = con.execute(
                ACTIVE_LOTS + " AND l.product_id=? AND l.expiry_date >= ? ORDER BY l.expiry_date, l.id",
                (req.product_id, today),
            ).fetchall()
            available = sum(l["qty"] for l in lots)
            if available < req.qty:
                raise HTTPException(409, f"출고 가능 재고 부족 (만료 제외 {available}, 요청 {req.qty})")
            need, picks = req.qty, []
            now = datetime.now().isoformat(timespec="seconds")
            for l in lots:
                if need == 0:
                    break
                take = min(need, l["qty"])
                con.execute("UPDATE lots SET qty = qty - ? WHERE id=?", (take, l["id"]))
                con.execute("INSERT INTO movements(lot_id,kind,qty,at) VALUES (?,'SHIP',?,?)",
                            (l["id"], take, now))
                picks.append({"lot_no": l["lot_no"], "expiry_date": l["expiry_date"], "qty": take,
                              "status": classify(l["expiry_date"])[0]})
                need -= take
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return {"shipped": req.qty, "picks": picks}


@app.post("/api/lots/{lot_id}/dispose", dependencies=[Depends(require_admin)])
def dispose(lot_id: int):
    """관리자 전용: 만료된 로트만 폐기"""
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            l = con.execute("SELECT * FROM lots WHERE id=? AND disposed=0", (lot_id,)).fetchone()
            if not l:
                raise HTTPException(404, "로트가 없거나 이미 폐기되었습니다.")
            if classify(l["expiry_date"])[0] != "expired":
                raise HTTPException(409, "만료된 로트만 폐기할 수 있습니다.")
            con.execute("UPDATE lots SET disposed=1, qty=0 WHERE id=?", (lot_id,))
            con.execute("INSERT INTO movements(lot_id,kind,qty,at,note) VALUES (?,'DISPOSE',?,?,?)",
                        (lot_id, l["qty"], datetime.now().isoformat(timespec="seconds"), "만료 폐기"))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return {"disposed": l["lot_no"], "qty": l["qty"]}


@app.get("/api/admin/check", dependencies=[Depends(require_admin)])
def admin_check():
    return {"ok": True}


@app.get("/api/movements")
def movements(limit: int = 30):
    with db() as con:
        rows = con.execute(
            """SELECT m.at, m.kind, m.qty, l.lot_no, p.name FROM movements m
               JOIN lots l ON l.id=m.lot_id JOIN products p ON p.id=l.product_id
               ORDER BY m.id DESC LIMIT ?""", (min(max(limit, 1), 200),)).fetchall()
    return [dict(r) for r in rows]


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
