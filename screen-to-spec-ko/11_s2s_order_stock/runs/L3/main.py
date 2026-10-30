"""가나다식품 주문 · 재고 백오피스: seed/*.csv 로 SQLite 를 새로 만들고 주문 동작 API 와 화면(/)을 낸다."""
import csv
import json
import logging
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE_DIR = Path(__file__).resolve().parent
SEED_DIR = BASE_DIR / "seed"
DB_PATH = BASE_DIR / "backoffice.db"
INDEX_PATH = BASE_DIR / "static" / "index.html"
BUSY_TIMEOUT_SECONDS = 10
ACTIONS = {"confirm", "ship", "cancel", "refund"}
# 동작 -> (할 수 있는 현재 상태들, 새 상태)
TRANSITIONS = {
    "confirm": ({"placed"}, "confirmed"),
    "ship": ({"confirmed"}, "shipped"),
    "cancel": ({"placed", "confirmed"}, "cancelled"),
    "refund": ({"shipped"}, "refunded"),
}
SCHEMA = """
CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0));
CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT NOT NULL, status TEXT NOT NULL,
    ordered_at TEXT NOT NULL);
CREATE TABLE bo_order_lines (order_id TEXT NOT NULL REFERENCES bo_orders(order_id),
    product_id TEXT NOT NULL REFERENCES bo_products(product_id), qty INTEGER NOT NULL);
CREATE INDEX idx_bo_order_lines_order ON bo_order_lines(order_id);
CREATE INDEX idx_bo_orders_ordered_at ON bo_orders(ordered_at);
"""
SEED_TABLES = [
    ("bo_users", "users.csv", ["user_id", "name", "role"]),
    ("bo_products", "products.csv", ["product_id", "name", "stock"]),
    ("bo_orders", "orders.csv", ["order_id", "customer", "status", "ordered_at"]),
    ("bo_order_lines", "order_lines.csv", ["order_id", "product_id", "qty"]),
]
INT_COLUMNS = {"stock", "qty"}
# 확정 · 취소가 재고를 동시에 건드리므로 쓰기는 한 번에 하나만 한다(단일 프로세스 가정).
WRITE_LOCK = threading.Lock()
logger = logging.getLogger("backoffice")


class Reject(Exception):
    """사용자에게 보여 줄 거부 사유와 상태 코드."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def connect() -> sqlite3.Connection:
    """행을 이름으로 읽는 새 커넥션을 연다. 트랜잭션은 직접 BEGIN 한다."""
    conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def read_seed(filename: str, columns: list[str]) -> list[tuple[Any, ...]]:
    """CSV 한 파일을 칸 순서대로 읽는다. 정수 칸은 int 로 바꾼다."""
    path = SEED_DIR / filename
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [tuple(int(r[c]) if c in INT_COLUMNS else r[c] for c in columns)
                for r in csv.DictReader(f)]


def build_database() -> None:
    """DB 파일을 지우고 스키마를 만든 뒤 seed 를 넣는다."""
    DB_PATH.unlink(missing_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN")
        for table, filename, columns in SEED_TABLES:
            marks = ",".join("?" * len(columns))
            conn.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({marks})",
                             read_seed(filename, columns))
        conn.execute("COMMIT")
    finally:
        conn.close()
    logger.info("DB_BUILT from seed")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """서버가 시작할 때마다 DB 를 새로 만든다."""
    build_database()
    yield


app = FastAPI(lifespan=lifespan)


def list_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """상품 전체와 현재 재고."""
    rows = conn.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")
    return [dict(r) for r in rows]


def list_orders(conn: sqlite3.Connection, order_id: str | None = None) -> list[dict[str, Any]]:
    """주문(줄 포함)을 주문 시각 오래된 순으로. order_id 를 주면 그 주문만."""
    where, args = ("WHERE order_id = ?", (order_id,)) if order_id else ("", ())
    orders = [dict(r) for r in conn.execute(
        f"SELECT order_id, customer, status, ordered_at FROM bo_orders {where} "
        "ORDER BY ordered_at, order_id", args)]
    lines = conn.execute(
        "SELECT l.order_id, l.product_id, p.name, l.qty FROM bo_order_lines l "
        "JOIN bo_products p ON p.product_id = l.product_id ORDER BY l.rowid")
    by_order: dict[str, list[dict[str, Any]]] = {o["order_id"]: [] for o in orders}
    for r in lines:
        if r["order_id"] in by_order:
            by_order[r["order_id"]].append(
                {"product_id": r["product_id"], "name": r["name"], "qty": r["qty"]})
    for o in orders:
        o["lines"] = by_order[o["order_id"]]
    return orders


def adjust_stock(conn: sqlite3.Connection, order_id: str, sign: int) -> None:
    """주문 줄마다 재고를 줄이거나(sign=-1) 되돌린다(sign=+1). 모자라면 Reject(409)."""
    lines = conn.execute("SELECT l.product_id, l.qty, p.name FROM bo_order_lines l "
                         "JOIN bo_products p ON p.product_id = l.product_id "
                         "WHERE l.order_id = ?", (order_id,)).fetchall()
    for line in lines:
        delta = sign * line["qty"]
        cur = conn.execute("UPDATE bo_products SET stock = stock + ? "
                           "WHERE product_id = ? AND stock + ? >= 0",
                           (delta, line["product_id"], delta))
        if cur.rowcount == 0:
            raise Reject(409, f"재고가 부족합니다: {line['name']}")


def apply_action(conn: sqlite3.Connection, order_id: str, action: str, user_id: str) -> None:
    """R8 순서(404 -> 403 -> 409)로 검사하고 상태와 재고를 한 트랜잭션으로 바꾼다."""
    order = conn.execute("SELECT status FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
    user = conn.execute("SELECT role FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
    if order is None or user is None or action not in ACTIONS:
        raise Reject(404, "찾을 수 없습니다")
    if action == "refund" and user["role"] != "manager":
        raise Reject(403, "관리자만 할 수 있습니다")
    allowed, new_status = TRANSITIONS[action]
    conn.execute("BEGIN IMMEDIATE")
    try:
        # 락을 잡은 뒤 상태를 다시 읽어, 같은 주문의 중복 요청이 재고를 두 번 바꾸지 못하게 한다.
        status = conn.execute("SELECT status FROM bo_orders WHERE order_id = ?",
                              (order_id,)).fetchone()["status"]
        if status not in allowed:
            raise Reject(409, "지금 상태에서는 할 수 없습니다")
        if action == "confirm":
            adjust_stock(conn, order_id, -1)
        elif action == "cancel" and status == "confirmed":
            adjust_stock(conn, order_id, +1)
        conn.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (new_status, order_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")  # 앞 줄까지 줄인 재고도 함께 취소한다
        raise


async def read_user(request: Request) -> str:
    """본문에서 user 문자열을 꺼낸다. 없으면 Reject(400)."""
    try:
        body = json.loads(await request.body())
    except ValueError:
        body = None
    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, str):
        raise Reject(400, "사용자를 확인하세요")
    return user


@app.exception_handler(Reject)
async def handle_reject(_request: Request, exc: Reject) -> JSONResponse:
    """거부는 모두 {"detail": 사유} 로 낸다."""
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def query_db(fetch: Callable[[sqlite3.Connection], Any]) -> Any:
    """읽기용 커넥션을 열어 fetch(conn) 결과를 돌려주고 닫는다."""
    conn = connect()
    try:
        return fetch(conn)
    finally:
        conn.close()


def fetch_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """사용자 전체."""
    return [dict(r) for r in conn.execute(
        "SELECT user_id, name, role FROM bo_users ORDER BY rowid")]


@app.get("/")
def index() -> FileResponse:
    """화면."""
    return FileResponse(INDEX_PATH, media_type="text/html; charset=utf-8")


@app.get("/api/users")
def get_users() -> list[dict[str, Any]]:
    """사용자 목록."""
    return query_db(fetch_users)


@app.get("/api/products")
def get_products() -> list[dict[str, Any]]:
    """상품과 재고."""
    return query_db(list_products)


@app.get("/api/orders")
def get_orders() -> list[dict[str, Any]]:
    """주문 목록(오래된 순)."""
    return query_db(list_orders)


@app.post("/api/orders/{order_id}/{action}")
async def post_action(order_id: str, action: str, request: Request) -> dict[str, Any]:
    """주문 동작. 바뀐 주문 하나와 재고 전체를 돌려준다."""
    user_id = await read_user(request)
    conn = connect()
    try:
        with WRITE_LOCK:
            apply_action(conn, order_id, action, user_id)
            return {"order": list_orders(conn, order_id)[0], "products": list_products(conn)}
    finally:
        conn.close()
