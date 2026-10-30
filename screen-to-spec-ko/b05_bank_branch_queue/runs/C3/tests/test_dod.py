# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 2부 5편 — 방문 예약 · 대기 현황판 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users · counters · tickets .csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
시각은 오늘 날짜의 고정 시각을 본문 at 으로 준다. 서버 하나를 T1~T9 가 차례로 쓴다 — 앞 테스트의 호출 · 완료를 뒤 테스트가 전제로 한다.
개인정보 검사는 칸 이름이 아니라 **응답 글자 전체**에서 고정 데이터의 이름 · 전화번호 · 계좌번호를 찾는다.
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
from datetime import date

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상(두둑은행은 가상 회사), 전화번호는 가짜 010-0000-… ──
D = date.today().isoformat()


def at(hm):
    return "%s %s" % (D, hm)


USERS = [("t1", "한창구", "teller", "C1"), ("t2", "두창구", "teller", "C2"), ("t3", "세창구", "teller", "C3"), ("t4", "네창구", "teller", "C4"), ("m1", "오지점", "manager", "")]
COUNTERS = [("C1", "창구 1", "deposit"), ("C2", "창구 2", "deposit"), ("C3", "창구 3", "loan"), ("C4", "창구 4", "fx")]
# ticket_id, number, name, phone, account, service, reserved_at, arrived_at, status, counter_id, called_at
TICKETS = [("K-01", 101, "김민수", "010-0000-0001", "110-222-333001", "deposit", "", at("09:00"), "waiting", "", ""),
           ("K-02", 102, "이수", "010-0000-0002", "110-222-333002", "deposit", "", at("09:05"), "waiting", "", ""),
           ("K-03", 103, "남궁민수", "010-0000-0003", "110-222-333003", "loan", "", at("09:06"), "waiting", "", ""),
           ("K-04", 104, "박하늘", "010-0000-0004", "110-222-333004", "fx", "", at("09:07"), "waiting", "", ""),
           ("K-05", 105, "최예약", "010-0000-0005", "110-222-333005", "deposit", at("10:00"), "", "reserved", "", ""),
           ("K-06", 106, "정예약", "010-0000-0006", "110-222-333006", "deposit", at("10:00"), "", "reserved", "", ""),
           ("K-07", 107, "강예약", "010-0000-0007", "110-222-333007", "deposit", at("10:00"), "", "reserved", "", ""),
           ("K-08", 108, "조예약", "010-0000-0008", "110-222-333008", "loan", at("10:00"), "", "reserved", "", ""),
           ("K-09", 109, "윤완료", "010-0000-0009", "110-222-333009", "deposit", "", at("08:50"), "done", "C1", at("08:55")),
           ("K-10", 110, "서보류", "010-0000-0010", "110-222-333010", "loan", "", at("08:51"), "held", "C3", at("08:56"))]
FULL_NAMES = [t[2] for t in TICKETS]
PHONES = [t[3] for t in TICKETS]
ACCOUNTS = [t[4] for t in TICKETS]
NEW_PHONE, NEW_ACCOUNT = "010-0000-0099", "110-222-333099"
SERVICE_WORDS = ["deposit", "loan", '"fx"', "예금", "대출", "외환"]


def pii_in(text):
    """응답 글자 전체에서 고정 데이터의 개인정보를 찾는다 — 칸 이름에 기대지 않는다"""
    return [x for x in FULL_NAMES + PHONES + ACCOUNTS + [NEW_PHONE, NEW_ACCOUNT, "새손님"] if x in text]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role", "counter_id"], USERS),
              ("counters.csv", ["counter_id", "name", "service"], COUNTERS),
              ("tickets.csv", ["ticket_id", "number", "name", "phone", "account", "service", "reserved_at", "arrived_at", "status", "counter_id", "called_at"], TICKETS)]
    for name, header, rows in tables:
        with open(os.path.join(seed, name), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)


def restore_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(bak):
        for _ in range(10):      # 윈도우: 죽은 서버가 파일을 놓기 전에 지우면 실패한다 — 잠깐씩 다시 시도
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
        if not os.path.exists(p) or os.sep + "tests" + os.sep in p or "seed" in os.path.relpath(p, APP) or "_grader" in p:
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
        # 서버 출력은 파일로 받는다. PIPE 로 받고 읽지 않으면 접속 로그가 버퍼를 채워 서버가 멈춘다
        self.logf = tempfile.TemporaryFile()
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", self.target, "--port", str(self.port)],
                                     cwd=APP, env=env, stdout=self.logf, stderr=subprocess.STDOUT)
        for _ in range(60):
            if self.proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(self.base + "/", timeout=1)
                return self
            except urllib.error.HTTPError:
                return self
            except Exception:
                time.sleep(0.5)
        self.stop()
        pytest.fail("서버가 30초 안에 뜨지 않음: %s\n%s" % (self.target, self.log[-1500:]))

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
    """(상태, JSON 또는 글자, 원문 글자)"""
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
        j = json.loads(raw) if raw else None
    except ValueError:
        j = raw
    text = raw
    if j is not None and not isinstance(j, str):
        text = json.dumps(j, ensure_ascii=False)   # \uXXXX 로 내보내도 찾도록
    return status, j, text


def get(s, path):
    return http("GET", s.base + path)


def post(s, path, body):
    return http("POST", s.base + path, body)


def nxt(s, counter, user, when):
    return post(s, "/api/counters/%s/next" % counter, {"user": user, "at": at(when)})


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


def open_page(pw, s, path="/"):
    pg = pw.new_page(viewport={"width": 1400, "height": 900})
    responses = []

    def keep(r):
        try:
            responses.append(r.text())
        except Exception:
            pass
    pg.on("response", keep)
    try:
        pg.goto(s.base + path, wait_until="load", timeout=15000)
        pg.wait_for_timeout(1500)
    except Exception as e:
        pg.close()
        pytest.fail("화면이 열리지 않음: %s" % str(e)[:200])
    return pg, responses


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    pg, _ = open_page(pw, srv)
    assert "대기" in pg.title() or "대기" in pg.inner_text("body")
    pg.close()


def test_T2_contract(srv):
    st, users, _ = get(srv, "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {(u, r) for u, _, r, _ in USERS}, users
    assert [u for u in users if u["user_id"] == "t3"][0]["counter_id"] == "C3", users
    st, b, raw = post(srv, "/api/tickets", {"name": "새손님", "phone": NEW_PHONE, "account": NEW_ACCOUNT, "service": "fx", "at": at("09:30")})
    assert st == 201 and b["number"] == 111 and b["status"] == "waiting" and b.get("ticket_id"), ("번호표", st, b)
    assert not pii_in(raw), ("번호표 응답에 이름 · 전화번호 · 계좌번호가 있다", raw)
    st, b, _ = post(srv, "/api/tickets", {"name": "새예약", "phone": "010-0000-0098", "account": "110-222-333098", "service": "fx", "reserved_at": at("15:00"), "at": at("09:31")})
    assert st == 201 and b["number"] == 112 and b["status"] == "reserved", ("예약", st, b)
    st, b, _ = post(srv, "/api/tickets", {"name": "오타", "phone": "010-0000-0097", "account": "1", "service": "insurance"})
    assert st == 400 and "업무" in b.get("detail", ""), ("없는 업무는 400", st, b)
    st, b, _ = post(srv, "/api/tickets", {"name": "오타", "phone": "12345", "account": "1", "service": "fx"})
    assert st == 400 and "전화번호" in b.get("detail", ""), ("전화번호 형식은 400", st, b)


def test_T3_board_hides(srv):
    st, b, raw = get(srv, "/api/board")
    assert st == 200 and isinstance(b, dict), ("GET /api/board", st, b)
    assert not pii_in(raw), ("대기 화면 응답에 개인정보", pii_in(raw))
    words = [w for w in SERVICE_WORDS if w in raw]
    assert not words, ("대기 화면 응답에 업무 종류", words)
    assert b["serving"] == [], b["serving"]
    assert [w["number"] for w in b["waiting"]] == [101, 102, 103, 104, 111], ("대기 중만 · 번호 순 — 예약 · 완료 · 보류 없음", b["waiting"])
    masks = {w["number"]: w["masked_name"] for w in b["waiting"]}
    assert masks[101] == "김*수" and masks[102] == "이*" and masks[103] == "남**수", ("가린 이름", masks)


def test_T4_reservation_window(srv):
    cases = [("K-05", "10:10", True), ("K-06", "10:11", False), ("K-07", "09:50", True), ("K-08", "09:49", False)]
    for tid, when, want in cases:
        st, b, _ = post(srv, "/api/tickets/%s/checkin" % tid, {"at": at(when)})
        assert st == 200 and b["priority"] is want and b["status"] == "waiting", ("도착", tid, when, "기대", want, st, b)
    st, b, _ = post(srv, "/api/tickets/K-05/checkin", {"at": at("10:12")})
    assert st == 409, ("다시 도착 처리는 409", st, b)
    st, b, _ = post(srv, "/api/tickets/K-01/checkin", {"at": at("10:12")})
    assert st == 409, ("현장 번호표 도착 처리는 409", st, b)


def test_T5_order_and_counters(srv):
    st, q, raw = get(srv, "/api/counters/C1/queue?viewer=t1")
    assert st == 200 and [x["ticket_id"] for x in q] == ["K-07", "K-05", "K-01", "K-02", "K-06"], ("예금 줄: 우선(도착 순) → 일반(도착 순)", st, q)
    assert not pii_in(raw), ("대기 줄 응답에 개인정보", pii_in(raw))
    assert q[0]["masked_name"] == "강*약" and q[0]["priority"] is True and q[2]["priority"] is False, q
    st, b, _ = nxt(srv, "C1", "t1", "10:20")
    assert st == 200 and b["called"]["ticket_id"] == "K-07" and b["called"]["counter_id"] == "C1" and b["held"] is None, ("C1 은 우선 고객부터", st, b)
    st, b, _ = nxt(srv, "C2", "t2", "10:20")
    assert st == 200 and b["called"]["ticket_id"] == "K-05", ("C2 는 예금 줄의 다음", st, b)
    st, b, _ = nxt(srv, "C3", "t3", "10:20")
    assert st == 200 and b["called"]["ticket_id"] == "K-03", ("C3 은 대출 고객만", st, b)
    st, b, raw = get(srv, "/api/board")
    assert {(x["number"], x["counter_id"]) for x in b["serving"]} == {(107, "C1"), (105, "C2"), (103, "C3")}, b["serving"]
    assert not pii_in(raw), ("호출 뒤에도 대기 화면에 개인정보 없음", pii_in(raw))


def test_T6_hold_and_complete(srv):
    st, b, _ = nxt(srv, "C1", "t1", "10:22")
    assert st == 409, ("호출 뒤 2분은 409", st, b)
    st, b, _ = nxt(srv, "C1", "t1", "10:23")
    assert st == 200 and b["held"] == "K-07" and b["called"]["ticket_id"] == "K-01", ("3분이면 앞 고객 보류 + 다음 호출", st, b)
    st, board, _ = get(srv, "/api/board")
    assert 107 not in [x["number"] for x in board["serving"]] + [x["number"] for x in board["waiting"]], ("보류 고객은 대기 화면에서 사라짐", board)
    st, b, _ = post(srv, "/api/tickets/K-05/complete", {"user": "t2", "at": at("10:21")})
    assert st == 200 and b["status"] == "done", ("완료", st, b)
    st, b, _ = nxt(srv, "C2", "t2", "10:21")
    assert st == 200 and b["called"]["ticket_id"] == "K-02" and b["held"] is None, ("완료 뒤엔 바로 다음 호출", st, b)
    st, b, _ = post(srv, "/api/tickets/K-07/complete", {"user": "t1", "at": at("10:24")})
    assert st == 409, ("이미 보류한 건 다시 완료는 409", st, b)


def test_T7_roles(srv):
    st, d, raw = get(srv, "/api/tickets/K-01?viewer=t1")
    assert st == 200 and d["name"] == "김민수" and d["phone"] == "010-0000-0001" and str(d["account_last4"]) == "3001", ("호출한 창구 직원은 상세", st, d)
    assert "110-222-333001" not in raw, ("상세에도 계좌번호 전체는 없다", raw)
    for viewer, tid, why in [("t2", "K-01", "다른 창구 직원"), ("m1", "K-01", "지점장"), ("t1", "K-06", "호출 전 고객"), ("t3", "K-01", "다른 업무 창구 직원")]:
        st, d, _ = get(srv, "/api/tickets/%s?viewer=%s" % (tid, viewer))
        assert st == 403, (why + " 은 403", st, d)
    st, d, _ = get(srv, "/api/counters/C3/queue?viewer=t1")
    assert st == 403, ("다른 창구 대기 줄은 403", st, d)
    st, d, _ = get(srv, "/api/counters/C1/queue?viewer=m1")
    assert st == 403, ("지점장도 대기 줄은 403", st, d)
    st, d, _ = nxt(srv, "C3", "t1", "10:40")
    assert st == 403, ("다른 창구 호출은 403", st, d)
    st, d, _ = nxt(srv, "C1", "m1", "10:40")
    assert st == 403, ("지점장 호출은 403", st, d)
    st, d, _ = post(srv, "/api/tickets/K-03/complete", {"user": "t1", "at": at("10:40")})
    assert st == 403, ("다른 창구 고객 완료는 403", st, d)


def test_T8_manager_and_reject_order(srv):
    st, s, raw = get(srv, "/api/manager/summary?viewer=m1")
    assert st == 200, ("지점장 현황", st, s)
    assert s["waiting"] == {"deposit": 1, "loan": 1, "fx": 2} and s["held"] == 2 and s["done"] == 2, ("대기 · 보류 · 완료 수", s)
    assert not pii_in(raw), ("지점장 현황에 개인정보", pii_in(raw))
    assert "*" not in raw, ("지점장 현황엔 가린 이름도 없다", raw)
    st, b, _ = get(srv, "/api/manager/summary?viewer=t1")
    assert st == 403, ("직원은 지점장 현황 403", st, b)
    st, b, _ = post(srv, "/api/counters/C9/next", {})
    assert st == 400, ("본문에 user 없음 + 없는 창구는 400 이 먼저", st, b)
    st, b, _ = nxt(srv, "C9", "t1", "10:50")
    assert st == 404, ("없는 창구는 404", st, b)
    st, b, _ = get(srv, "/api/tickets/K-99?viewer=t1")
    assert st == 404, ("없는 번호표는 404", st, b)
    st, b, _ = get(srv, "/api/tickets/K-01")
    assert st == 400, ("viewer 없음은 400", st, b)
    # 줄 비우기: C2 가 K-02 완료 → K-06 호출 · 완료 → 줄이 비면 called null
    post(srv, "/api/tickets/K-02/complete", {"user": "t2", "at": at("10:50")})
    st, b, _ = nxt(srv, "C2", "t2", "10:50")
    assert st == 200 and b["called"]["ticket_id"] == "K-06", ("마지막 예금 고객", st, b)
    post(srv, "/api/tickets/K-06/complete", {"user": "t2", "at": at("10:51")})
    st, b, _ = nxt(srv, "C2", "t2", "10:51")
    assert st == 200 and b["called"] is None, ("줄이 비면 called null", st, b)


def test_T9_screens(srv, pw):
    pg, responses = open_page(pw, srv, "/board")
    text = pg.inner_text("body")
    assert not pii_in(text), ("대기 화면 글자에 개인정보", pii_in(text))
    assert "김*수" in text, ("가린 이름이 보여야 한다 (호출 중인 K-01)", text[:300])
    for tid in ("serving", "waiting"):
        assert pg.query_selector('[data-testid="%s"]' % tid) is not None, "대기 화면에 %s 가 없다" % tid
    leaks = sorted({x for r in responses for x in pii_in(r)})
    assert not leaks, ("대기 화면이 받은 응답에 개인정보", leaks)
    pg.close()
    pg, _ = open_page(pw, srv, "/")
    pg.select_option('[data-testid="user"]', "t4")
    pg.wait_for_timeout(1000)
    row = pg.query_selector('[data-testid="ticket"][data-id="K-04"]')
    assert row is not None, "C4 대기 줄에 K-04 가 없다"
    pg.click('[data-testid="next"]')
    pg.wait_for_timeout(1200)
    nm = pg.query_selector('[data-testid="detail-name"]')
    assert nm is not None and "박하늘" in nm.inner_text(), ("호출한 고객 상세에 이름 전체", nm.inner_text() if nm else None)
    assert pg.query_selector('[data-testid="complete"]') is not None, "완료 버튼이 없다"
    pg.select_option('[data-testid="user"]', "m1")
    pg.wait_for_timeout(1000)
    assert pg.query_selector('[data-testid="next"]') is None, "지점장에게 호출 버튼이 보인다"
    assert pg.query_selector('[data-testid="summary"]') is not None, "지점장 현황 상자가 없다"
    assert not pg.query_selector('[data-testid="detail-name"]'), "지점장에게 고객 상세가 보인다"
    pg.close()
