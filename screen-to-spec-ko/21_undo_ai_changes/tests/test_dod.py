# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 1편 — 오늘의 현황판 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765, 빈 데이터 검사는 +1)

데이터 계약(PRD 5 데이터): seed/orders.csv · seed/stock.csv · seed/inquiries.csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
"""
import csv
import datetime as dt
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))
TODAY = dt.date.today()


def D(n):
    """n일 전 날짜 (YYYY-MM-DD)."""
    return (TODAY - dt.timedelta(days=n)).isoformat()


# ── 고정 데이터 (정답을 아는 값) ────────────────────────────────────────────
# 오늘 주문 5건 중 취소 1 → 4. 어제 23:50 주문 2건은 오늘이 아니다. 3일 전은 0건(막대에 빠지면 안 됨). 8일 전은 7일 밖.
ORDERS = [
    ("O-1001", D(0) + " 08:10", "행복마트", 184000, "접수"),
    ("O-1002", D(0) + " 09:35", "두리상회", 96000, "출고"),
    ("O-1003", D(0) + " 11:02", "그린식자재", 412000, "접수"),
    ("O-1004", D(0) + " 13:20", "행복마트", 57000, "취소"),
    ("O-1005", D(0) + " 15:48", "미소급식", 230000, "접수"),
    ("O-0991", D(1) + " 23:50", "두리상회", 88000, "출고"),
    ("O-0992", D(1) + " 23:55", "행복마트", 120000, "출고"),
    ("O-0981", D(2) + " 10:00", "미소급식", 75000, "출고"),
    ("O-0982", D(2) + " 14:30", "그린식자재", 310000, "출고"),
    ("O-0983", D(2) + " 16:00", "행복마트", 44000, "출고"),
    ("O-0971", D(4) + " 09:00", "두리상회", 66000, "출고"),
    ("O-0972", D(4) + " 17:10", "미소급식", 98000, "출고"),
    ("O-0961", D(5) + " 12:00", "행복마트", 150000, "출고"),
    ("O-0951", D(8) + " 10:00", "그린식자재", 200000, "출고"),
]
# 현재고 < 안전재고 가 경고. 같으면(두부 300g) 경고가 아니다 → 2건.
STOCK = [
    ("F101", "냉동만두 1kg", 12, 40),
    ("F102", "냉동 김말이 1kg", 80, 40),
    ("C201", "두부 300g", 60, 60),
    ("C204", "떡볶이 떡 1kg", 5, 30),
    ("D301", "고추장 500g", 300, 50),
    ("M401", "밀키트 부대찌개", 44, 20),
]
# 접수 2 + 처리중 1 = 미처리 3. 완료 3건은 세지 않는다.
INQUIRIES = [
    ("Q-301", D(0) + " 09:00", "전화", "접수"),
    ("Q-302", D(0) + " 10:30", "이메일", "처리중"),
    ("Q-303", D(1) + " 15:00", "전화", "완료"),
    ("Q-304", D(1) + " 16:20", "채팅", "접수"),
    ("Q-305", D(2) + " 11:00", "이메일", "완료"),
    ("Q-306", D(3) + " 14:00", "전화", "완료"),
]
EXPECT = dict(today_orders=4, stock_alerts=2, open_inquiries=3,
              daily=[0, 1, 2, 0, 3, 2, 4])   # 6일 전 → 오늘


def write_seed(empty=False):
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"], ORDERS),
              ("stock.csv", ["sku", "name", "qty", "safety_qty"], STOCK),
              ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"], INQUIRIES)]
    for name, header, rows in tables:
        with open(os.path.join(seed, name), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            if not empty:
                w.writerows(rows)


def restore_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(bak):
        shutil.rmtree(seed, ignore_errors=True)
        shutil.copytree(bak, seed)
        shutil.rmtree(bak, ignore_errors=True)


def find_app_target():
    """uvicorn 에 넘길 'module:variable'. main.py 의 app 을 먼저 보고, 없으면 FastAPI() 를 만든 파일을 찾는다."""
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


def free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


class Server:
    def __init__(self, port, empty=False):
        self.port = port
        self.base = "http://127.0.0.1:%d" % port
        self.proc = None
        self.empty = empty
        self.target, self.file = find_app_target()
        self.log = ""

    def start(self):
        if not self.target:
            pytest.fail("FastAPI 앱을 찾지 못함 (main.py 에 app = FastAPI() 가 없다)")
        write_seed(self.empty)
        for p in glob.glob(os.path.join(APP, "**", "*.db"), recursive=True):   # 지난 실행의 DB 를 지워 seed 를 다시 읽게
            try:
                os.remove(p)
            except OSError:
                pass
        env = dict(os.environ, PORT=str(self.port), PYTHONUTF8="1")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", self.target, "--port", str(self.port)],
                                     cwd=APP, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                out = self.proc.communicate(timeout=5)[0]
                self.log = (out or b"").decode("utf-8", "ignore")
            except Exception:
                pass
        restore_seed()


@pytest.fixture(scope="module")
def pw():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def open_page(pw, s):
    """화면을 연다. 요청 하나가 멈춰도 테스트가 매달리지 않게 load 까지만 기다리고 1.5초 더 준다."""
    page = pw.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.goto(s.base + "/", wait_until="load", timeout=15000)
        page.wait_for_timeout(1500)
    except Exception as e:
        page.close()
        s.stop()
        pytest.fail("화면이 열리지 않음: %s" % str(e)[:200])
    return page


def shutdown(s, page):
    try:
        page.close()
    except Exception:
        pass
    s.stop()


@pytest.fixture(scope="module")
def full(pw):
    s = Server(PORT).start()
    page = open_page(pw, s)
    yield s, page
    shutdown(s, page)


@pytest.fixture(scope="module")
def empty(pw, full):
    # 같은 폴더의 DB 파일을 두 서버가 함께 쓰면 (윈도우에서) 두 번째가 뜨지 못한다 → 고정 데이터 서버를 먼저 내린다.
    # 그래서 T8 은 파일 맨 끝에 있다 (full 을 쓰는 테스트가 모두 끝난 뒤).
    shutdown(*full)
    s = Server(PORT + 1, empty=True).start()
    page = open_page(pw, s)
    yield s, page
    shutdown(s, page)


# ── 화면에서 값 읽기 (data-testid 가 있으면 그것, 없으면 라벨 근처 숫자) ─────────
FIND_JS = r"""
(label) => {
  const isNum = (t) => /^\s*[\d,]+\s*(건|개|품목)?\s*$/.test(t) || /^\s*[—–\-]\s*$/.test(t);
  const leaves = [...document.querySelectorAll('body *')].filter(e => e.children.length === 0 || [...e.children].every(c => c.tagName === 'SPAN' || c.tagName === 'B' || c.tagName === 'SMALL'));
  const hits = leaves.filter(e => (e.textContent || '').replace(/\s+/g, ' ').includes(label));
  for (const h of hits) {
    let a = h;
    for (let up = 0; up < 5 && a; up++) {
      const texts = [...a.querySelectorAll('*')].filter(e => e.children.length === 0).map(e => (e.textContent || '').trim());
      const v = texts.find(t => t && isNum(t) && !t.includes(label));
      if (v) return v;
      a = a.parentElement;
    }
  }
  return null;
}
"""
LABEL = {"today-orders": "오늘 주문", "stock-alerts": "재고 경고", "open-inquiries": "미처리 문의"}


def metric(page, tid):
    el = page.query_selector('[data-testid="%s"]' % tid)
    if el:
        return (el.inner_text() or "").strip()
    return page.evaluate(FIND_JS, LABEL[tid])


def as_int(v):
    if v is None:
        return None
    m = re.search(r"[\d,]+", v)
    return int(m.group().replace(",", "")) if m else None


def bar_count(page):
    bars = page.query_selector_all('[data-testid="daily-bar"]')
    if bars:
        return len(bars)
    for sel in ("svg rect", ".bar", "[class*=bar] > div", "[class*=bar] > span", "li[class*=bar]"):
        n = len(page.query_selector_all(sel))
        if n:
            return n
    return 0


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(full):
    s, page = full
    r = urllib.request.urlopen(s.base + "/", timeout=5)
    assert r.status == 200
    assert "현황판" in page.title() or "현황판" in page.inner_text("body")


def test_T2_three_metric_labels(full):
    _, page = full
    body = page.inner_text("body").replace("\n", " ")
    for label in LABEL.values():
        assert label in body, "라벨 없음: " + label


def test_T3_today_orders_excludes_cancel_and_yesterday(full):
    _, page = full
    assert as_int(metric(page, "today-orders")) == EXPECT["today_orders"]


def test_T4_stock_alert_is_strictly_below_safety(full):
    _, page = full
    assert as_int(metric(page, "stock-alerts")) == EXPECT["stock_alerts"]


def test_T5_open_inquiries_exclude_done(full):
    _, page = full
    assert as_int(metric(page, "open-inquiries")) == EXPECT["open_inquiries"]


def test_T6_seven_bars_including_zero_days(full):
    _, page = full
    assert bar_count(page) == 7


def test_T7_updated_at_shown(full):
    _, page = full
    el = page.query_selector('[data-testid="updated-at"]')
    text = (el.inner_text() if el else page.inner_text("body"))
    assert re.search(r"갱신[^\n]{0,20}\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", text), "갱신 YYYY-MM-DD HH:MM 형식이 없음"


def test_T9_summary_api_contract(full):
    s, _ = full
    data = json.loads(urllib.request.urlopen(s.base + "/api/summary", timeout=5).read().decode("utf-8"))
    assert data["today_orders"] == EXPECT["today_orders"]
    assert data["stock_alerts"] == EXPECT["stock_alerts"]
    assert data["open_inquiries"] == EXPECT["open_inquiries"]
    assert [d["count"] for d in data["daily_orders"]] == EXPECT["daily"]
    assert re.match(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", data["updated_at"])


# T8 은 맨 끝: 고정 데이터 서버를 내리고 빈 데이터 서버를 새로 띄운다 (empty 픽스처 주석 참고).
def test_T8_empty_data_shows_dash_not_zero(empty):
    _, page = empty
    body = page.inner_text("body")
    assert "데이터 없음" in body
    for tid in LABEL:
        v = metric(page, tid)
        assert v is not None and re.fullmatch(r"\s*[—–\-]\s*", v), "%s 가 '—' 가 아님: %r" % (tid, v)
