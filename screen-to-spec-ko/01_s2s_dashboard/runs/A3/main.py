import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "ganada.db"

app = FastAPI(title="가나다식품 오늘의 현황판")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            amount INTEGER NOT NULL,
            ordered_at TEXT NOT NULL  -- YYYY-MM-DD HH:MM:SS
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            stock INTEGER NOT NULL,
            safety_stock INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('미처리', '처리완료')),
            created_at TEXT NOT NULL
        );
        """
    )
    if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
        seed(conn)
    conn.commit()
    conn.close()


def seed(conn):
    rnd = random.Random(42)
    now = datetime.now()

    customers = ["한우리마트", "푸른식당", "해든카페", "동네슈퍼", "별빛호텔", "미소급식", "온누리유통"]
    # 최근 7일(오늘 포함) 주문, 일자별 건수를 다르게
    for days_ago in range(6, -1, -1):
        day = now - timedelta(days=days_ago)
        count = rnd.randint(8, 24) if days_ago else rnd.randint(12, 20)
        for _ in range(count):
            t = day.replace(hour=rnd.randint(8, 17), minute=rnd.randint(0, 59), second=0, microsecond=0)
            if days_ago == 0 and t > now:
                t = now.replace(microsecond=0)
            conn.execute(
                "INSERT INTO orders (customer, amount, ordered_at) VALUES (?, ?, ?)",
                (rnd.choice(customers), rnd.randint(5, 120) * 1000, t.strftime("%Y-%m-%d %H:%M:%S")),
            )

    products = [
        ("국산 참기름 500ml", 120, 50), ("유기농 쌀 10kg", 18, 40), ("멸치액젓 1L", 65, 30),
        ("100% 현미식초", 9, 25), ("냉동 만두 1kg", 210, 100), ("김치찌개 양념", 14, 30),
        ("들기름 350ml", 80, 40), ("전통 된장 2kg", 33, 30), ("고춧가루 1kg", 22, 35),
        ("해물 육수팩", 150, 60),
    ]
    conn.executemany("INSERT INTO products (name, stock, safety_stock) VALUES (?, ?, ?)", products)

    inquiries = [
        ("배송 지연 문의", "미처리"), ("세금계산서 재발행 요청", "미처리"),
        ("참기름 유통기한 문의", "처리완료"), ("대량 주문 견적 요청", "미처리"),
        ("반품 접수 문의", "처리완료"), ("신제품 샘플 요청", "미처리"),
        ("결제 오류 문의", "처리완료"), ("포장 파손 클레임", "미처리"),
    ]
    for i, (title, status) in enumerate(inquiries):
        created = (now - timedelta(hours=i * 7)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO inquiries (title, status, created_at) VALUES (?, ?, ?)", (title, status, created))


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/dashboard")
def dashboard():
    today = date.today()
    start = today - timedelta(days=6)
    conn = connect()
    try:
        orders_today = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE date(ordered_at) = ?", (today.isoformat(),)
        ).fetchone()[0]
        low_stock = conn.execute("SELECT COUNT(*) FROM products WHERE stock < safety_stock").fetchone()[0]
        open_inquiries = conn.execute("SELECT COUNT(*) FROM inquiries WHERE status = '미처리'").fetchone()[0]
        rows = conn.execute(
            "SELECT date(ordered_at) AS d, COUNT(*) AS c FROM orders WHERE date(ordered_at) BETWEEN ? AND ? GROUP BY d",
            (start.isoformat(), today.isoformat()),
        ).fetchall()
    finally:
        conn.close()

    counts = {r["d"]: r["c"] for r in rows}
    daily = []
    for i in range(7):
        d = start + timedelta(days=i)
        daily.append({"date": d.isoformat(), "count": counts.get(d.isoformat(), 0)})

    return {
        "today": today.isoformat(),
        "orders_today": orders_today,
        "low_stock_items": low_stock,
        "open_inquiries": open_inquiries,
        "daily_orders": daily,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
