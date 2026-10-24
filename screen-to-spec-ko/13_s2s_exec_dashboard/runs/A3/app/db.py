import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "ganada.db"

CLIENTS = ["한울마트", "초록유통", "새벽식자재", "미소푸드서비스", "바른급식", "행복할인점",
           "대성식품몰", "온누리상회", "푸른바다수산", "해든외식", "청솔마트", "다온푸드"]
# (이름, 단가, 현재고, 안전재고)
PRODUCTS = [("가나다 쌀과자", 3200, 400, 150), ("김치 만두 1kg", 8900, 120, 150),
            ("국산 참기름 320ml", 12500, 35, 60), ("들기름 180ml", 11000, 20, 40),
            ("냉동 볶음밥 450g", 4800, 260, 120), ("순두부찌개 양념", 2900, 500, 200),
            ("한우 사골곰탕 500g", 6900, 18, 80), ("두부 300g", 1800, 90, 150),
            ("고추장 1kg", 7800, 140, 70), ("된장 1kg", 7200, 55, 70),
            ("김자반 50g", 2400, 310, 100), ("유기농 현미 4kg", 21000, 12, 30),
            ("꿀 500g", 15800, 64, 40), ("라면 5입", 3900, 700, 300), ("비빔냉면 2인", 5200, 25, 90)]
ACCOUNTS = [("ceo", "대표 김대표", "ceo"), ("sales", "영업팀 이영업", "sales"),
            ("logistics", "물류팀 박물류", "logistics")]
SUBJECTS = ["납기 지연 문의", "단가 견적 요청", "제품 파손 접수", "유통기한 문의", "세금계산서 재발행", "신제품 샘플 요청"]


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if DB_PATH.exists():
        return
    rnd = random.Random(2026)
    conn = connect()
    conn.executescript("""
    CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, price INTEGER, stock INTEGER, safety_stock INTEGER);
    CREATE TABLE orders(id INTEGER PRIMARY KEY, client_id INTEGER, order_date TEXT, amount INTEGER, status TEXT);
    CREATE TABLE inquiries(id INTEGER PRIMARY KEY, client_id INTEGER, created_at TEXT, subject TEXT, status TEXT);
    CREATE TABLE users(username TEXT PRIMARY KEY, display_name TEXT, role TEXT);
    CREATE INDEX ix_orders_date ON orders(order_date);
    """)
    conn.executemany("INSERT INTO clients(name) VALUES(?)", [(c,) for c in CLIENTS])
    conn.executemany("INSERT INTO products(name,price,stock,safety_stock) VALUES(?,?,?,?)", PRODUCTS)
    conn.executemany("INSERT INTO users VALUES(?,?,?)", ACCOUNTS)
    today = date.today()
    weights = [rnd.uniform(0.4, 2.0) for _ in CLIENTS]
    for back in range(120):
        d = today - timedelta(days=back)
        n = 0 if d.weekday() == 6 else rnd.randint(6, 18) + (4 if d.weekday() == 0 else 0)
        for _ in range(n):
            cid = rnd.choices(range(1, len(CLIENTS) + 1), weights)[0]
            amount = rnd.randint(30, 600) * 1000
            status = rnd.choices(["완료", "취소", "진행"], [80, 9, 11 if back < 5 else 0.01])[0]
            conn.execute("INSERT INTO orders(client_id,order_date,amount,status) VALUES(?,?,?,?)",
                         (cid, d.isoformat(), amount, status))
        for _ in range(rnd.randint(0, 3)):
            ts = datetime.combine(d, datetime.min.time()) + timedelta(hours=rnd.randint(9, 18))
            done = rnd.random() < (0.9 if back > 10 else 0.3)
            conn.execute("INSERT INTO inquiries(client_id,created_at,subject,status) VALUES(?,?,?,?)",
                         (rnd.randint(1, len(CLIENTS)), ts.isoformat(sep=" "), rnd.choice(SUBJECTS),
                          "처리완료" if done else "미처리"))
    conn.commit()
    conn.close()
