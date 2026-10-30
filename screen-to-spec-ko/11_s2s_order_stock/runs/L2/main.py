"""가나다식품 주문 · 재고 백오피스: seed CSV 로 SQLite 를 새로 만들고 주문 동작 API 와 화면을 낸다."""
import csv
import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE_DIR = Path(__file__).resolve().parent
SEED_DIR = BASE_DIR / "seed"
DB_PATH = BASE_DIR / "backoffice.db"
INDEX_PATH = BASE_DIR / "static" / "index.html"
# 쓰기 트랜잭션이 서로 기다리는 최대 시간(초). 동시 확정이 줄 서서 처리되게 한다.
DB_TIMEOUT_SEC = 30

# 동작 -> (지금 상태로 허용되는 것, 새 상태)
TRANSITIONS = {
    "confirm": ({"placed"}, "confirmed"),
    "ship": ({"confirmed"}, "shipped"),
    "cancel": ({"placed", "confirmed"}, "cancelled"),
    "refund": ({"shipped"}, "refunded"),
}
MANAGER_ONLY = {"refund"}

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


class Reject(Exception):
    """사용자에게 그대로 보여 줄 거부 사유를 가진 오류."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def connect() -> sqlite3.Connection:
    """트랜잭션을 직접 다루는 새 커넥션을 연다."""
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT_SEC, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def read_csv(name: str) -> list[dict[str, str]]:
    """seed 폴더의 CSV 하나를 읽는다."""
    with (SEED_DIR / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def rebuild_db() -> None:
    """DB 파일을 지우고 seed CSV 로 다시 만든다."""
    DB_PATH.unlink(missing_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN")
        conn.executemany("INSERT INTO bo_users VALUES (:user_id, :name, :role)",
                         read_csv("users.csv"))
        conn.executemany("INSERT INTO bo_products VALUES (:product_id, :name, :stock)",
                         read_csv("products.csv"))
        conn.executemany("INSERT INTO bo_orders VALUES (:order_id, :customer, :status, :ordered_at)",
                         read_csv("orders.csv"))
        conn.executemany("INSERT INTO bo_order_lines VALUES (:order_id, :product_id, :qty)",
                         read_csv("order_lines.csv"))
        conn.execute("COMMIT")
    finally:
        conn.close()
    logger.info("DB 재생성 완료: %s", DB_PATH.name)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """서버가 시작할 때마다 DB 를 새로 만든다."""
    rebuild_db()
    yield


app = FastAPI(lifespan=lifespan)


def fetch_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """상품 전체와 현재 재고."""
    rows = conn.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")
    return [dict(r) for r in rows]


def fetch_orders(conn: sqlite3.Connection, order_id: str | None = None) -> list[dict[str, Any]]:
    """주문(줄 포함)을 주문 시각 오래된 순으로 읽는다. order_id 가 있으면 그 주문만."""
    where = "WHERE o.order_id = ?" if order_id else ""
    params = (order_id,) if order_id else ()
    rows = conn.execute(
        "SELECT o.order_id, o.customer, o.status, o.ordered_at, l.product_id, p.name AS pname, l.qty"
        " FROM bo_orders o LEFT JOIN bo_order_lines l ON l.order_id = o.order_id"
        " LEFT JOIN bo_products p ON p.product_id = l.product_id "
        + where + " ORDER BY o.ordered_at, o.order_id, l.rowid", params)
    orders: dict[str, dict[str, Any]] = {}
    for r in rows:
        order = orders.setdefault(r["order_id"], {
            "order_id": r["order_id"], "customer": r["customer"], "status": r["status"],
            "ordered_at": r["ordered_at"], "lines": []})
        if r["product_id"] is not None:
            order["lines"].append({"product_id": r["product_id"], "name": r["pname"],
                                   "qty": r["qty"]})
    return list(orders.values())


def adjust_stock(conn: sqlite3.Connection, order_id: str, sign: int) -> None:
    """주문 줄마다 재고를 줄이거나(sign=-1) 되돌린다(sign=+1). 모자라면 Reject(409)."""
    lines = conn.execute(
        "SELECT l.product_id, l.qty, p.name FROM bo_order_lines l"
        " JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ?", (order_id,))
    for line in lines.fetchall():
        # 조건부 UPDATE 라서 재고가 0 미만이 되는 갱신은 일어나지 않는다.
        cur = conn.execute(
            "UPDATE bo_products SET stock = stock + ? WHERE product_id = ? AND stock + ? >= 0",
            (sign * line["qty"], line["product_id"], sign * line["qty"]))
        if cur.rowcount == 0:
            raise Reject(409, f"재고가 부족합니다: {line['name']}")


def apply_action(conn: sqlite3.Connection, order_id: str, action: str, user_id: str) -> None:
    """R6~R8 순서로 검사한 뒤 상태와 재고를 바꾼다. 호출하는 쪽이 트랜잭션을 연다."""
    order = conn.execute("SELECT status FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
    user = conn.execute("SELECT role FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
    if order is None or user is None or action not in TRANSITIONS:
        raise Reject(404, "찾을 수 없습니다")
    if action in MANAGER_ONLY and user["role"] != "manager":
        raise Reject(403, "관리자만 할 수 있습니다")
    allowed, new_status = TRANSITIONS[action]
    if order["status"] not in allowed:
        raise Reject(409, "지금 상태에서는 할 수 없습니다")
    if action == "confirm":
        adjust_stock(conn, order_id, -1)
    elif action == "cancel" and order["status"] == "confirmed":
        adjust_stock(conn, order_id, +1)
    conn.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (new_status, order_id))


async def read_user_id(request: Request) -> str:
    """본문에서 user 를 꺼낸다. 문자열이 아니면 Reject(400)."""
    try:
        body = json.loads(await request.body())
    except ValueError:
        body = None
    user_id = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user_id, str):
        raise Reject(400, "사용자를 확인하세요")
    return user_id


@app.exception_handler(Reject)
async def handle_reject(_request: Request, exc: Reject) -> JSONResponse:
    """거부 사유를 {"detail": ...} 로 돌려준다."""
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


@app.get("/")
def index() -> FileResponse:
    """화면 한 페이지."""
    return FileResponse(INDEX_PATH)


@app.get("/api/users")
def list_users() -> list[dict[str, Any]]:
    """사용자 목록."""
    conn = connect()
    try:
        rows = conn.execute("SELECT user_id, name, role FROM bo_users ORDER BY rowid")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/products")
def list_products() -> list[dict[str, Any]]:
    """상품과 현재 재고."""
    conn = connect()
    try:
        return fetch_products(conn)
    finally:
        conn.close()


@app.get("/api/orders")
def list_orders() -> list[dict[str, Any]]:
    """주문 전체(줄 포함), 주문 시각 오래된 순."""
    conn = connect()
    try:
        return fetch_orders(conn)
    finally:
        conn.close()


@app.post("/api/orders/{order_id}/{action}")
async def run_action(order_id: str, action: str, request: Request) -> dict[str, Any]:
    """주문에 동작(확정 · 출고 · 취소 · 환불)을 적용하고 바뀐 주문과 재고를 돌려준다."""
    user_id = await read_user_id(request)
    conn = connect()
    try:
        # 쓰기 잠금을 먼저 잡아야 같은 재고를 두 요청이 동시에 읽지 못한다(R5).
        conn.execute("BEGIN IMMEDIATE")
        try:
            apply_action(conn, order_id, action, user_id)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return {"order": fetch_orders(conn, order_id)[0], "products": fetch_products(conn)}
    finally:
        conn.close()


if __name__ == "__main__":
    import os

    import uvicorn

    # 환경 변수 PORT 가 없으면 PRD 의 기본 포트 8000 을 쓴다.
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
