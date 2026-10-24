import random, secrets, sqlite3
from datetime import date, timedelta
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).parent
DB = BASE / "ganada.db"
app = FastAPI(title="가나다식품 경영 현황 대시보드")

# 데모 계정: 아이디 -> (비밀번호, 역할)
USERS = {
    "ceo": ("ceo1234", "대표"),
    "sales": ("sales1234", "영업팀"),
    "logistics": ("logi1234", "물류팀"),
}
# 역할별 열람 가능 지표 (서버에서 강제: 권한 없는 값은 응답에 아예 포함하지 않음)
ROLE_METRICS = {
    "대표": {"orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries", "daily", "ranking", "stock_list"},
    "영업팀": {"orders", "revenue", "cancel_rate", "open_inquiries", "daily", "ranking"},
    "물류팀": {"orders", "cancel_rate", "stock_alerts", "daily", "stock_list"},
}
SESSIONS: dict[str, str] = {}


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def seed():
    if DB.exists():
        return
    rnd = random.Random(42)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE partners(id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, stock INTEGER, safety_stock INTEGER);
    CREATE TABLE orders(id INTEGER PRIMARY KEY, partner_id INTEGER, order_date TEXT, status TEXT, amount INTEGER);
    CREATE TABLE inquiries(id INTEGER PRIMARY KEY, partner_id INTEGER, created TEXT, title TEXT, status TEXT);
    CREATE INDEX ix_o ON orders(order_date);
    CREATE INDEX ix_i ON inquiries(created);
    """)
    partners = ["한마음마트", "싱싱유통", "대한푸드서비스", "누리식자재", "초록상회", "행복급식", "바다프레시", "으뜸할인점"]
    c.executemany("INSERT INTO partners(name) VALUES(?)", [(p,) for p in partners])
    prods = [("국산 쌀 10kg", 120, 50), ("참기름 500ml", 35, 40), ("김치 5kg", 18, 30), ("냉동만두 1kg", 210, 80),
             ("고추장 3kg", 64, 40), ("김 20봉", 22, 25), ("라면 40입", 300, 100), ("식용유 18L", 9, 15),
             ("두부 20모", 75, 30), ("된장 3kg", 55, 30)]
    c.executemany("INSERT INTO products(name,stock,safety_stock) VALUES(?,?,?)", prods)
    today = date.today()
    for d in range(120):
        day = today - timedelta(days=d)
        n = rnd.randint(8, 22) + (6 if day.weekday() < 5 else -5)
        for _ in range(max(n, 2)):
            st = rnd.choices(["완료", "처리중", "취소"], [80, 8, 12])[0]
            if d > 5 and st == "처리중":
                st = "완료"
            pid = rnd.choices(range(1, 9), [10, 8, 12, 6, 5, 9, 7, 4])[0]
            c.execute("INSERT INTO orders(partner_id,order_date,status,amount) VALUES(?,?,?,?)",
                      (pid, day.isoformat(), st, rnd.randint(30, 400) * 10000))
        for _ in range(rnd.randint(0, 3)):
            t = rnd.choice(["납품 지연 문의", "단가 조정 요청", "반품 접수 문의", "세금계산서 재발행", "신제품 샘플 요청", "배송지 변경"])
            s = "처리완료" if d > 7 and rnd.random() < .9 else rnd.choice(["미처리", "처리완료"])
            c.execute("INSERT INTO inquiries(partner_id,created,title,status) VALUES(?,?,?,?)",
                      (rnd.randint(1, 8), day.isoformat(), t, s))
    c.commit()
    c.close()


seed()


class Login(BaseModel):
    username: str
    password: str


def me(authorization: str = Header(default="")):
    role = SESSIONS.get(authorization.removeprefix("Bearer ").strip())
    if not role:
        raise HTTPException(401, "로그인이 필요합니다")
    return role


@app.post("/api/login")
def login(b: Login):
    u = USERS.get(b.username)
    if not u or not secrets.compare_digest(u[0], b.password):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    tok = secrets.token_urlsafe(24)
    SESSIONS[tok] = u[1]
    return {"token": tok, "role": u[1]}


@app.get("/api/dashboard")
def dashboard(start: date = Query(...), end: date = Query(...), role: str = Depends(me)):
    if start > end:
        raise HTTPException(400, "시작일이 종료일보다 늦습니다")
    if (end - start).days > 366:
        raise HTTPException(400, "기간은 최대 1년까지 선택할 수 있습니다")
    allowed = ROLE_METRICS[role]
    s, e = start.isoformat(), end.isoformat()
    c = conn()
    out: dict = {"role": role, "allowed": sorted(allowed), "start": s, "end": e}
    r = c.execute("""SELECT COUNT(*) n, COALESCE(SUM(status='취소'),0) x,
                     COALESCE(SUM(CASE WHEN status!='취소' THEN amount END),0) rev
                     FROM orders WHERE order_date BETWEEN ? AND ?""", (s, e)).fetchone()
    if "orders" in allowed:
        out["orders"] = r["n"]
    if "revenue" in allowed:
        out["revenue"] = r["rev"]
    if "cancel_rate" in allowed:
        out["cancel_rate"] = round(r["x"] / r["n"] * 100, 1) if r["n"] else 0
        out["cancel_count"] = r["x"]
    if "stock_alerts" in allowed:
        out["stock_alerts"] = c.execute("SELECT COUNT(*) FROM products WHERE stock<safety_stock").fetchone()[0]
    if "stock_list" in allowed:
        out["stock_list"] = [dict(x) for x in c.execute(
            "SELECT name,stock,safety_stock FROM products WHERE stock<safety_stock ORDER BY stock*1.0/safety_stock")]
    if "open_inquiries" in allowed:
        out["open_inquiries"] = c.execute(
            "SELECT COUNT(*) FROM inquiries WHERE status='미처리' AND created BETWEEN ? AND ?", (s, e)).fetchone()[0]
    if "daily" in allowed:
        rows = {x["d"]: x["n"] for x in c.execute(
            "SELECT order_date d, COUNT(*) n FROM orders WHERE order_date BETWEEN ? AND ? GROUP BY d", (s, e))}
        days, d = [], start
        while d <= end:
            days.append({"date": d.isoformat(), "orders": rows.get(d.isoformat(), 0)})
            d += timedelta(days=1)
        out["daily"] = days
    if "ranking" in allowed:
        out["ranking"] = [dict(x) for x in c.execute("""
            SELECT p.name, SUM(o.amount) revenue, COUNT(*) orders FROM orders o JOIN partners p ON p.id=o.partner_id
            WHERE o.status!='취소' AND o.order_date BETWEEN ? AND ? GROUP BY p.id ORDER BY revenue DESC""", (s, e))]
    c.close()
    return out


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
