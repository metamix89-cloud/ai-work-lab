# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 8편 — 세금계산서 발행 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/customers.csv · seed/invoices.csv · seed/invoice_lines.csv 를 서버가 시작할 때 읽는다. 날짜는 '오늘'.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
테스트는 파일 순서대로 돈다 — 계산서가 차례로 생긴다(004 → 005 → 006 → 수정 007).
"""
import csv
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))
TODAY = dt.date.today()
DAY = TODAY.isoformat()
YMD = TODAY.strftime("%Y%m%d")
MONTH = TODAY.strftime("%Y-%m")


def NO(n):
    return "INV-%s-%03d" % (YMD, n)


# ── 고정 데이터 (정답을 아는 값) — 모두 가상 ─────────────────────────────────
CUSTOMERS = [("101-81-11111", "행복마트", "김행복"), ("202-81-22222", "두리상회", "이두리"), ("303-81-33333", "미소급식", "박미소")]
INVOICES = [(NO(1), DAY, "101-81-11111", 10000, 1000, 11000, "발행", "", ""),
            (NO(2), DAY, "202-81-22222", 9240, 924, 10164, "발행", "", ""),
            (NO(3), DAY, "303-81-33333", 5000, 500, 5500, "취소", "", "")]
LINES = [(NO(1), 1, "두부 300g", 10, 1000), (NO(2), 1, "고추장 500g", 2, 4620), (NO(3), 1, "어묵탕 세트", 1, 5000)]
# 줄 공급가 1,005 × 3줄 = 3,015. 정답: 합계에 10% 원 미만 버림 = 301.
# 틀린 방법은 모두 다른 값: 줄마다 버림 300 · 줄마다 짝수 반올림(파이썬 round) 300 · 줄마다 사사오입(JS Math.round) 303 · 합계 반올림 302
# (처음 고른 숫자는 파이썬 round 를 줄마다 쓰면 우연히 정답과 같아져 자가 시험에서 바꿨다)
TRICKY = [{"item": "간장 1.8L", "qty": 1, "unit_price": 1005}, {"item": "김자반 50g", "qty": 5, "unit_price": 201},
          {"item": "참기름 320ml", "qty": 3, "unit_price": 335}]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("customers.csv", ["biz_no", "name", "ceo"], CUSTOMERS),
              ("invoices.csv", ["invoice_no", "issued", "biz_no", "supply", "tax", "total", "status", "amends", "amended_by"], INVOICES),
              ("invoice_lines.csv", ["invoice_no", "line", "item", "qty", "unit_price"], LINES)]
    for name, header, rows in tables:
        with open(os.path.join(seed, name), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)


def restore_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(bak):
        shutil.rmtree(seed, ignore_errors=True)
        shutil.copytree(bak, seed)
        shutil.rmtree(bak, ignore_errors=True)


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
        if self.proc:
            if self.proc.poll() is None:
                self.proc.kill()
            try:      # 이미 죽은 프로세스의 출력도 읽는다(7편 교훈 — 서버가 시작하자마자 죽으면 이유가 여기 있다)
                out = self.proc.communicate(timeout=5)[0]
                self.log = (out or b"").decode("utf-8", "ignore")
            except Exception:
                pass
        restore_seed()


def http(method, url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        raw = r.read().decode("utf-8")
        status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        status = e.code
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw


def issue(s, biz, lines, **extra):
    body = dict({"biz_no": biz, "issued": DAY, "lines": lines}, **extra)
    return http("POST", s.base + "/api/invoices", body)


def ledger(s):
    st, body = http("GET", s.base + "/api/invoices?month=" + MONTH)
    assert st == 200, "GET /api/invoices 가 %s" % st
    return body


def by_no(body):
    return {i["invoice_no"]: i for i in body["items"]}


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
    page = pw.new_page(viewport={"width": 1500, "height": 900})
    try:
        page.goto(s.base + "/", wait_until="load", timeout=15000)
        page.wait_for_timeout(1500)
    except Exception as e:
        page.close()
        pytest.fail("화면이 열리지 않음: %s" % str(e)[:200])
    return page


def digits(text):
    return [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text or "")]


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "세금계산서" in page.title() or "세금계산서" in page.inner_text("body")
    page.close()


def test_T2_tax_on_total_floor(srv):
    st, body = issue(srv, "101-81-11111", TRICKY)
    assert st == 201, (st, body)
    assert (body["supply"], body["tax"], body["total"]) == (3015, 301, 3316), \
        "공급가 · 세액 · 합계 = %s (기대 3015 · 301 · 3316 — 줄마다 세액이면 300 또는 303, 합계 반올림이면 302)" % ((body["supply"], body["tax"], body["total"]),)
    assert body["invoice_no"] == NO(4), body["invoice_no"]


def test_T3_server_recomputes_and_preview_matches(srv):
    lines = [{"item": "간장 1.8L", "qty": 2, "unit_price": 5410, "line_supply": 1, "supply": 1}]
    st, pv = http("POST", srv.base + "/api/invoices/preview", {"biz_no": "202-81-22222", "issued": DAY, "lines": lines})
    assert st == 200, (st, pv)
    st, body = issue(srv, "202-81-22222", lines, supply=1, tax=0, total=1)
    assert st == 201, (st, body)
    assert (body["supply"], body["tax"], body["total"]) == (10820, 1082, 11902), (body["supply"], body["tax"], body["total"])
    assert (pv["supply"], pv["tax"], pv["total"]) == (body["supply"], body["tax"], body["total"]), "미리보기와 발행 금액이 다르다"


def test_T4_numbering_continues(srv):
    st, body = issue(srv, "202-81-22222", [{"item": "김 선물세트", "qty": 1, "unit_price": 100}])
    assert st == 201, (st, body)
    assert body["invoice_no"] == NO(6), body["invoice_no"]
    nos = [i["invoice_no"] for i in ledger(srv)["items"]]
    assert nos == [NO(n) for n in range(1, 7)], "대장 번호 순서: %s" % nos


def test_T5_required_fields(srv):
    good = [{"item": "두부 300g", "qty": 1, "unit_price": 1000}]
    cases = [("모르는 거래처", issue(srv, "999-99-99999", good)),
             ("품목 없음", issue(srv, "101-81-11111", [])),
             ("수량 0", issue(srv, "101-81-11111", [{"item": "두부", "qty": 0, "unit_price": 1000}])),
             ("수량 1.5", issue(srv, "101-81-11111", [{"item": "두부", "qty": 1.5, "unit_price": 1000}])),
             ("음수 단가", issue(srv, "101-81-11111", [{"item": "두부", "qty": 1, "unit_price": -1}]))]
    bad = [(name, st) for name, (st, _) in cases if st != 400]
    assert not bad, "400 이어야 하는데: %s" % bad
    assert ledger(srv)["count"] == 6, "거부된 요청인데 계산서가 생겼다"


def test_T6_amend_creates_new_and_keeps_original(srv):
    st, body = http("POST", srv.base + "/api/invoices/INV-00000000-999/amend", {"issued": DAY, "lines": []})
    assert st == 400, ("없는 번호 + 잘못된 본문은 400 이 먼저", st, body)
    st, body = http("POST", srv.base + "/api/invoices/INV-00000000-999/amend", {"issued": DAY, "lines": [{"item": "두부", "qty": 1, "unit_price": 1000}]})
    assert st == 404, ("없는 번호 + 올바른 본문은 404", st, body)
    st, new = http("POST", srv.base + "/api/invoices/%s/amend" % NO(1), {"issued": DAY, "lines": [{"item": "두부 300g", "qty": 12, "unit_price": 1000}]})
    assert st == 201, (st, new)
    assert new["invoice_no"] == NO(7) and new["amends"] == NO(1), new
    assert (new["supply"], new["tax"], new["total"]) == (12000, 1200, 13200)
    assert new.get("biz_no") == "101-81-11111", "수정 발행의 거래처는 원본과 같아야 한다"
    st, orig = http("GET", srv.base + "/api/invoices/" + NO(1))
    assert st == 200 and orig["status"] == "수정됨" and orig["amended_by"] == NO(7), orig
    assert [(l["qty"], l["unit_price"]) for l in orig["lines"]] == [(10, 1000)] and orig["total"] == 11000, "원본 품목 · 금액이 바뀌었다"
    st, body = http("POST", srv.base + "/api/invoices/%s/amend" % NO(1), {"issued": DAY, "lines": [{"item": "두부", "qty": 1, "unit_price": 1000}]})
    assert st == 409, ("이미 수정된 원본을 또 고치면 409", st, body)


def test_T7_cancel(srv):
    st, body = http("POST", srv.base + "/api/invoices/%s/cancel" % NO(2))
    assert st == 200 and body.get("status") == "취소", (st, body)
    st, body = http("POST", srv.base + "/api/invoices/%s/amend" % NO(2), {"issued": DAY, "lines": [{"item": "고추장", "qty": 1, "unit_price": 4620}]})
    assert st == 409, ("취소된 계산서 수정은 409", st, body)
    st, body = http("POST", srv.base + "/api/invoices/%s/cancel" % NO(2))
    assert st == 409, ("다시 취소는 409", st, body)
    st, body = http("POST", srv.base + "/api/invoices/%s/cancel" % NO(3))
    assert st == 409, ("seed 의 취소 계산서 취소는 409", st, body)


def test_T8_month_totals_only_issued(srv):
    body = ledger(srv)
    assert body["count"] == 7, body["count"]
    # 발행: 004(3015/301) · 005(10820/1082) · 006(100/10) · 007(12000/1200) — 001 수정됨 · 002 취소 · 003 취소는 뺀다
    assert body["totals"] == {"supply": 25935, "tax": 2593, "total": 28528}, body["totals"]


def test_T9_screen_ledger(srv, pw):
    page = open_page(pw, srv)
    rows = page.query_selector_all('[data-testid="invoice-row"]')
    assert len(rows) == 7, "대장 행 %d개" % len(rows)
    r1 = page.query_selector('[data-testid="invoice-row"][data-no="%s"]' % NO(1))
    assert r1 is not None and r1.get_attribute("data-status") == "수정됨", "수정된 원본 행 상태가 아니다"
    mt = page.query_selector('[data-testid="month-total"]')
    assert mt is not None and 28528 in digits(mt.inner_text()), "month-total %r" % (mt.inner_text() if mt else None)
    page.close()
