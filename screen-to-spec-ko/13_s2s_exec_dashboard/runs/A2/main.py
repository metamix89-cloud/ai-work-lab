"""가나다식품 경영 현황 대시보드 - FastAPI + SQLite. 실행: python main.py"""
import hashlib, hmac, os, random, secrets, sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB = BASE / "ganada.db"

# 역할별 열람 가능 항목 (서버에서 강제)
ROLES = {
    "ceo":       {"label": "대표",   "kpi": {"orders", "sales", "cancel_rate", "stock_alerts", "open_inquiries"}, "ranking": True,  "daily": "both"},
    "sales":     {"label": "영업팀", "kpi": {"orders", "sales", "cancel_rate", "open_inquiries"},                 "ranking": True,  "daily": "both"},
    "logistics": {"label": "물류팀", "kpi": {"orders", "cancel_rate", "stock_alerts"},                           "ranking": False, "daily": "orders"},
}
USERS = {"ceo": "ceo1234", "sales": "sales1234", "logistics": "logi1234"}  # 데모 계정


def hash_pw(pw: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000).hex()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def seed():
    if DB.exists():
        return
    rnd = random.Random(83)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE users(username TEXT PRIMARY KEY, role TEXT, salt BLOB, pw TEXT);
    CREATE TABLE clients(id INTEGER PRIMARY KEY, name TEXT, weight REAL);
    CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, stock INTEGER, safety_stock INTEGER);
    CREATE TABLE orders(id INTEGER PRIMARY KEY, client_id INTEGER, order_date TEXT, status TEXT, amount INTEGER);
    CREATE TABLE inquiries(id INTEGER PRIMARY KEY, client_id INTEGER, created_at TEXT, title TEXT, status TEXT);
    CREATE INDEX ix_orders_date ON orders(order_date);
    """)
    for u, pw in USERS.items():
        salt = os.urandom(16)
        c.execute("INSERT INTO users VALUES(?,?,?,?)", (u, u, salt, hash_pw(pw, salt)))
    clients = [("한울마트", 5), ("푸른유통", 4), ("대한프레시", 3.5), ("행복식자재", 3), ("별빛푸드", 2.5),
               ("미래급식", 2), ("온누리상회", 1.5), ("다온F&B", 1.2)]
    c.executemany("INSERT INTO clients(name,weight) VALUES(?,?)", clients)
    prods = [("가나다 김치 1kg", 320, 200), ("가나다 된장 500g", 140, 150), ("가나다 고추장 1kg", 95, 120),
             ("가나다 참기름 320ml", 410, 150), ("가나다 즉석밥 12입", 60, 300), ("가나다 만두 1.2kg", 520, 250),
             ("가나다 어묵 500g", 210, 100), ("가나다 라면 20입", 80, 200)]
    c.executemany("INSERT INTO products(name,stock,safety_stock) VALUES(?,?,?)", prods)
    today = date(2026, 10, 24)
    w = [x[1] for x in clients]
    for i in range(120):
        d = today - timedelta(days=119 - i)
        n = rnd.randint(2, 6) if d.weekday() >= 5 else rnd.randint(8, 18)
        for _ in range(n):
            cid = rnd.choices(range(1, 9), weights=w)[0]
            st = rnd.choices(["완료", "진행", "취소"], weights=[80, 10, 10])[0] if i < 115 else rnd.choices(["진행", "완료", "취소"], weights=[70, 20, 10])[0]
            c.execute("INSERT INTO orders(client_id,order_date,status,amount) VALUES(?,?,?,?)",
                      (cid, d.isoformat(), st, rnd.randint(30, 400) * 10000 // 10))
    titles = ["납기 일정 문의", "단가 조정 요청", "포장 파손 클레임", "신제품 샘플 요청", "세금계산서 재발행", "유통기한 확인 문의"]
    for i in range(60):
        d = today - timedelta(days=rnd.randint(0, 59))
        old = (today - d).days > 20
        st = "처리완료" if rnd.random() < (0.9 if old else 0.55) else "미처리"
        c.execute("INSERT INTO inquiries(client_id,created_at,title,status) VALUES(?,?,?,?)",
                  (rnd.randint(1, 8), d.isoformat(), rnd.choice(titles), st))
    c.commit()
    c.close()


seed()
app = FastAPI(title="가나다식품 경영 현황 대시보드")
SESSIONS: dict[str, str] = {}


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Login):
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not u or not hmac.compare_digest(u["pw"], hash_pw(body.password, u["salt"])):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    tok = secrets.token_urlsafe(24)
    SESSIONS[tok] = u["role"]
    return {"token": tok, "role": u["role"], "label": ROLES[u["role"]]["label"]}


def current_role(authorization: str = Header(default="")) -> str:
    role = SESSIONS.get(authorization.removeprefix("Bearer ").strip())
    if not role:
        raise HTTPException(401, "로그인이 필요합니다.")
    return role


@app.get("/api/summary")
def summary(start: str, end: str, role: str = Depends(current_role)):
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "날짜 형식이 올바르지 않습니다.")
    if s > e:
        raise HTTPException(400, "시작일이 종료일보다 늦습니다.")
    if (e - s).days > 366:
        raise HTTPException(400, "조회 기간은 최대 1년입니다.")
    cfg = ROLES[role]
    k = cfg["kpi"]
    out = {"role": role, "label": cfg["label"], "kpi": {}, "daily": [], "ranking": None, "stock_items": None, "open_inquiry_items": None}
    with conn() as c:
        r = c.execute("""SELECT COUNT(*) n, SUM(status='취소') canc,
                         COALESCE(SUM(CASE WHEN status!='취소' THEN amount END),0) sales
                         FROM orders WHERE order_date BETWEEN ? AND ?""", (start, end)).fetchone()
        n, canc = r["n"], r["canc"] or 0
        if "orders" in k: out["kpi"]["orders"] = n
        if "sales" in k: out["kpi"]["sales"] = r["sales"]
        if "cancel_rate" in k: out["kpi"]["cancel_rate"] = round(canc / n * 100, 1) if n else 0
        if "stock_alerts" in k:
            items = [dict(x) for x in c.execute(
                "SELECT name, stock, safety_stock FROM products WHERE stock < safety_stock ORDER BY stock*1.0/safety_stock")]
            out["kpi"]["stock_alerts"] = len(items)
            out["stock_items"] = items
        if "open_inquiries" in k:
            items = [dict(x) for x in c.execute(
                """SELECT i.created_at, c.name client, i.title FROM inquiries i JOIN clients c ON c.id=i.client_id
                   WHERE i.status='미처리' AND i.created_at BETWEEN ? AND ? ORDER BY i.created_at""", (start, end))]
            out["kpi"]["open_inquiries"] = len(items)
            out["open_inquiry_items"] = items[:8]
        rows = {x["d"]: x for x in c.execute(
            """SELECT order_date d, COUNT(*) orders,
               COALESCE(SUM(CASE WHEN status!='취소' THEN amount END),0) sales
               FROM orders WHERE order_date BETWEEN ? AND ? GROUP BY order_date""", (start, end))}
        d = s
        while d <= e:
            x = rows.get(d.isoformat())
            row = {"date": d.isoformat(), "orders": x["orders"] if x else 0}
            if cfg["daily"] == "both": row["sales"] = x["sales"] if x else 0
            out["daily"].append(row)
            d += timedelta(days=1)
        if cfg["ranking"]:
            out["ranking"] = [dict(x) for x in c.execute(
                """SELECT c.name, SUM(o.amount) sales, COUNT(*) orders FROM orders o JOIN clients c ON c.id=o.client_id
                   WHERE o.status!='취소' AND o.order_date BETWEEN ? AND ? GROUP BY c.id ORDER BY sales DESC""", (start, end))]
    return out


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    seed()
    uvicorn.run(app, host="127.0.0.1", port=8000)
