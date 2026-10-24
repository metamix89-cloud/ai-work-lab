# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 2부 2편 — 유통기한 임박 재고 알림판 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users · items · lots .csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
고정 데이터의 날짜는 **테스트를 돌리는 날(오늘 = D)** 기준. 서버 하나를 T1~T9 가 차례로 쓴다 — 앞 테스트의 출고 · 폐기를 뒤 테스트가 전제로 한다.
"""
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상(꼬르륵식품은 가상 회사), 날짜는 오늘(D) 기준 ──
D = date.today()


def day(n):
    """오늘 + n 일 (n 이 음수면 과거)"""
    return (D + timedelta(days=n)).isoformat()


USERS = [("s1", "김창고", "staff"), ("s2", "이창고", "staff"), ("m1", "박관리", "manager")]
ITEMS = [("I01", "두부 300g", 1500, 3), ("I02", "김치 1kg", 9000, 7), ("I03", "냉동만두 1kg", 8900, 30),
         ("I04", "참기름 320ml", 12000, 30), ("I05", "떡볶이 떡 500g", 3500, 7)]
# lot_id, item_id, produced_on, expires_on, qty
LOTS = [("L-2401", "I01", day(-5), day(0), 10),      # 유통기한 당일 → 임박(만료 아님)
        ("L-2402", "I01", day(-6), day(-1), 4),      # 어제 만료 → 출고 제외 · 부족 계산에서 제외
        ("L-2403", "I01", day(-2), day(3), 6),       # 남은 3 = near_days 3 → 임박
        ("L-2404", "I01", day(-1), day(4), 20),      # 남은 4 → 정상
        ("L-2405", "I02", day(-30), day(20), 5),     # 생산은 빠르지만 유통기한이 늦다 → 뒤로
        ("L-2406", "I02", day(-10), day(5), 3),      # 유통기한이 이르다 → 먼저 (FEFO)
        ("L-2407", "I03", day(-40), day(-10), 8),    # 만료 → 관리자 폐기 대상
        ("L-2408", "I03", day(-20), day(100), 15),
        ("L-2409", "I04", day(-100), day(2), 0),     # 수량 0 → 목록에서 뺀다
        ("L-2410", "I05", day(-3), day(1), 12),      # 임박
        ("L-2411", "I05", day(-1), day(10), 30),
        ("L-2412", "I04", day(-3), day(0), 2)]       # 유통기한 당일(화면 T9 용)
NEAR0 = {"L-2401", "L-2403", "L-2406", "L-2410", "L-2412"}
NEAR_VALUE0 = 1500 * 10 + 1500 * 6 + 9000 * 3 + 3500 * 12 + 12000 * 2     # 117,000


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("items.csv", ["item_id", "name", "unit_price", "near_days"], ITEMS),
              ("lots.csv", ["lot_id", "item_id", "produced_on", "expires_on", "qty"], LOTS)]
    for name, header, rows in tables:
        with open(os.path.join(seed, name), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)


def restore_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(bak):
        for _ in range(10):      # 윈도우: 죽은 서버가 파일을 놓기 전에 지우면 실패한다(9편 C3 보고) — 잠깐씩 다시 시도
            try:
                shutil.rmtree(seed, ignore_errors=False) if os.path.isdir(seed) else None
                shutil.copytree(bak, seed)
                shutil.rmtree(bak, ignore_errors=True)
                return
            except OSError:
                time.sleep(0.5)


def find_app_target():
    cands = [os.path.join(APP, "main.py")] + sorted(glob.glob(os.path.join(APP, "**", "*.py"), recursive=True))
    for p in cands:
        if not os.path.exists(p) or os.sep + "tests" + os.sep in p or "seed" in p or "_grader" in p:
            continue
        try:
            src = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        m = re.search(r"^\s*(\w+)\s*=\s*FastAPI\s*\(", src, re.M)
        if m:
            rel = os.path.relpath(p, APP)[:-3].replace(os.sep, ".")
            return rel + ":" + m.group(1), p
    return None, None


class Server:
    def __init__(self, port):
        self.port = port
        self.base = "http://127.0.0.1:%d" % port
        self.proc = None
        self.target, self.file = find_app_target()
        self.log = ""

    def start(self):
        if not self.target:
            pytest.fail("FastAPI 앱을 찾지 못함 (main.py 에 app = FastAPI() 가 없다)")
        write_seed()
        for p in glob.glob(os.path.join(APP, "**", "*.db"), recursive=True):
            try:
                os.remove(p)
            except OSError:
                pass
        env = dict(os.environ, PORT=str(self.port), PYTHONUTF8="1")
        # 서버 출력은 파일로 받는다. PIPE 로 받고 읽지 않으면 접속 로그가 버퍼를 채워 서버가 멈춘다(10편 C1 빌더가 찾아 준 채점기 버그)
        self.logf = tempfile.TemporaryFile()
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", self.target, "--port", str(self.port)],
                                     cwd=APP, env=env, stdout=self.logf, stderr=subprocess.STDOUT)
        for _ in range(60):
            if self.proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(self.base + "/", timeout=1)
                return self
            except Exception:
                time.sleep(0.5)
        self.stop()
        pytest.fail("서버가 20초 안에 뜨지 않음: %s\n%s" % (self.target, self.log[-1500:]))

    def stop(self):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.kill()
            try:
                self.proc.wait(timeout=5)
                self.logf.seek(0)
                self.log = self.logf.read().decode("utf-8", "ignore")
                self.logf.close()
            except Exception:
                pass
        restore_seed()


def http(method, url, body=None, timeout=10):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        raw = r.read().decode("utf-8")
        status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        status = e.code
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw


def board(s):
    st, body = http("GET", s.base + "/api/lots")
    assert st == 200 and isinstance(body, dict) and "lots" in body and "summary" in body, ("GET /api/lots", st, body)
    return body


def lot(s, lid):
    for l in board(s)["lots"]:
        if l["lot_id"] == lid:
            return l
    return None


def ship(s, user, item, qty):
    return http("POST", s.base + "/api/ship", {"user": user, "item_id": item, "qty": qty})


def dispose(s, lid, body):
    return http("POST", s.base + "/api/lots/%s/dispose" % lid, body)


@pytest.fixture(scope="module")
def pw():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def srv():
    s = Server(PORT).start()
    yield s
    s.stop()


def open_page(pw, s):
    pg = pw.new_page(viewport={"width": 1400, "height": 900})
    try:
        pg.goto(s.base + "/", wait_until="load", timeout=15000)
        pg.wait_for_timeout(1500)
    except Exception as e:
        pg.close()
        pytest.fail("화면이 열리지 않음: %s" % str(e)[:200])
    return pg


def digits(text):
    return [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text or "")]


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    pg = open_page(pw, srv)
    assert "유통기한" in pg.title() or "유통기한" in pg.inner_text("body")
    pg.close()


def test_T2_contract(srv):
    st, users = http("GET", srv.base + "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {(u, r) for u, _, r in USERS}, users
    st, items = http("GET", srv.base + "/api/items")
    assert st == 200 and {(i["item_id"], i["unit_price"], i["near_days"]) for i in items} == {(i, p, n) for i, _, p, n in ITEMS}, items
    b = board(srv)
    ids = [l["lot_id"] for l in b["lots"]]
    assert "L-2409" not in ids, "수량 0 인 로트는 목록에서 뺀다"
    assert ids == ["L-2407", "L-2402", "L-2401", "L-2412", "L-2410", "L-2403", "L-2404", "L-2406", "L-2411", "L-2405", "L-2408"], ("남은 일수 오름차순 · 같으면 lot_id", ids)
    l = {x["lot_id"]: x for x in b["lots"]}
    assert (l["L-2401"]["item_name"], l["L-2401"]["days_left"], l["L-2401"]["unit_price"]) == ("두부 300g", 0, 1500), l["L-2401"]
    assert b["today"] == day(0)
    assert b["summary"] == {"near": 5, "expired": 2, "near_value": NEAR_VALUE0}, b["summary"]


def test_T3_state_boundaries(srv):
    l = {x["lot_id"]: x for x in board(srv)["lots"]}
    assert l["L-2401"]["state"] == "near", ("유통기한 당일은 임박(만료 아님)", l["L-2401"])
    assert l["L-2402"]["state"] == "expired" and l["L-2402"]["days_left"] == -1, l["L-2402"]
    assert l["L-2403"]["state"] == "near", ("남은 일수 = near_days 는 임박", l["L-2403"])
    assert l["L-2404"]["state"] == "ok", ("near_days 보다 하루 더 남으면 정상", l["L-2404"])
    assert l["L-2412"]["state"] == "near" and l["L-2405"]["state"] == "ok"


def test_T4_fefo_allocation(srv):
    st, body = ship(srv, "s1", "I02", 5)
    assert st == 200, ("출고", st, body)
    assert [(a["lot_id"], a["qty"]) for a in body["allocations"]] == [("L-2406", 3), ("L-2405", 2)], ("유통기한 이른 로트부터, 모자라면 다음 로트로", body.get("allocations"))
    assert lot(srv, "L-2406") is None and lot(srv, "L-2405")["qty"] == 3, "배분된 만큼 줄고, 0 이 된 로트는 목록에서 빠진다"


def test_T5_expired_excluded_all_or_nothing(srv):
    before = {x["lot_id"]: x["qty"] for x in board(srv)["lots"]}
    st, body = ship(srv, "s1", "I01", 37)
    assert st == 409, ("만료 아닌 수량 합 36 < 37 → 409 (만료 로트 4개는 세지 않는다)", st, body)
    assert {x["lot_id"]: x["qty"] for x in board(srv)["lots"]} == before, "거부되면 아무 로트도 줄지 않는다"
    st, body = ship(srv, "s2", "I01", 12)
    assert st == 200 and [(a["lot_id"], a["qty"]) for a in body["allocations"]] == [("L-2401", 10), ("L-2403", 2)], ("만료 L-2402 는 건너뛴다", st, body)
    assert lot(srv, "L-2402")["qty"] == 4, "만료 로트는 그대로"


def test_T6_dispose(srv):
    st, body = dispose(srv, "L-2407", {"user": "s1", "reason": "곰팡이"})
    assert st == 403, ("창고 담당의 폐기는 403", st, body)
    st, body = dispose(srv, "L-2410", {"user": "m1", "reason": "곰팡이"})
    assert st == 409, ("임박 로트는 폐기할 수 없다(409)", st, body)
    st, body = dispose(srv, "L-2407", {"user": "m1", "reason": "   "})
    assert st == 400, ("빈 사유는 400", st, body)
    st, body = dispose(srv, "L-2407", {"user": "m1", "reason": "곰팡이 발생"})
    assert st == 200 and body["lot"]["qty"] == 0, (st, body)
    assert lot(srv, "L-2407") is None and body["summary"]["expired"] == 1, ("폐기한 로트는 목록에서 빠지고 요약 expired 가 준다", body.get("summary"))


def test_T7_near_value(srv):
    b = board(srv)
    near = [x for x in b["lots"] if x["state"] == "near"]
    assert {x["lot_id"] for x in near} == {"L-2403", "L-2410", "L-2412"}, [x["lot_id"] for x in near]
    assert b["summary"]["near"] == 3 and b["summary"]["near_value"] == 1500 * 4 + 3500 * 12 + 12000 * 2, ("단가 × 수량 합(출고 뒤 줄어든 값)", b["summary"])
    assert b["summary"]["near_value"] < NEAR_VALUE0


def test_T8_reject_order(srv):
    st, body = dispose(srv, "L-9999", {})
    assert st == 400, ("본문에 user 없음 + 없는 로트는 400 이 먼저", st, body)
    st, body = dispose(srv, "L-9999", {"user": "m1", "reason": "x"})
    assert st == 404, ("없는 로트는 404", st, body)
    st, body = dispose(srv, "L-2404", {"user": "nobody", "reason": "x"})
    assert st == 404, ("없는 사용자는 404", st, body)
    st, body = dispose(srv, "L-2404", {"user": "s1", "reason": "x"})
    assert st == 403, ("창고 담당이 정상 로트를 폐기하면 권한(403)이 상태(409)보다 먼저", st, body)
    st, body = ship(srv, "s1", "I01", 0)
    assert st == 400, ("수량 0 은 400", st, body)
    st, body = ship(srv, "s1", "I99", 1)
    assert st == 404, ("없는 품목은 404", st, body)


def test_T9_screen(srv, pw):
    pg = open_page(pw, srv)
    row = pg.query_selector('[data-testid="lot"][data-id="L-2402"]')
    assert row is not None and row.get_attribute("data-state") == "expired", "L-2402 줄(data-state=expired)이 없다"
    row2 = pg.query_selector('[data-testid="lot"][data-id="L-2412"]')
    assert row2 is not None and row2.get_attribute("data-state") == "near", "유통기한 당일 L-2412 가 near 가 아니다"
    sn = pg.query_selector('[data-testid="sum-near"]')
    assert sn is not None and digits(sn.inner_text()), "요약 숫자가 없다"
    assert pg.query_selector('[data-testid="dispose"]') is None, "창고 담당(첫 사용자)에게 폐기 버튼이 보인다"
    pg.select_option('[data-testid="user"]', "m1")
    pg.wait_for_timeout(1200)
    assert pg.query_selector('[data-testid="lot"][data-id="L-2402"] [data-testid="dispose"]') is not None, "관리자에게 만료 줄의 폐기 버튼이 없다"
    assert pg.query_selector('[data-testid="lot"][data-id="L-2404"] [data-testid="dispose"]') is None, "정상 줄에 폐기 버튼이 있다"
    pg.select_option('[data-testid="item"]', "I04")
    pg.fill('[data-testid="qty"]', "99")
    pg.click('[data-testid="ship"]')
    pg.wait_for_timeout(1000)
    msg = pg.query_selector('[data-testid="message"]')
    assert msg is not None and "재고가 부족합니다" in msg.inner_text(), ("재고를 넘는 출고 → 서버의 detail", msg.inner_text() if msg else None)
    pg.close()
