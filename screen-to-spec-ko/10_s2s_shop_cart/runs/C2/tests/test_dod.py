# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 10편 — 소호 쇼핑몰 상품 목록 · 장바구니 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/products.csv · seed/options.csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
테스트마다 새 장바구니를 만들어 서로 섞이지 않는다.
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

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상 ─────────────────────────────────
PRODUCTS = [("P01", "두부 300g", 1500, "", 50, 10),
            ("P02", "고추장", 9000, 7500, 20, 5),
            ("P03", "냉동만두 1kg", 8900, "", 0, 10),          # 품절
            ("P04", "김 선물세트", 25000, 23000, 3, 5),         # 재고 3 < 한도 5
            ("P05", "참기름 320ml", 12000, "", 30, 2)]          # 한도 2
OPTIONS = [("P02-500", "P02", "500g", 0), ("P02-1K", "P02", "1kg", 6000)]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("products.csv", ["product_id", "name", "price", "sale_price", "stock", "max_per_order"], PRODUCTS),
              ("options.csv", ["option_id", "product_id", "label", "extra"], OPTIONS)]
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


def new_cart(s):
    st, body = http("POST", s.base + "/api/carts")
    assert st in (200, 201) and body and body.get("cart_id"), ("장바구니를 못 만듦", st, body)
    return body["cart_id"]


def add(s, cid, pid, qty, opt=None):
    body = {"product_id": pid, "qty": qty}
    if opt is not None:
        body["option_id"] = opt
    return http("POST", s.base + "/api/carts/%s/items" % cid, body)


def cart(s, cid):
    st, body = http("GET", s.base + "/api/carts/%s" % cid)
    assert st == 200, ("GET cart", st, body)
    return body


def item_of(c, pid, opt=None):
    for it in c["items"]:
        if it["product_id"] == pid and (opt is None or it.get("option_id") == opt):
            return it
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
    assert "장바구니" in page.title() or "장바구니" in page.inner_text("body")
    page.close()


def test_T2_products_contract(srv):
    st, body = http("GET", srv.base + "/api/products")
    assert st == 200 and len(body) == 5, (st, body)
    p = {x["product_id"]: x for x in body}
    assert p["P03"]["sold_out"] is True and p["P01"]["sold_out"] is False
    assert p["P01"]["sale_price"] is None and p["P02"]["sale_price"] == 7500, (p["P01"]["sale_price"], p["P02"]["sale_price"])
    assert sorted(o["option_id"] for o in p["P02"]["options"]) == ["P02-1K", "P02-500"]
    assert p["P01"]["options"] == []


def test_T3_sold_out_rejected(srv):
    cid = new_cart(srv)
    st, body = add(srv, cid, "P03", 1)
    assert st == 409, ("품절은 409", st, body)
    assert cart(srv, cid)["items"] == []


def test_T4_options_and_unit_price(srv):
    cid = new_cart(srv)
    st, body = add(srv, cid, "P02", 1)
    assert st == 400, ("옵션 있는 상품에 옵션 없음은 400", st, body)
    st, body = add(srv, cid, "P01", 1, opt="P02-1K")
    assert st == 400, ("옵션 없는 상품에 옵션은 400", st, body)
    st, body = add(srv, cid, "P02", 1, opt="P02-1K")
    assert st in (200, 201), (st, body)
    it = item_of(cart(srv, cid), "P02", "P02-1K")
    assert it and it["unit_price"] == 13500, ("단가 = 할인가 7,500 + 추가금 6,000", it)


def test_T5_quantity_limit(srv):
    cid = new_cart(srv)
    st, body = add(srv, cid, "P04", 4)
    assert st == 409, ("재고 3 인데 4개는 409", st, body)
    st, body = add(srv, cid, "P04", 3)
    assert st in (200, 201), (st, body)
    st, body = add(srv, cid, "P05", 2)
    assert st in (200, 201), (st, body)
    st, body = add(srv, cid, "P05", 1)
    assert st == 409, ("한도 2 를 넘는 추가는 409", st, body)
    assert item_of(cart(srv, cid), "P05")["qty"] == 2
    cid2 = new_cart(srv)
    st, body = add(srv, cid2, "P02", 3, opt="P02-500")
    assert st in (200, 201), (st, body)
    st, body = add(srv, cid2, "P02", 3, opt="P02-1K")
    assert st == 409, ("같은 상품의 다른 옵션도 합쳐서 한도 5", st, body)


def test_T6_shipping_boundary(srv):
    cid = new_cart(srv)
    st, _ = add(srv, cid, "P02", 2, opt="P02-1K")    # 13,500 × 2 = 27,000
    assert st in (200, 201)
    st, _ = add(srv, cid, "P01", 1)                  # 1,500
    assert st in (200, 201)
    c = cart(srv, cid)
    assert (c["subtotal"], c["shipping"], c["total"]) == (28500, 3000, 31500), (c["subtotal"], c["shipping"], c["total"])
    it = item_of(c, "P01")
    st, c = http("PUT", srv.base + "/api/carts/%s/items/%s" % (cid, it["item_id"]), {"qty": 2})
    assert st == 200, (st, c)
    c = cart(srv, cid)
    assert (c["subtotal"], c["shipping"], c["total"]) == (30000, 0, 30000), ("30,000 은 무료", c["subtotal"], c["shipping"], c["total"])


def test_T7_update_qty(srv):
    cid = new_cart(srv)
    add(srv, cid, "P05", 1)
    add(srv, cid, "P01", 1)
    c = cart(srv, cid)
    it = item_of(c, "P05")
    st, _ = http("PUT", srv.base + "/api/carts/%s/items/%s" % (cid, it["item_id"]), {"qty": 3})
    assert st == 409, ("한도 2 를 넘게 바꾸면 409", st)
    st, _ = http("PUT", srv.base + "/api/carts/%s/items/%s" % (cid, it["item_id"]), {"qty": 0})
    assert st == 200, st
    c = cart(srv, cid)
    assert item_of(c, "P05") is None and item_of(c, "P01") is not None, "수량 0 이면 그 줄만 빠진다"
    st, _ = http("PUT", srv.base + "/api/carts/%s/items/no-such-item" % cid, {"qty": 1})
    assert st == 404, ("없는 줄은 404", st)


def test_T8_reject_order(srv):
    st, body = http("POST", srv.base + "/api/carts/no-such-cart/items", {"product_id": "P01", "qty": 0})
    assert st == 400, ("없는 장바구니 + 잘못된 수량은 400 이 먼저", st, body)
    st, body = http("POST", srv.base + "/api/carts/no-such-cart/items", {"product_id": "P01", "qty": 1})
    assert st == 404, ("없는 장바구니 + 올바른 본문은 404", st, body)
    cid = new_cart(srv)
    st, body = add(srv, cid, "P99", 1)
    assert st == 404, ("없는 상품은 404", st, body)


def test_T9_screen(srv, pw):
    page = open_page(pw, srv)
    sold = page.query_selector('[data-testid="product"][data-id="P03"]')
    assert sold is not None and sold.get_attribute("data-soldout") == "1", "품절 카드 표시가 없다"
    btn = sold.query_selector('[data-testid="add-btn"]')
    assert btn is None or btn.is_disabled(), "품절 카드의 담기가 막혀 있지 않다"
    sale = page.query_selector('[data-testid="product"][data-id="P02"]')
    lp, sp = sale.query_selector('[data-testid="list-price"]'), sale.query_selector('[data-testid="sale-price"]')
    assert lp is not None and sp is not None and 9000 in digits(lp.inner_text()) and 7500 in digits(sp.inner_text()), "정가 · 할인가가 따로 안 보인다"
    p01 = page.query_selector('[data-testid="product"][data-id="P01"]')
    p01.query_selector('[data-testid="add-btn"]').click()
    page.wait_for_timeout(1200)
    tot = page.query_selector('[data-testid="total"]')
    assert tot is not None and 4500 in digits(tot.inner_text()), "1,500원 상품 + 배송비 3,000 = 총액 4,500 이 안 보인다: %r" % (tot.inner_text() if tot else None)
    page.close()
