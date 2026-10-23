"""PRD 10장 완료 기준 T1~T9 (API/HTML 수준). 실행: python -m pytest tests  (pytest, httpx 필요)"""
import importlib
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def write(d, name, header, rows):
    (d / name).write_text("\n".join([header] + rows) + "\n", encoding="utf-8")


def load_app(tmp_path, monkeypatch, orders, stock, inquiries):
    monkeypatch.setenv("SEED_DIR", str(tmp_path))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dash.db"))
    write(tmp_path, "orders.csv", "order_id,ordered_at,customer,amount,status", orders)
    write(tmp_path, "stock.csv", "sku,name,qty,safety_qty", stock)
    write(tmp_path, "inquiries.csv", "inquiry_id,received_at,channel,status", inquiries)
    sys.modules.pop("main", None)
    return TestClient(importlib.import_module("main").app)


@pytest.fixture
def client(tmp_path, monkeypatch):
    now = datetime.now()
    t = now.strftime("%Y-%m-%d")
    y = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    old = (now - timedelta(days=9)).strftime("%Y-%m-%d")
    orders = [
        f"1,{t} 08:00,a,1,접수", f"2,{t} 09:00,a,1,출고", f"3,{t} 10:00,a,1,접수",
        f"4,{t} 00:01,a,1,출고", f"5,{t} 11:00,a,1,취소",
        f"6,{y} 23:50,a,1,출고", f"7,{old} 10:00,a,1,출고",
    ]
    stock = ["s1,a,1,5", "s2,b,2,9", "s3,c,5,5", "s4,d,9,5"]
    inq = [f"1,{t} 08:00,메일,접수", f"2,{t} 08:00,메일,처리중",
           f"3,{t} 08:00,메일,접수", f"4,{t} 08:00,메일,완료"]
    return load_app(tmp_path, monkeypatch, orders, stock, inq)


def test_t1_t2_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "현황판" in r.text
    for label in ("오늘 주문", "재고 경고", "미처리 문의"):
        assert label in r.text
    for tid in ("today-orders", "stock-alerts", "open-inquiries", "updated-at"):
        assert f'data-testid="{tid}"' in r.text


def test_t3_t4_t5_t9_api(client):
    d = client.get("/api/summary").json()
    assert d["today_orders"] == 4
    assert d["stock_alerts"] == 2
    assert d["open_inquiries"] == 3
    assert d["empty"] is False
    assert set(d) == {"today_orders", "stock_alerts", "open_inquiries",
                      "daily_orders", "updated_at", "empty"}


def test_t6_seven_days(client):
    days = client.get("/api/summary").json()["daily_orders"]
    assert len(days) == 7
    assert days[-1]["date"] == datetime.now().strftime("%Y-%m-%d")
    assert days[-1]["count"] == 4 and days[-2]["count"] == 1
    assert all(x["count"] == 0 for x in days[:5])


def test_t7_updated_at(client):
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", client.get("/api/summary").json()["updated_at"])


def test_t8_empty(tmp_path, monkeypatch):
    c = load_app(tmp_path, monkeypatch, [], [], [])
    d = c.get("/api/summary").json()
    assert d["empty"] is True
    assert d["today_orders"] is None and d["stock_alerts"] is None and d["open_inquiries"] is None
    assert len(d["daily_orders"]) == 7
