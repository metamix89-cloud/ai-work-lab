import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

c = TestClient(main.app)
Q = "/api/dashboard?viewer={}&from={}&to={}"


def get(v, f, t):
    return c.get(Q.format(v, f, t))


def test_page():
    r = c.get("/")
    assert r.status_code == 200 and "현황" in r.text


def test_exec_default_period():
    d = c.get("/api/dashboard?viewer=u1").json()
    assert set(d["metrics"]) == {"orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries"}
    assert len(d["daily"]) == 7 and len(c.get("/api/users").json()) == 3


def test_example_period():
    d = get("u1", "2026-10-18", "2026-10-24").json()
    assert d["metrics"] == {"orders": 8, "revenue": 600000, "cancel_rate": 27.3,
                            "stock_alerts": 2, "open_inquiries": 3}
    assert d["daily"][0] == {"date": "2026-10-18", "count": 1}
    assert [t["customer"] for t in d["top_customers"]] == ["마루푸드", "한빛마트", "새벽유통", "두레상회"]


def test_boundaries():
    d = get("u1", "2026-10-18", "2026-10-23").json()
    assert d["metrics"]["orders"] == 6  # 10-23 23:50 in, 10-24 out, 10-17 23:59 out


def test_errors():
    for f, t in [("2026-10-24", "2026-10-18"), ("2026-10-01", "2026-11-01"), ("x", "2026-10-18")]:
        r = get("u1", f, t)
        assert r.status_code == 400 and r.json() == {"detail": "기간을 확인하세요"}
    assert c.get("/api/dashboard?viewer=u1&from=2026-10-18").status_code == 400
    assert get("zz", "2026-10-18", "2026-10-24").status_code == 404
    assert get("zz", "bad", "2026-10-24").status_code == 400
    assert c.get("/api/dashboard?from=bad&to=bad").status_code == 400


def test_roles():
    d = get("u3", "2026-10-18", "2026-10-24")
    assert set(d.json()["metrics"]) == {"orders", "stock_alerts"}
    assert "top_customers" not in d.json() and "600000" not in d.text
    s = get("u2", "2026-10-18", "2026-10-24").json()
    assert "stock_alerts" not in s["metrics"] and "top_customers" not in s


def test_empty_period():
    d = get("u1", "2026-09-01", "2026-09-05").json()
    assert d["metrics"]["orders"] == 0 and d["metrics"]["revenue"] == 0
    assert d["metrics"]["cancel_rate"] is None and [x["count"] for x in d["daily"]] == [0] * 5
