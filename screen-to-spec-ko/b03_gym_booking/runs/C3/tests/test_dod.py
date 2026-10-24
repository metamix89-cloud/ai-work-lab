# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 2부 3편 — 수업 예약 · 회원권 차감 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users · passes · slots · bookings .csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
고정 데이터의 시각은 **테스트를 돌리는 시각(지금)** 기준(지금 +1시간 · +5시간 · 어제 …). 서버 하나를 T1~T9 가 차례로 쓴다 — 앞 테스트의 예약 · 처리를 뒤 테스트가 전제로 한다.
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
from datetime import date, datetime, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상(으랏차차헬스는 가상 회사), 시각은 지금 기준 ──
NOW = datetime.now().replace(second=0, microsecond=0)


def at_h(h):
    """지금 + h 시간 (YYYY-MM-DD HH:MM)"""
    return (NOW + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M")


def day(n):
    return (NOW.date() + timedelta(days=n)).isoformat()


USERS = [("c1", "김회원", "member"), ("c2", "이회원", "member"), ("c3", "박회원", "member"),
         ("c4", "최회원", "member"), ("c5", "정회원", "member"), ("d1", "한데스크", "desk")]
# member_id, kind, total, used, expires_on
PASSES = [("c1", "PT 10회권", 10, 2, day(60)),      # 잔여 8
          ("c2", "PT 10회권", 10, 8, day(60)),      # 잔여 2 · 예약 중 1 → 가능 1
          ("c3", "PT 10회권", 10, 10, day(60)),     # 잔여 0
          ("c4", "PT 10회권", 10, 5, day(-1)),      # 어제 만료
          ("c5", "PT 20회권", 20, 4, day(60))]      # 최근 30일 노쇼 3회
# slot_id, starts_at, trainer, capacity
SLOTS = [("S-101", at_h(-26), "강코치", 4),                 # 어제 — 지난 수업(출석 · 노쇼 처리 대상)
         ("S-102", at_h(1), "강코치", 3),                   # 1시간 뒤 — 취소 마감 지남
         ("S-103", at_h(5), "오코치", 2),                   # 5시간 뒤 — 정원 2(가득)
         ("S-104", at_h(27), "오코치", 4),                  # 내일
         ("S-105", day(60) + " 18:00", "강코치", 4),        # 유효기간 당일
         ("S-106", day(61) + " 18:00", "강코치", 4),        # 유효기간 다음 날
         ("S-107", at_h(3), "오코치", 4),                   # 3시간 뒤 — 아직 시작 안 함
         ("S-108", day(-5) + " 18:00", "강코치", 4), ("S-109", day(-10) + " 18:00", "강코치", 4), ("S-110", day(-20) + " 18:00", "강코치", 4)]
# booking_id, slot_id, member_id, status
BOOKINGS = [("B-1001", "S-101", "c1", "booked"),      # 지난 수업, 미처리 → 데스크 출석(T6)
            ("B-1002", "S-101", "c2", "booked"),      # 지난 수업, 미처리 → 데스크 노쇼(T6)
            ("B-1003", "S-102", "c1", "booked"),      # 1시간 뒤 → 취소 409(T7)
            ("B-1004", "S-103", "c1", "booked"),      # 5시간 뒤 → 취소 200(T6)
            ("B-1005", "S-103", "c5", "booked"),      # S-103 정원 2 가득
            ("B-1006", "S-107", "c1", "booked"),      # 3시간 뒤 → 출석 처리 409(T7)
            ("B-1007", "S-101", "c4", "attended"),
            ("B-1008", "S-101", "c3", "cancelled"),
            ("B-1009", "S-108", "c5", "noshow"), ("B-1010", "S-109", "c5", "noshow"), ("B-1011", "S-110", "c5", "noshow"),
            ("B-1012", "S-101", "c5", "booked")]      # 지난 수업, 미처리 — 화면(T9) 데스크 버튼용


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("passes.csv", ["member_id", "kind", "total", "used", "expires_on"], PASSES),
              ("slots.csv", ["slot_id", "starts_at", "trainer", "capacity"], SLOTS),
              ("bookings.csv", ["booking_id", "slot_id", "member_id", "status"], BOOKINGS)]
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


def book(s, user, member, slot):
    return http("POST", s.base + "/api/bookings", {"user": user, "member_id": member, "slot_id": slot})


def act(s, bid, action, body):
    return http("POST", s.base + "/api/bookings/%s/%s" % (bid, action), body)


def pas(s, member):
    st, body = http("GET", s.base + "/api/passes/%s" % member)
    assert st == 200 and isinstance(body, dict), ("GET /api/passes", member, st, body)
    return body


def bookings(s, viewer):
    st, body = http("GET", s.base + "/api/bookings?" + urllib.parse.urlencode({"viewer": viewer}))
    assert st == 200 and isinstance(body, list), ("GET /api/bookings", viewer, st, body)
    return body


def slots(s):
    st, body = http("GET", s.base + "/api/slots")
    assert st == 200 and isinstance(body, list), ("GET /api/slots", st, body)
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
    assert "예약" in pg.title() or "예약" in pg.inner_text("body")
    pg.close()


def test_T2_contract(srv):
    st, users = http("GET", srv.base + "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {(u, r) for u, _, r in USERS}, users
    sl = {x["slot_id"]: x for x in slots(srv)}
    assert [x["slot_id"] for x in slots(srv)][:4] == ["S-110", "S-109", "S-108", "S-101"], ("시작 시각 순", [x["slot_id"] for x in slots(srv)][:4])
    assert (sl["S-103"]["booked"], sl["S-103"]["left"]) == (2, 0) and (sl["S-101"]["booked"], sl["S-101"]["left"]) == (3, 1), (sl["S-103"], sl["S-101"])
    p = pas(srv, "c2")
    assert (p["left"], p["held"], p["available"], p["expired"]) == (2, 1, 1, False), p
    assert pas(srv, "c4")["expired"] is True and pas(srv, "c1")["available"] == 4, (pas(srv, "c4"), pas(srv, "c1"))
    mine = bookings(srv, "c1")
    assert {b["member_id"] for b in mine} == {"c1"} and len(mine) == 4, ("회원은 자기 것만", mine)
    assert len(bookings(srv, "d1")) == len(BOOKINGS), "데스크는 전부"
    assert bookings(srv, "d1")[0]["slot_id"] == "S-110", "시작 시각 순"


def test_T3_available_count(srv):
    st, body = book(srv, "c2", "c2", "S-104")
    assert st == 201 and body["status"] == "booked", ("잔여 2 · 예약 중 1 → 한 번 더 된다", st, body)
    st, body = book(srv, "c2", "c2", "S-105")
    assert st == 409 and "예약 가능 횟수" in body.get("detail", ""), ("예약 중을 빼면 0 → 409", st, body)
    assert pas(srv, "c2")["available"] == 0
    st, body = book(srv, "c3", "c3", "S-104")
    assert st == 409, ("잔여 0 은 409", st, body)


def test_T4_expiry_and_past(srv):
    st, body = book(srv, "c4", "c4", "S-104")
    assert st == 409 and "유효기간" in body.get("detail", ""), ("만료 회원은 409", st, body)
    st, body = book(srv, "c1", "c1", "S-105")
    assert st == 201, ("유효기간 당일 수업은 된다", st, body)
    st, body = book(srv, "c1", "c1", "S-106")
    assert st == 409 and "유효기간" in body.get("detail", ""), ("유효기간 다음 날 수업은 409", st, body)
    st, body = book(srv, "c1", "c1", "S-101")
    assert st == 409 and "지난" in body.get("detail", ""), ("지난 수업은 409", st, body)


def test_T5_capacity_and_duplicate(srv):
    st, body = book(srv, "c1", "c1", "S-103")
    assert st == 409 and "정원" in body.get("detail", ""), ("정원 2 가득 → 409", st, body)
    st, body = book(srv, "c1", "c1", "S-104")
    assert st == 201, (st, body)
    st, body = book(srv, "c1", "c1", "S-104")
    assert st == 409 and "이미" in body.get("detail", ""), ("같은 수업 두 번은 409", st, body)


def test_T6_deduct_timing(srv):
    assert pas(srv, "c1")["used"] == 2, "예약해도 used 는 그대로"
    st, body = act(srv, "B-1001", "attend", {"user": "d1"})
    assert st == 200 and body["status"] == "attended", (st, body)
    assert pas(srv, "c1")["used"] == 3, "출석은 +1"
    st, body = act(srv, "B-1002", "noshow", {"user": "d1"})
    assert st == 200 and body["status"] == "noshow", (st, body)
    assert pas(srv, "c2")["used"] == 9, "노쇼도 +1"
    held = pas(srv, "c1")["held"]
    st, body = act(srv, "B-1004", "cancel", {"user": "c1"})
    assert st == 200 and body["status"] == "cancelled", ("5시간 뒤 수업 취소", st, body)
    p = pas(srv, "c1")
    assert p["used"] == 3 and p["held"] == held - 1, ("취소는 used 그대로, 예약 중만 준다", p)


def test_T7_cancel_deadline_and_state(srv):
    st, body = act(srv, "B-1003", "cancel", {"user": "c1"})
    assert st == 409 and "마감" in body.get("detail", ""), ("1시간 뒤 수업의 취소는 409", st, body)
    st, body = act(srv, "B-1006", "attend", {"user": "d1"})
    assert st == 409 and "시작" in body.get("detail", ""), ("아직 안 시작한 수업의 출석 처리는 409", st, body)
    st, body = act(srv, "B-1001", "cancel", {"user": "d1"})
    assert st == 409, ("이미 출석 처리한 예약의 취소는 409", st, body)


def test_T8_roles_and_reject_order(srv):
    st, body = book(srv, "c2", "c1", "S-104")
    assert st == 403, ("회원이 남의 예약을 만들면 403", st, body)
    st, body = act(srv, "B-1006", "attend", {"user": "c1"})
    assert st == 403, ("회원의 출석 처리는 403(아직 안 시작 409 보다 먼저)", st, body)
    st, body = act(srv, "B-9999", "cancel", {})
    assert st == 400, ("본문에 user 없음 + 없는 예약은 400 이 먼저", st, body)
    st, body = act(srv, "B-9999", "cancel", {"user": "d1"})
    assert st == 404, ("없는 예약은 404", st, body)
    st, body = act(srv, "B-1003", "cancel", {"user": "c2"})
    assert st == 403, ("회원이 남의 예약을 취소하면 403(마감 409 보다 먼저)", st, body)
    st, body = book(srv, "d1", "c5", "S-104")
    assert st == 409 and "노쇼" in body.get("detail", ""), ("최근 30일 노쇼 3회는 데스크가 대신해도 409", st, body)


def test_T9_screen(srv, pw):
    pg = open_page(pw, srv)
    left = pg.query_selector('[data-testid="pass-left"]')
    assert left is not None and digits(left.inner_text()) and pg.query_selector('[data-testid="pass-avail"]') is not None, "회원권 카드 숫자가 없다"
    assert pg.query_selector('[data-testid="act-attend"]') is None and pg.query_selector('[data-testid="act-noshow"]') is None, "회원에게 출석 · 노쇼 버튼이 보인다"
    pg.select_option('[data-testid="user"]', "d1")
    pg.wait_for_timeout(1200)
    row = pg.query_selector('[data-testid="booking"][data-id="B-1012"]')
    assert row is not None and row.query_selector('[data-testid="act-attend"]') is not None and row.query_selector('[data-testid="act-noshow"]') is not None, "데스크에게 지난 수업 예약 줄의 출석 · 노쇼 버튼이 없다"
    pg.select_option('[data-testid="member"]', "c3")
    pg.wait_for_timeout(600)
    slot = pg.query_selector('[data-testid="slot"][data-id="S-104"]')
    assert slot is not None, "S-104 줄이 없다"
    btn = slot.query_selector('[data-testid="book"]')
    if btn is not None:
        btn.click()
        pg.wait_for_timeout(1000)
        msg = pg.query_selector('[data-testid="message"]')
        assert msg is not None and "예약 가능 횟수가 없습니다" in msg.inner_text(), ("잔여 0 회원 예약 → 서버의 detail", msg.inner_text() if msg else None)
    else:
        avail = pg.query_selector('[data-testid="pass-avail"]')
        assert avail is not None and 0 in digits(avail.inner_text()), "잔여 0 회원을 골랐는데 예약 가능 0 이 안 보인다"
    pg.close()
