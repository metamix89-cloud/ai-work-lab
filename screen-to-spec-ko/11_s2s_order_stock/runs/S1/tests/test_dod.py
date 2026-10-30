# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 11편 — 주문 · 재고 백오피스 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users.csv · products.csv · orders.csv · order_lines.csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
테스트마다 서로 다른 주문 · 상품을 써서 섞이지 않는다(재고는 '전과 후의 차이' 로 본다).
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
import threading
import time
import urllib.error
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상 ─────────────────────────────────
USERS = [("u1", "김하나", "staff"), ("u2", "이두리", "staff"), ("m1", "박관리", "manager")]
PRODUCTS = [("P01", "두부 300g", 10), ("P02", "고추장 1kg", 2), ("P03", "냉동만두 1kg", 0),
            ("P04", "참기름 320ml", 3),                      # 동시 확정(T7) 대상
            ("P05", "김 선물세트", 5)]
ORDERS = [("O-1001", "한가람", "placed", "2026-10-24 09:00"),     # P01×3 · P02×2 → 확정(T3)
          ("O-1002", "두레상회", "placed", "2026-10-24 09:05"),   # P05×2 · P03×1 → 재고 부족(T3 · T9)
          ("O-1003", "마루식당", "confirmed", "2026-10-24 09:10"),  # P05×1 → 취소하면 되돌림(T4)
          ("O-1004", "새봄분식", "placed", "2026-10-24 09:15"),   # P01×1 → 취소해도 그대로(T4)
          ("O-1005", "다솜카페", "shipped", "2026-10-24 09:20"),  # P02×1 → 환불(T5)
          ("O-1006", "바른반찬", "placed", "2026-10-24 09:25"),   # P01×2 → 두 번 확정(T6)
          ("O-1007", "늘봄", "cancelled", "2026-10-24 09:30"),
          ("O-1008", "하늘빵집", "refunded", "2026-10-24 09:35"),
          ("O-1009", "소담", "placed", "2026-10-24 09:40"),       # 거부 순서(T8)
          ("O-1010", "온새미", "placed", "2026-10-24 09:45")]     # 화면(T9)
LINES = [("O-1001", "P01", 3), ("O-1001", "P02", 2), ("O-1002", "P05", 2), ("O-1002", "P03", 1),
         ("O-1003", "P05", 1), ("O-1004", "P01", 1), ("O-1005", "P02", 1), ("O-1006", "P01", 2),
         ("O-1007", "P01", 1), ("O-1008", "P05", 1), ("O-1009", "P05", 1), ("O-1010", "P01", 1)]
RACE = ["O-11%02d" % i for i in range(1, 9)]                       # P04×1 씩 8건, 재고 3
ORDERS += [(o, "동시주문 %d" % i, "placed", "2026-10-24 10:%02d" % i) for i, o in enumerate(RACE, 1)]
LINES += [(o, "P04", 1) for o in RACE]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("products.csv", ["product_id", "name", "stock"], PRODUCTS),
              ("orders.csv", ["order_id", "customer", "status", "ordered_at"], ORDERS),
              ("order_lines.csv", ["order_id", "product_id", "qty"], LINES)]
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


def act(s, oid, action, user="u1"):
    return http("POST", s.base + "/api/orders/%s/%s" % (oid, action), {"user": user} if user is not None else {})


def stocks(s):
    st, body = http("GET", s.base + "/api/products")
    assert st == 200, ("GET /api/products", st, body)
    return {p["product_id"]: p["stock"] for p in body}


def order(s, oid):
    st, body = http("GET", s.base + "/api/orders")
    assert st == 200, ("GET /api/orders", st, body)
    for o in body:
        if o["order_id"] == oid:
            return o
    return None


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
    page = pw.new_page(viewport={"width": 1400, "height": 900})
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
    assert "주문" in page.title() or "주문" in page.inner_text("body")
    page.close()


def test_T2_contract(srv):
    st, users = http("GET", srv.base + "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {("u1", "staff"), ("u2", "staff"), ("m1", "manager")}, (st, users)
    st, prods = http("GET", srv.base + "/api/products")
    assert st == 200 and len(prods) == 5 and {p["product_id"]: p["stock"] for p in prods}["P04"] == 3, (st, prods)
    st, orders = http("GET", srv.base + "/api/orders")
    assert st == 200 and len(orders) == len(ORDERS), (st, len(orders) if isinstance(orders, list) else orders)
    assert orders[0]["order_id"] == "O-1001", ("주문 시각 오래된 순", orders[0].get("order_id"))
    o = {x["order_id"]: x for x in orders}
    assert sorted((l["product_id"], l["qty"]) for l in o["O-1001"]["lines"]) == [("P01", 3), ("P02", 2)], o["O-1001"]
    assert {x["status"] for x in orders} == {"placed", "confirmed", "shipped", "cancelled", "refunded"}


def test_T3_confirm_all_or_nothing(srv):
    before = stocks(srv)
    st, body = act(srv, "O-1001", "confirm")
    assert st == 200, ("확정", st, body)
    after = stocks(srv)
    assert (before["P01"] - after["P01"], before["P02"] - after["P02"]) == (3, 2), ("줄마다 차감", before, after)
    assert order(srv, "O-1001")["status"] == "confirmed"
    before = stocks(srv)
    st, body = act(srv, "O-1002", "confirm")           # P05×2 는 있지만 P03×1 은 재고 0
    assert st == 409, ("한 줄이라도 모자라면 409", st, body)
    after = stocks(srv)
    assert after["P05"] == before["P05"] and after["P03"] == 0, ("모자라면 아무것도 바뀌지 않는다", before, after)
    assert order(srv, "O-1002")["status"] == "placed"


def test_T4_cancel_restores(srv):
    before = stocks(srv)
    st, body = act(srv, "O-1003", "cancel")           # 확정 → 취소: P05 +1
    assert st == 200, ("확정 주문 취소", st, body)
    assert stocks(srv)["P05"] - before["P05"] == 1, "확정 주문을 취소하면 재고가 돌아온다"
    before = stocks(srv)
    st, body = act(srv, "O-1004", "cancel")           # 접수 → 취소: 그대로
    assert st == 200, ("접수 주문 취소", st, body)
    assert stocks(srv)["P01"] == before["P01"], "접수 주문 취소는 재고 그대로"
    assert order(srv, "O-1004")["status"] == "cancelled"
    st, body = act(srv, "O-1005", "cancel")           # 출고 → 취소 불가
    assert st == 409, ("출고 주문의 취소는 409", st, body)


def test_T5_refund(srv):
    st, body = act(srv, "O-1005", "refund", user="u1")
    assert st == 403, ("직원의 환불은 403", st, body)
    assert order(srv, "O-1005")["status"] == "shipped"
    before = stocks(srv)
    st, body = act(srv, "O-1005", "refund", user="m1")
    assert st == 200, ("관리자의 환불", st, body)
    assert order(srv, "O-1005")["status"] == "refunded"
    assert stocks(srv) == before, "환불은 재고를 되돌리지 않는다"
    st, body = act(srv, "O-1004", "refund", user="m1")   # T4 에서 취소된 주문
    assert st == 409, ("취소 주문의 환불은 409", st, body)


def test_T6_transitions(srv):
    st, body = act(srv, "O-1006", "ship")
    assert st == 409, ("접수 주문의 출고는 409", st, body)
    before = stocks(srv)
    st, body = act(srv, "O-1006", "confirm")
    assert st == 200, (st, body)
    st, body = act(srv, "O-1006", "confirm")
    assert st == 409, ("두 번째 확정은 409", st, body)
    assert before["P01"] - stocks(srv)["P01"] == 2, "재고는 한 번만 준다"
    st, body = act(srv, "O-1006", "ship")
    assert st == 200 and order(srv, "O-1006")["status"] == "shipped", (st, body)


def test_T7_concurrent_confirm(srv):
    results = []
    gate = threading.Barrier(len(RACE))

    def go(oid):
        try:
            gate.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        try:
            results.append(act(srv, oid, "confirm", user="u2")[0])
        except Exception as e:
            results.append("ERR %s" % e)

    ts = [threading.Thread(target=go, args=(o,)) for o in RACE]
    [t.start() for t in ts]
    [t.join(timeout=30) for t in ts]
    ok = sum(1 for r in results if r == 200)
    no = sum(1 for r in results if r == 409)
    st = stocks(srv)
    assert (ok, no, st["P04"]) == (3, 5, 0), ("재고 3 에 동시 확정 8건 → 성공 3 · 409 5 · 재고 0", ok, no, st["P04"], results)


def test_T8_reject_order(srv):
    st, body = http("POST", srv.base + "/api/orders/O-9999/confirm", {})
    assert st == 400, ("본문에 user 없음 + 없는 주문은 400 이 먼저", st, body)
    st, body = act(srv, "O-9999", "confirm")
    assert st == 404, ("없는 주문은 404", st, body)
    st, body = act(srv, "O-1009", "confirm", user="nobody")
    assert st == 404, ("없는 사용자는 404", st, body)
    st, body = act(srv, "O-1009", "refund", user="u1")
    assert st == 403, ("직원이 접수 주문을 환불하면 권한(403)이 상태(409)보다 먼저", st, body)
    assert order(srv, "O-1009")["status"] == "placed"


def test_T9_screen(srv, pw):
    page = open_page(pw, srv)
    row = page.query_selector('[data-testid="order"][data-id="O-1010"]')
    assert row is not None and row.get_attribute("data-status") == "placed", "O-1010 줄(data-status=placed)이 없다"
    cell = page.query_selector('[data-testid="stock"][data-id="P01"]')
    assert cell is not None and digits(cell.inner_text()), "P01 재고 숫자가 없다"
    before = digits(cell.inner_text())[-1]
    btn = row.query_selector('[data-testid="act-confirm"]')
    assert btn is not None, "접수 주문에 확정 버튼이 없다"
    btn.click()
    page.wait_for_timeout(1200)
    row = page.query_selector('[data-testid="order"][data-id="O-1010"]')
    assert row is not None and row.get_attribute("data-status") == "confirmed", "확정 뒤 줄 상태가 confirmed 로 안 바뀐다"
    cell = page.query_selector('[data-testid="stock"][data-id="P01"]')
    assert digits(cell.inner_text())[-1] == before - 1, ("재고 숫자가 1 줄어야 한다", before, cell.inner_text())
    short = page.query_selector('[data-testid="order"][data-id="O-1002"] [data-testid="act-confirm"]')
    assert short is not None, "O-1002(접수)에 확정 버튼이 없다"
    short.click()
    page.wait_for_timeout(1200)
    msg = page.query_selector('[data-testid="message"]')
    assert msg is not None and "재고가 부족합니다" in msg.inner_text(), ("메시지 줄에 서버의 detail 이 안 보인다", msg.inner_text() if msg else None)
    page.close()
