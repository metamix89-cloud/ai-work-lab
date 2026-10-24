import secrets
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .db import connect, init_db

app = FastAPI(title="가나다식품 경영 현황 대시보드")
init_db()

STATIC = Path(__file__).resolve().parent.parent / "static"
SESSIONS: dict[str, dict] = {}  # token -> user (데모용 메모리 세션)
DEMO_PASSWORD = "demo1234"

# 역할별 열람 가능 항목. 서버에서 강제: 권한 없는 숫자는 응답에 아예 포함하지 않는다.
PERMISSIONS = {
    "ceo": {"orders", "revenue", "cancel_rate", "stock", "inquiries", "daily_revenue", "ranking"},
    "sales": {"orders", "revenue", "cancel_rate", "inquiries", "daily_revenue", "ranking"},
    "logistics": {"orders", "stock", "inquiries"},
}


class Login(BaseModel):
    username: str
    password: str


def current_user(authorization: str = Header(default="")):
    user = SESSIONS.get(authorization.removeprefix("Bearer ").strip())
    if not user:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


@app.post("/api/login")
def login(body: Login):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not row or not secrets.compare_digest(body.password.encode(), DEMO_PASSWORD.encode()):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = {"username": row["username"], "name": row["display_name"], "role": row["role"]}
    return {"token": token, **SESSIONS[token]}


@app.get("/api/dashboard")
def dashboard(start: str, end: str, user: dict = Depends(current_user)):
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "날짜 형식은 YYYY-MM-DD 입니다.")
    if s > e:
        raise HTTPException(400, "시작일이 종료일보다 늦습니다.")
    if (e - s).days > 366:
        raise HTTPException(400, "조회 기간은 최대 1년입니다.")
    perm = PERMISSIONS[user["role"]]
    out: dict = {"role": user["role"], "start": start, "end": end}
    rng = (start, end)
    with connect() as conn:
        def q(sql, *args):
            return conn.execute(sql, args).fetchall()

        total, cancelled, revenue = q(
            "SELECT COUNT(*), SUM(status='취소'), COALESCE(SUM(CASE WHEN status!='취소' THEN amount END),0) "
            "FROM orders WHERE order_date BETWEEN ? AND ?", *rng)[0]
        cancelled = cancelled or 0
        kpi = {}
        if "orders" in perm:
            kpi["orders"] = total
        if "revenue" in perm:
            kpi["revenue"] = revenue
        if "cancel_rate" in perm:
            kpi["cancel_rate"] = round(cancelled / total * 100, 1) if total else 0
        if "stock" in perm:
            low = q("SELECT name, stock, safety_stock FROM products WHERE stock < safety_stock "
                    "ORDER BY CAST(stock AS REAL)/safety_stock")
            kpi["stock_warnings"] = len(low)
            out["stock_items"] = [dict(r) for r in low]
        if "inquiries" in perm:
            pend = q("SELECT i.created_at, i.subject, c.name client FROM inquiries i "
                     "JOIN clients c ON c.id=i.client_id "
                     "WHERE i.status='미처리' AND date(i.created_at) BETWEEN ? AND ? "
                     "ORDER BY i.created_at DESC", *rng)
            kpi["pending_inquiries"] = len(pend)
            out["inquiry_items"] = [dict(r) for r in pend[:8]]
        out["kpi"] = kpi

        rows = {r["order_date"]: r for r in q(
            "SELECT order_date, COUNT(*) n, COALESCE(SUM(CASE WHEN status!='취소' THEN amount END),0) rev "
            "FROM orders WHERE order_date BETWEEN ? AND ? GROUP BY order_date", *rng)}
        daily, d = [], s
        while d <= e:
            r = rows.get(d.isoformat())
            item = {"date": d.isoformat(), "orders": r["n"] if r else 0}
            if "daily_revenue" in perm:
                item["revenue"] = r["rev"] if r else 0
            daily.append(item)
            d += timedelta(days=1)
        out["daily"] = daily

        if "ranking" in perm:
            out["ranking"] = [dict(r) for r in q(
                "SELECT c.name, COUNT(*) orders, SUM(o.amount) revenue FROM orders o "
                "JOIN clients c ON c.id=o.client_id "
                "WHERE o.status!='취소' AND o.order_date BETWEEN ? AND ? "
                "GROUP BY c.id ORDER BY revenue DESC LIMIT 10", *rng)]
    return out


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
