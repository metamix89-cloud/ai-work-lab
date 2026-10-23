import importlib
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_app(seed_dir):
    os.environ["SEED_DIR"] = str(seed_dir)
    import main
    importlib.reload(main)
    return TestClient(main.app)


def write(seed, orders="", stock="", inquiries=""):
    seed.mkdir(exist_ok=True)
    (seed / "orders.csv").write_text("order_id,ordered_at,customer,amount,status\n" + orders, encoding="utf-8")
    (seed / "stock.csv").write_text("sku,name,qty,safety_qty\n" + stock, encoding="utf-8")
    (seed / "inquiries.csv").write_text("inquiry_id,received_at,channel,status\n" + inquiries, encoding="utf-8")


def fixed(tmp_path):
    t = datetime.now()

    def d(n, hm):
        return (t - timedelta(days=n)).strftime("%Y-%m-%d ") + hm

    rows = [
        (0, "00:01", "접수"), (0, "01:00", "출고"), (0, "02:00", "접수"), (0, "03:00", "출고"),
        (0, "04:00", "취소"), (1, "23:50", "출고"), (3, "10:00", "출고"), (9, "10:00", "출고"),
    ]
    orders = "".join(f"{i},{d(n, hm)},c,1,{s}\n" for i, (n, hm, s) in enumerate(rows))
    stock = "a,A,1,5\nb,B,5,5\nc,C,2,3\nd,D,9,3\n"
    inq = (
        "1,2026-01-01 00:00,메일,접수\n2,2026-01-01 00:00,메일,처리중\n"
        "3,2026-01-01 00:00,메일,접수\n4,2026-01-01 00:00,메일,완료\n"
    )
    write(tmp_path, orders, stock, inq)
    return load_app(tmp_path)


def test_t1_t2_page(tmp_path):
    r = fixed(tmp_path).get("/")
    assert r.status_code == 200
    for s in ["현황판", "오늘 주문", "재고 경고", "미처리 문의", "갱신", "daily-bar", "empty-notice"]:
        assert s in r.text


def test_t3_t4_t5_counts(tmp_path):
    j = fixed(tmp_path).get("/api/summary").json()
    assert j["today_orders"] == 4
    assert j["stock_alerts"] == 2
    assert j["open_inquiries"] == 3


def test_t6_seven_days(tmp_path):
    j = fixed(tmp_path).get("/api/summary").json()
    assert len(j["daily_orders"]) == 7
    assert j["daily_orders"][-1]["count"] == 4
    assert sum(x["count"] for x in j["daily_orders"]) == 6  # 9일 전 제외


def test_t7_t9_format(tmp_path):
    j = fixed(tmp_path).get("/api/summary").json()
    assert set(j) == {"today_orders", "stock_alerts", "open_inquiries", "daily_orders", "updated_at", "empty"}
    datetime.strptime(j["updated_at"], "%Y-%m-%d %H:%M")
    assert j["empty"] is False


def test_t8_empty(tmp_path):
    write(tmp_path)
    j = load_app(tmp_path).get("/api/summary").json()
    assert j["empty"] is True
