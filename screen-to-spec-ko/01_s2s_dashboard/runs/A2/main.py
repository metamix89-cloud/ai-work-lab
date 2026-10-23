import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "ganada.db"

app = FastAPI(title="가나다식품 오늘의 현황판")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ordered_at TEXT NOT NULL,      -- YYYY-MM-DD HH:MM:SS
            customer TEXT NOT NULL,
            amount INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            stock INTEGER NOT NULL,
            safety_stock INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('미처리', '처리중', '완료'))
        );
        """
    )
    if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
        seed(conn)
    conn.commit()
    conn.close()


def seed(conn):
    rnd = random.Random(42)
    customers = ["한울마트", "초록상회", "행복식자재", "미소푸드", "새벽유통", "대한식당", "바른먹거리"]
    now = datetime.now()
    # 최근 7일(오늘 포함) 주문, 오늘은 시간대를 현재 이전으로 제한
    for days_ago in range(6, -1, -1):
        d = date.today() - timedelta(days=days_ago)
        for _ in range(rnd.randint(14, 38)):
            t = datetime(d.year, d.month, d.day, rnd.randint(8, 20), rnd.randint(0, 59), rnd.randint(0, 59))
            if t > now:
                t = now - timedelta(minutes=rnd.randint(0, 120))
                if t.date() != d:
                    continue
            conn.execute(
                "INSERT INTO orders (ordered_at, customer, amount) VALUES (?,?,?)",
                (t.strftime("%Y-%m-%d %H:%M:%S"), rnd.choice(customers), rnd.randint(5, 300) * 1000),
            )

    products = [
        ("국산 참기름 500ml", 12, 30), ("전통 고추장 1kg", 85, 40), ("김치만두 1.4kg", 8, 25),
        ("햇반형 쌀밥 210g", 240, 100), ("한우사골곰탕 500g", 18, 20), ("순두부 350g", 150, 60),
        ("들기름 350ml", 5, 15), ("멸치액젓 1L", 64, 30), ("국산 볶음김치 500g", 22, 20),
        ("수제 어묵 모둠 1kg", 3, 20), ("된장 1kg", 97, 40), ("냉동 떡국떡 1kg", 41, 30),
    ]
    conn.executemany("INSERT INTO products (name, stock, safety_stock) VALUES (?,?,?)", products)

    titles = [
        "배송이 아직 도착하지 않았어요", "유통기한 문의드립니다", "대량 구매 단가 문의",
        "포장 파손 교환 요청", "세금계산서 발행 요청", "신제품 샘플 신청", "알레르기 성분 문의",
        "정기 배송 변경 요청", "결제 오류 문의", "원산지 확인 요청",
    ]
    statuses = ["미처리"] * 5 + ["처리중"] * 2 + ["완료"] * 3
    for title, status in zip(titles, statuses):
        t = now - timedelta(hours=rnd.randint(1, 120))
        conn.execute(
            "INSERT INTO inquiries (created_at, title, status) VALUES (?,?,?)",
            (t.strftime("%Y-%m-%d %H:%M:%S"), title, status),
        )


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/dashboard")
def dashboard():
    today = date.today()
    conn = get_conn()
    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE date(ordered_at) = ?", (today.isoformat(),)
    ).fetchone()[0]
    low_stock = conn.execute("SELECT COUNT(*) FROM products WHERE stock < safety_stock").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM inquiries WHERE status = '미처리'").fetchone()[0]

    start = (today - timedelta(days=6)).isoformat()
    rows = conn.execute(
        "SELECT date(ordered_at) AS d, COUNT(*) AS c FROM orders WHERE date(ordered_at) >= ? GROUP BY d",
        (start,),
    ).fetchall()
    conn.close()
    counts = {r["d"]: r["c"] for r in rows}
    weekdays = "월화수목금토일"
    daily = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        daily.append({
            "date": d.isoformat(),
            "label": f"{d.month}/{d.day}({weekdays[d.weekday()]})",
            "count": counts.get(d.isoformat(), 0),
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
    return FileResponse(BASE / "index.html")
