import os
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402

M = "2026-11"


@pytest.fixture()
def client():
    main.init_db()
    return TestClient(main.app)


def gen(c, month=M):
    r = c.post("/api/roster/generate", json={"month": month})
    assert r.status_code == 200, r.text
    return {d["date"]: d["name"] for d in r.json()["days"]}


def test_t1_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "당직" in r.text


def test_t2_every_day_one(client):
    days = gen(client)
    assert len(days) == 30 and all(days.values())


def test_t3_unavailable(client):
    days = gen(client)
    for u in client.get("/api/unavailable", params={"month": M}).json():
        assert days[u["date"]] != u["name"]


def test_t4_no_consecutive(client):
    days = gen(client)
    ds = sorted(days)
    assert days[ds[0]] != "최유나"  # 10-31 이 최유나
    for a, b in zip(ds, ds[1:]):
        assert days[a] != days[b]


def test_t5_t6_fair(client):
    gen(client)
    st = client.get("/api/stats", params={"month": M}).json()
    assert len(st) == 6
    t = [s["total"] for s in st]
    w = [s["weekend"] for s in st]
    assert max(t) - min(t) <= 1 and max(w) - min(w) <= 1 and sum(t) == 30


def test_t7_swap(client):
    days = gen(client)
    # 연속을 만드는 바꾸기: 11-10 당직자를 11-20 으로, 이웃과 같은 사람이 되도록 찾는다
    ds = sorted(days)
    found = None
    for i in ds:
        for j in ds:
            if i < j:
                a, b = days[i], days[j]
                if a != b and (date.fromisoformat(j) - date.fromisoformat(i)).days > 2 and any(
                    days.get((date.fromisoformat(j) + timedelta(k)).isoformat()) == a for k in (-1, 1)
                ):
                    found = (i, j)
                    break
        if found:
            break
    assert found
    assert client.post("/api/roster/swap", json={"date_a": found[0], "date_b": found[1]}).status_code == 409
    # 제외일로 보내는 바꾸기: 박지연 제외일 11-03 으로 박지연이 아닌 사람을 보내려면 박지연 날과 교환
    pj = next(d for d in ds if days[d] == "박지연")
    r = client.post("/api/roster/swap", json={"date_a": "2026-11-03", "date_b": pj})
    assert r.status_code == 409
    # 규칙 안의 바꾸기
    for i in ds:
        for j in ds:
            if i < j and days[i] != days[j]:
                r = client.post("/api/roster/swap", json={"date_a": i, "date_b": j})
                if r.status_code == 200:
                    new = {d["date"]: d["name"] for d in r.json()["days"]}
                    assert new[i] == days[j] and new[j] == days[i]
                    return
    pytest.fail("가능한 바꾸기가 없음")


def test_swap_rejects(client):
    assert client.post("/api/roster/swap", json={"date_a": "2026-11-01", "date_b": "2026-11-02"}).status_code == 400
    gen(client)
    assert client.post("/api/roster/swap", json={"date_a": "2026-11-01", "date_b": "2026-11-01"}).status_code == 400
    assert client.post("/api/roster/swap", json={"date_a": "2026-11-01", "date_b": "2026-12-99"}).status_code == 400


def test_t8_confirm(client):
    gen(client)
    assert client.post("/api/roster/confirm", json={"month": M}).status_code == 200
    r = client.post("/api/roster/generate", json={"month": M})
    assert r.status_code == 409 and r.json()["detail"] == "확정된 달은 다시 생성할 수 없습니다"
    days = {d["date"]: d["name"] for d in client.get("/api/roster", params={"month": M}).json()["days"]}
    for i in sorted(days):
        for j in sorted(days):
            if i < j and days[i] != days[j]:
                if client.post("/api/roster/swap", json={"date_a": i, "date_b": j}).status_code == 200:
                    return
    pytest.fail("확정 뒤 바꾸기 불가")


def test_confirm_empty(client):
    assert client.post("/api/roster/confirm", json={"month": "2027-01"}).status_code == 400


def test_other_months_generate(client):
    for m in ("2026-12", "2027-02"):
        assert len(gen(client, m)) in (31, 28)


def test_t9_ui(client):
    pw = pytest.importorskip("playwright.sync_api")
    import socket
    import threading
    import time

    import uvicorn

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(main.app, port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(1.5)
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page()
            page.goto(f"http://127.0.0.1:{port}/")
            page.fill('[data-testid="month"]', M)
            page.click('[data-testid="generate-btn"]')
            page.wait_for_selector('[data-testid="day"][data-name]:not([data-name=""])')
            days = page.locator('[data-testid="day"]')
            assert days.count() == 30
            assert all(days.nth(i).get_attribute("data-name") for i in range(30))
            rows = page.locator('[data-testid="stat-row"]')
            assert sum(int(rows.nth(i).get_attribute("data-total")) for i in range(rows.count())) == 30
            b.close()
    finally:
        server.should_exit = True
