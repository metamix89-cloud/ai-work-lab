# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 13편 — 경영 현황 대시보드 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users.csv · orders.csv · stock.csv · inquiries.csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
고정 데이터의 날짜는 **테스트를 돌리는 날(오늘 = D)** 기준으로 만든다. 화면은 읽기만 하므로 테스트끼리 섞이지 않는다.
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
import urllib.parse
import urllib.request
from datetime import date, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상, 날짜는 오늘(D) 기준 ──────────────
D = date.today()


def day(n):
    return (D - timedelta(days=n)).isoformat()


def at(n, hm):
    return "%s %s" % (day(n), hm)


USERS = [("u1", "한대표", "exec"), ("u2", "오영업", "sales"), ("u3", "강물류", "logistics")]
ORDERS = [("O01", at(0, "09:00"), "한빛상회", 120000, "출고"),
          ("O02", at(0, "10:00"), "두레마트", 80000, "접수"),        # 접수 — 주문 수엔 들고 매출엔 안 든다
          ("O03", at(0, "11:00"), "한빛상회", 50000, "취소"),
          ("O04", at(1, "23:50"), "새봄식당", 90000, "출고"),        # 기간 끝날 23:50 (T5)
          ("O05", at(1, "15:00"), "두레마트", 30000, "출고"),
          ("O06", at(2, "13:00"), "다솜카페", 45000, "취소"),
          ("O07", at(3, "09:00"), "마루푸드", 200000, "출고"),
          ("O08", at(3, "10:00"), "다솜카페", 40000, "취소"),
          ("O09", at(4, "23:59"), "늘봄유통", 90000, "출고"),        # 시작일 전날 23:59 (T5) · 새봄식당과 매출 같음 → 이름 순
          ("O10", at(6, "08:00"), "한빛상회", 60000, "출고"),
          ("O11", at(7, "12:00"), "소담", 999000, "출고"),           # 기본 기간(최근 7일) 밖
          ("O12", at(0, "00:05"), "온새미", 10000, "출고")]
STOCK = [("S1", "두부 300g", 5, 10), ("S2", "고추장 1kg", 20, 10), ("S3", "포기김치", 3, 8),
         ("S4", "참기름 320ml", 7, 7),                               # 같으면 경고 아님
         ("S5", "냉동만두", 50, 20), ("S6", "김 선물세트", 12, 10)]
INQUIRIES = [("I1", at(0, "09:00"), "전화", "접수"), ("I2", at(1, "10:00"), "메일", "처리중"),
             ("I3", at(2, "11:00"), "메일", "완료"), ("I4", at(3, "14:00"), "전화", "접수"),
             ("I5", at(5, "09:00"), "메일", "완료"),
             ("I6", at(27, "10:00"), "전화", "접수")]                # 오래된 미처리 — 기본 기간엔 안 든다(R6)
TOP5 = [("마루푸드", 200000), ("한빛상회", 180000), ("늘봄유통", 90000), ("새봄식당", 90000), ("두레마트", 30000)]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"], ORDERS),
              ("stock.csv", ["sku", "name", "qty", "safety_qty"], STOCK),
              ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"], INQUIRIES)]
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


def dash(s, viewer="u1", frm=None, to=None, raw=False):
    q = {}
    if viewer is not None:
        q["viewer"] = viewer
    if frm is not None:
        q["from"] = frm
    if to is not None:
        q["to"] = to
    url = s.base + "/api/dashboard?" + urllib.parse.urlencode(q)
    if raw:
        try:
            r = urllib.request.urlopen(url, timeout=10)
            return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "ignore")
    return http("GET", url)


def ok(s, **kw):
    st, body = dash(s, **kw)
    assert st == 200 and isinstance(body, dict), ("GET /api/dashboard", kw, st, body)
    return body


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
    assert "현황" in pg.title() or "현황" in pg.inner_text("body")
    pg.close()


def test_T2_contract(srv):
    b = ok(srv)
    assert b["period"] == {"from": day(6), "to": day(0)}, ("기본 기간은 최근 7일(오늘 포함)", b.get("period"))
    assert set(b["metrics"]) == {"orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries"}, b.get("metrics")
    assert [d["date"] for d in b["daily"]] == [day(n) for n in range(6, -1, -1)], ("막대 7칸, 날짜 차례", b.get("daily"))
    assert [d["count"] for d in b["daily"]] == [1, 0, 1, 1, 0, 2, 3], ("0 인 날도 칸", [d["count"] for d in b["daily"]])
    st, users = http("GET", srv.base + "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {("u1", "exec"), ("u2", "sales"), ("u3", "logistics")}, users


def test_T3_orders_and_revenue(srv):
    m = ok(srv)["metrics"]
    assert m["orders"] == 8, ("주문 수 = 취소 제외", m["orders"])
    assert m["revenue"] == 600000, ("매출 = 출고만(접수 80,000 제외)", m["revenue"])
    assert m["stock_alerts"] == 2, ("재고 경고 = qty < safety_qty (같으면 아님)", m["stock_alerts"])


def test_T4_cancel_rate_and_top(srv):
    b = ok(srv)
    assert b["metrics"]["cancel_rate"] == 27.3, ("취소율 3/11 = 27.27 → 27.3", b["metrics"]["cancel_rate"])
    got = [(x["customer"], x["revenue"]) for x in b["top_customers"]]
    assert got == TOP5, ("거래처 상위 5 — 매출 큰 순, 같으면 이름 순, 출고만", got)


def test_T5_period_boundary(srv):
    m = ok(srv, frm=day(3), to=day(1))["metrics"]
    assert m["orders"] == 3, ("기간 양 끝 포함 — 끝날 23:50 은 들고, 시작 전날 23:59 · 다음 날은 빠진다", m["orders"])
    assert m["revenue"] == 320000, ("기간 매출", m["revenue"])
    assert m["cancel_rate"] == 40.0, ("기간 취소율 2/5", m["cancel_rate"])


def test_T6_period_errors(srv):
    for kw in (dict(frm=day(1), to=day(3)), dict(frm=day(31), to=day(0)), dict(frm="2026/10/01", to=day(0)), dict(frm=day(3))):
        st, body = dash(srv, **kw)
        assert st == 400, ("기간 오류는 400", kw, st, body)
    st, body = dash(srv, frm=day(30), to=day(0))
    assert st == 200, ("31일까지는 된다", st, body)
    st, body = dash(srv, viewer="nobody")
    assert st == 404, ("없는 사용자는 404", st, body)
    st, body = dash(srv, viewer=None, frm="bad", to=day(0))
    assert st == 400, ("viewer 없음 + 형식 오류는 400", st, body)


def test_T7_roles(srv):
    st, raw = dash(srv, viewer="u3", raw=True)
    assert st == 200, (st, raw)
    b = json.loads(raw)
    assert set(b["metrics"]) == {"orders", "stock_alerts"}, ("물류팀: 주문 수 · 재고 경고만", sorted(b["metrics"]))
    assert "top_customers" not in b, "물류팀 응답에 거래처 키가 있다"
    assert "600000" not in raw and "200000" not in raw, "물류팀 응답 어딘가에 매출 숫자가 있다(화면만 숨김)"
    s = ok(srv, viewer="u2")
    assert set(s["metrics"]) == {"orders", "revenue", "cancel_rate", "open_inquiries"}, ("영업팀", sorted(s["metrics"]))
    assert "top_customers" not in s, "영업팀 응답에 거래처 키가 있다"


def test_T8_empty_period(srv):
    b = ok(srv, frm=day(30), to=day(25))
    m = b["metrics"]
    assert (m["orders"], m["revenue"], m["cancel_rate"]) == (0, 0, None), ("주문 없는 기간: 0 · 0 · null(0 아님)", m)
    assert [d["count"] for d in b["daily"]] == [0] * 6, ("막대는 날 수만큼 0", b.get("daily"))
    assert m["open_inquiries"] == 1, ("미처리 문의는 기간 안에 들어온 것만 — 이 기간엔 1건", m["open_inquiries"])
    assert ok(srv)["metrics"]["open_inquiries"] == 3, "기본 기간엔 27일 전 미처리 문의가 안 든다"


def test_T9_screen(srv, pw):
    pg = open_page(pw, srv)
    rev = pg.query_selector('[data-testid="m-revenue"]')
    assert rev is not None and 600000 in digits(rev.inner_text()), ("대표에게 매출 카드(600,000)", rev.inner_text() if rev else None)
    pg.select_option('[data-testid="user"]', "u3")
    pg.wait_for_timeout(1200)
    assert pg.query_selector('[data-testid="m-revenue"]') is None, "물류팀인데 매출 카드가 있다"
    assert pg.query_selector('[data-testid="m-stock-alerts"]') is not None, "물류팀에게 재고 경고 카드가 없다"
    pg.select_option('[data-testid="user"]', "u2")
    pg.wait_for_timeout(1000)
    pg.fill('[data-testid="from"]', day(30))
    pg.fill('[data-testid="to"]', day(25))
    pg.click('[data-testid="apply"]')
    pg.wait_for_timeout(1200)
    cr = pg.query_selector('[data-testid="m-cancel-rate"]')
    assert cr is not None and "—" in cr.inner_text(), ("주문 없는 기간의 취소율은 —", cr.inner_text() if cr else None)
    pg.fill('[data-testid="from"]', day(0))
    pg.fill('[data-testid="to"]', day(1))
    pg.click('[data-testid="apply"]')
    pg.wait_for_timeout(1000)
    msg = pg.query_selector('[data-testid="message"]')
    assert msg is not None and "기간을 확인하세요" in msg.inner_text(), ("시작 > 종료 → 서버의 detail", msg.inner_text() if msg else None)
    pg.close()
