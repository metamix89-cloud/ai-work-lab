"""가나다식품 주문 · 재고 백오피스 서버: seed CSV 로 SQLite 를 만들고 주문 동작 API 와 화면을 낸다."""
import csv
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE_DIR = Path(__file__).resolve().parent
SEED_DIR = BASE_DIR / "seed"
DB_PATH = BASE_DIR / "backoffice.db"
INDEX_PATH = BASE_DIR / "static" / "index.html"
DEFAULT_PORT = 8000  # `python main.py` 로 직접 띄울 때만 쓴다
MANAGER_ROLE = "manager"
ACTIONS = ("confirm", "ship", "cancel", "refund")
# 동작 → (허용되는 현재 상태, 다음 상태)
TRANSITIONS = {
    "confirm": (("placed",), "confirmed"),
    "ship": (("confirmed",), "shipped"),
    "cancel": (("placed", "confirmed"), "cancelled"),
    "refund": (("shipped",), "refunded"),
}

SCHEMA = """
CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE bo_products (
    product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0));
CREATE TABLE bo_orders (
    order_id TEXT PRIMARY KEY, customer TEXT NOT NULL, status TEXT NOT NULL,
    ordered_at TEXT NOT NULL);
CREATE TABLE bo_order_lines (
    order_id TEXT NOT NULL REFERENCES bo_orders(order_id),
    product_id TEXT NOT NULL REFERENCES bo_products(product_id),
    qty INTEGER NOT NULL CHECK (qty >= 1));
CREATE INDEX idx_bo_order_lines_order ON bo_order_lines(order_id);
CREATE INDEX idx_bo_orders_ordered_at ON bo_orders(ordered_at);
"""

logger = logging.getLogger("backoffice")


class Rejection(Exception):
    """업무 규칙으로 요청을 거부한다. status 는 HTTP 코드, detail 은 사용자에게 보일 사유."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def connect() -> sqlite3.Connection:
    """DB 연결을 연다. 쓰는 쪽이 닫는다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def read_csv(name: str) -> list[dict[str, str]]:
    """seed 폴더의 CSV 하나를 읽는다."""
    with open(SEED_DIR / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_database() -> None:
    """기존 DB 를 지우고 seed CSV 로 새로 만든다."""
    DB_PATH.unlink(missing_ok=True)
    conn = connect()
    try:
        with conn:
            conn.executescript(SCHEMA)
            conn.executemany(
                "INSERT INTO bo_users VALUES (:user_id, :name, :role)", read_csv("users.csv"))
            products = [dict(r, stock=int(r["stock"])) for r in read_csv("products.csv")]
            conn.executemany(
                "INSERT INTO bo_products VALUES (:product_id, :name, :stock)", products)
            conn.executemany(
                "INSERT INTO bo_orders VALUES (:order_id, :customer, :status, :ordered_at)",
                read_csv("orders.csv"))
            lines = [dict(r, qty=int(r["qty"])) for r in read_csv("order_lines.csv")]
            conn.executemany(
                "INSERT INTO bo_order_lines VALUES (:order_id, :product_id, :qty)", lines)
    finally:
        conn.close()
    logger.info("DB_READY path=%s", DB_PATH.name)


def fetch_products(conn: sqlite3.Connection) -> list[dict]:
    """상품과 현재 재고 전체."""
    rows = conn.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")
    return [dict(r) for r in rows]


def fetch_orders(conn: sqlite3.Connection, order_id: Optional[str] = None) -> list[dict]:
    """주문(줄 포함)을 주문 시각 오래된 순으로. order_id 가 있으면 그 주문만."""
    where = "WHERE o.order_id = ?" if order_id else ""
    sql = (
        "SELECT o.order_id, o.customer, o.status, o.ordered_at, l.product_id, p.name, l.qty "
        "FROM bo_orders o LEFT JOIN bo_order_lines l ON l.order_id = o.order_id "
        "LEFT JOIN bo_products p ON p.product_id = l.product_id "
        f"{where} ORDER BY o.ordered_at, o.order_id, l.rowid")
    orders: dict[str, dict] = {}
    for r in conn.execute(sql, (order_id,) if order_id else ()):
        order = orders.setdefault(r["order_id"], {
            "order_id": r["order_id"], "customer": r["customer"], "status": r["status"],
            "ordered_at": r["ordered_at"], "lines": []})
        if r["product_id"]:
            order["lines"].append(
                {"product_id": r["product_id"], "name": r["name"], "qty": r["qty"]})
    return list(orders.values())


def change_stock(conn: sqlite3.Connection, order_id: str, sign: int) -> None:
    """주문 줄마다 수량 × sign 만큼 재고를 바꾼다. 줄이 모자라면 Rejection(409)."""
    lines = conn.execute(
        "SELECT p.product_id, p.name, p.stock, l.qty FROM bo_order_lines l "
        "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ?", (order_id,)
    ).fetchall()
    for line in lines:
        if line["stock"] + sign * line["qty"] < 0:
            raise Rejection(409, f"재고가 부족합니다: {line['name']}")
    conn.executemany(
        "UPDATE bo_products SET stock = stock + ? WHERE product_id = ?",
        [(sign * line["qty"], line["product_id"]) for line in lines])


def apply_action(conn: sqlite3.Connection, order_id: str, action: str, user_id: object) -> None:
    """검사 순서(400 → 404 → 403 → 409)대로 확인하고 주문 상태와 재고를 바꾼다."""
    if not isinstance(user_id, str):
        raise Rejection(400, "사용자를 확인하세요")
    order = conn.execute(
        "SELECT status FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
    user = conn.execute("SELECT role FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
    if order is None or user is None or action not in ACTIONS:
        raise Rejection(404, "찾을 수 없습니다")
    if action == "refund" and user["role"] != MANAGER_ROLE:
        raise Rejection(403, "관리자만 할 수 있습니다")
    allowed, next_status = TRANSITIONS[action]
    if order["status"] not in allowed:
        raise Rejection(409, "지금 상태에서는 할 수 없습니다")
    if action == "confirm":
        change_stock(conn, order_id, -1)
    elif action == "cancel" and order["status"] == "confirmed":
        change_stock(conn, order_id, +1)
    conn.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (next_status, order_id))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """서버가 시작할 때마다 DB 를 새로 만든다."""
    build_database()
    yield


# 가정: 핸들러가 모두 async 이고 안에서 await 를 하지 않으므로 DB 작업은 한 번에 하나씩
# 돈다. 그래서 동시 확정도 차례대로 처리되어 재고가 0 미만이 되지 않는다.
app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    """주문 · 재고 화면."""
    return FileResponse(INDEX_PATH)


@app.get("/api/users")
async def list_users() -> list[dict]:
    """사용자 목록."""
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT user_id, name, role FROM bo_users ORDER BY rowid")]
    finally:
        conn.close()


@app.get("/api/products")
async def list_products() -> list[dict]:
    """상품과 현재 재고."""
    conn = connect()
    try:
        return fetch_products(conn)
    finally:
        conn.close()


@app.get("/api/orders")
async def list_orders() -> list[dict]:
    """주문 전체(줄 포함), 주문 시각 오래된 순."""
    conn = connect()
    try:
        return fetch_orders(conn)
    finally:
        conn.close()


async def read_user(request: Request) -> object:
    """본문 JSON 에서 user 를 꺼낸다. 본문이 없거나 JSON 이 아니면 None."""
    try:
        body = json.loads(await request.body())
    except ValueError:  # 본문 없음 · 깨진 JSON 은 user 없음과 같게 다룬다(R7)
        return None
    return body.get("user") if isinstance(body, dict) else None


@app.post("/api/orders/{order_id}/{action}")
async def run_action(order_id: str, action: str, request: Request) -> JSONResponse:
    """주문에 확정 · 출고 · 취소 · 환불 중 하나를 적용하고 바뀐 주문과 재고를 돌려준다."""
    user_id = await read_user(request)
    conn = connect()
    try:
        try:
            with conn:  # 재고와 상태를 한 트랜잭션으로 묶는다
                apply_action(conn, order_id, action, user_id)
        except Rejection as rejection:
            logger.info("ACTION_REJECTED order=%s action=%s status=%d",
                        order_id, action, rejection.status)
            return JSONResponse({"detail": rejection.detail}, status_code=rejection.status)
        logger.info("ACTION_DONE order=%s action=%s", order_id, action)
        return JSONResponse({"order": fetch_orders(conn, order_id)[0],
                             "products": fetch_products(conn)})
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", DEFAULT_PORT)))
