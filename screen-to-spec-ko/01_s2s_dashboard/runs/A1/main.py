import random
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
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
    """테이블 생성 + 비어 있으면 가상 데이터 투입."""
    with closing(connect()) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer TEXT NOT NULL,
                amount INTEGER NOT NULL,
                ordered_at TEXT NOT NULL
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
        if db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]:
            return

        rnd = random.Random(42)
        now = datetime.now()

        customers = ["한빛마트", "초록상회", "맛나유통", "행복식자재", "동네슈퍼", "바른푸드", "온누리마트"]
        orders = []
        for days_ago in range(0, 7):
            day = (now - timedelta(days=days_ago)).replace(hour=9, minute=0, second=0, microsecond=0)
            # 오늘은 하루가 덜 지났을 수 있으니 시각을 현재 이전으로 제한
            n = rnd.randint(14, 38) if days_ago else rnd.randint(18, 30)
            for _ in range(n):
                t = day + timedelta(minutes=rnd.randint(0, 9 * 60))
                if t > now:
                    t = now - timedelta(minutes=rnd.randint(0, 60))
                orders.append((rnd.choice(customers), rnd.randint(5, 120) * 1000, t.strftime("%Y-%m-%d %H:%M:%S")))
        db.executemany("INSERT INTO orders (customer, amount, ordered_at) VALUES (?,?,?)", orders)

        products = [
            ("김치 1kg", 120, 50), ("간장 1.8L", 18, 40), ("참기름 320ml", 9, 30),
            ("쌀 10kg", 75, 30), ("고추장 500g", 42, 25), ("된장 1kg", 6, 20),
            ("냉동만두 1.2kg", 88, 40), ("식용유 1.8L", 22, 35), ("두부 300g", 140, 60),
            ("라면 5입", 210, 100), ("김 20봉", 12, 25), ("미역 100g", 64, 20),
        ]
        db.executemany("INSERT INTO products (name, stock, safety_stock) VALUES (?,?,?)", products)

        titles = [
            "배송 지연 문의", "유통기한 확인 요청", "대량 구매 단가 문의", "제품 포장 파손 신고",
            "세금계산서 재발행 요청", "신제품 샘플 요청", "반품 절차 문의", "납품 일정 변경 문의",
            "원산지 표기 문의", "결제 오류 문의",
        ]
        inquiries = []
        for i, title in enumerate(titles):
            status = "미처리" if i % 3 != 2 else "처리완료"
            created = (now - timedelta(hours=rnd.randint(1, 120))).strftime("%Y-%m-%d %H:%M:%S")
            inquiries.append((title, status, created))
        db.executemany("INSERT INTO inquiries (title, status, created_at) VALUES (?,?,?)", inquiries)
        db.commit()


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/dashboard")
def dashboard():
    today = datetime.now().date()
    with closing(connect()) as db:
        today_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(ordered_at) = ?", (today.isoformat(),)
        ).fetchone()[0]
        low_stock = db.execute(
            "SELECT COUNT(*) FROM products WHERE stock < safety_stock"
        ).fetchone()[0]
        pending = db.execute(
            "SELECT COUNT(*) FROM inquiries WHERE status = '미처리'"
        ).fetchone()[0]

        start = today - timedelta(days=6)
        rows = db.execute(
            "SELECT date(ordered_at) AS d, COUNT(*) AS c FROM orders "
            "WHERE date(ordered_at) >= ? GROUP BY d",
            (start.isoformat(),),
        ).fetchall()
        counts = {r["d"]: r["c"] for r in rows}

    weekdays = "월화수목금토일"
    daily = []
    for i in range(7):
        d = start + timedelta(days=i)
        daily.append({
            "date": d.isoformat(),
            "label": f"{d.month}/{d.day}({weekdays[d.weekday()]})",
            "orders": counts.get(d.isoformat(), 0),
        })
    return {
        "today": today.isoformat(),
        "today_orders": today_orders,
        "low_stock_items": low_stock,
        "pending_inquiries": pending,
        "daily_orders": daily,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
