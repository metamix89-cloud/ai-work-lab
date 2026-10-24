# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수만 모았다. T1 · T2 만 통과해야 채점기가 맞다.
실수: 매출에 접수까지 · 기간을 직접 주면 종료일을 문자열로 비교(그날 주문 빠짐) · 분모 0 이면 취소율 0 ·
      미처리 문의는 기간과 상관없이 · 역할별 숨김은 화면에서만(API 는 다 줌) · 31일 검사 없음 · 같은 매출은 들어온 순 · 화면 없음."""
import csv
import os
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
app = FastAPI()
ROWS = {}
for _name in ("users", "orders", "stock", "inquiries"):
    with open(os.path.join(SEED, _name + ".csv"), encoding="utf-8") as _f:
        ROWS[_name] = list(csv.DictReader(_f))


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>경영 현황</h1></body></html>"


@app.get("/api/users")
def users():
    return ROWS["users"]


@app.get("/api/dashboard")
def dashboard(viewer: str | None = None, frm: str | None = Query(default=None, alias="from"), to: str | None = None):
    if not viewer:
        raise HTTPException(400, "사용자를 확인하세요")
    if not any(u["user_id"] == viewer for u in ROWS["users"]):
        raise HTTPException(404, "사용자가 없습니다")
    if frm is None and to is None:
        t = date.today()
        f = t - timedelta(days=6)
        inside = lambda s: f.isoformat() <= s[:10] <= t.isoformat()
    else:
        try:
            f, t = date.fromisoformat(frm), date.fromisoformat(to)
        except (TypeError, ValueError):
            raise HTTPException(400, "기간을 확인하세요")
        if f > t:
            raise HTTPException(400, "기간을 확인하세요")                  # 실수: 31일 검사 없음
        inside = lambda s: f.isoformat() <= s <= t.isoformat()          # 실수: '2026-10-23 23:50' <= '2026-10-23' 은 거짓
    orders = [o for o in ROWS["orders"] if inside(o["ordered_at"])]
    live = [o for o in orders if o["status"] != "취소"]
    cancel = sum(1 for o in orders if o["status"] == "취소")
    by = {}
    for o in live:                                                     # 실수: 매출에 접수까지
        by[o["customer"]] = by.get(o["customer"], 0) + int(o["amount"])
    days = [(f + timedelta(days=k)).isoformat() for k in range((t - f).days + 1)]
    return {"period": {"from": f.isoformat(), "to": t.isoformat()},
            "metrics": {"orders": len(live), "revenue": sum(int(o["amount"]) for o in live),
                        "cancel_rate": round(cancel * 100 / len(orders), 1) if orders else 0,   # 실수: 분모 0 이면 0
                        "stock_alerts": sum(1 for s in ROWS["stock"] if int(s["qty"]) < int(s["safety_qty"])),
                        "open_inquiries": sum(1 for i in ROWS["inquiries"] if i["status"] != "완료")},   # 실수: 기간 무관
            "daily": [{"date": d, "count": sum(1 for o in live if o["ordered_at"][:10] == d)} for d in days],
            "top_customers": [{"customer": k, "revenue": v} for k, v in sorted(by.items(), key=lambda kv: -kv[1])[:5]],   # 실수: 동률은 들어온 순
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}           # 실수: 역할과 상관없이 다 준다
