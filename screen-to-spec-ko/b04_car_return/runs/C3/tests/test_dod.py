# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 2부 4편 — 반납 점검표 · 추가 요금 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users · cars · rentals · pre_damages .csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
고정 데이터의 시각은 **테스트를 돌리는 시각(지금)** 기준(반납 예정 = 지금 −2시간 · +3시간 …). 지연은 요청 본문의 returned_at 으로 정확히 준다.
서버 하나를 T1~T9 가 차례로 쓴다 — T6 의 반납 처리를 T7 이 전제로 한다.
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
from datetime import datetime, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상(부릉부릉렌터카는 가상 회사), 시각은 지금 기준 ──
NOW = datetime.now().replace(second=0, microsecond=0)
FMT = "%Y-%m-%d %H:%M"


def at_h(h):
    return (NOW + timedelta(hours=h)).strftime(FMT)


def plus(ts, minutes):
    return (datetime.strptime(ts, FMT) + timedelta(minutes=minutes)).strftime(FMT)


USERS = [("c1", "김고객", "customer"), ("c2", "이고객", "customer"), ("c3", "박고객", "customer"), ("c4", "최고객", "customer"), ("s1", "한직원", "staff")]
CARS = [("V-01", "12가 3456", "소형 SUV"), ("V-02", "34나 5678", "준중형"), ("V-03", "56다 7890", "경차"), ("V-04", "78라 1234", "승합")]
# rental_id, car_id, customer_id, out_at, due_at, out_fuel, out_km, status
RENTALS = [("R-1001", "V-01", "c1", at_h(-50), at_h(-2), 6, 12480, "out"),      # 반납 예정 2시간 지남 — 요금 계산(T3~T5 · T8)
           ("R-1002", "V-02", "c2", at_h(-20), at_h(3), 8, 30000, "out"),
           ("R-1003", "V-03", "c3", at_h(-4), at_h(27), 5, 8000, "out"),
           ("R-1004", "V-04", "c4", at_h(-72), at_h(-30), 7, 55000, "returned"),  # 이미 반납 완료(CSV 상태)
           ("R-1005", "V-02", "c1", at_h(-30), at_h(-1), 6, 20000, "out"),       # 반납 처리 대상(T6 · T7)
           ("R-1006", "V-03", "c2", at_h(-1), at_h(5), 3, 9000, "out")]
PRE_DAMAGES = [("R-1001", "앞범퍼"), ("R-1001", "휠"), ("R-1005", "뒷범퍼")]
DUE_1001 = RENTALS[0][4]
DUE_1005 = RENTALS[4][4]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("cars.csv", ["car_id", "plate", "model"], CARS),
              ("rentals.csv", ["rental_id", "car_id", "customer_id", "out_at", "due_at", "out_fuel", "out_km", "status"], RENTALS),
              ("pre_damages.csv", ["rental_id", "part"], PRE_DAMAGES)]
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


def body_of(user, returned_at, fuel, km, damages):
    b = {"user": user, "fuel": fuel, "km": km, "damages": damages}
    if returned_at is not None:
        b["returned_at"] = returned_at
    return b


def quote(s, rid, body):
    return http("POST", s.base + "/api/rentals/%s/quote" % rid, body)


def ret(s, rid, body):
    return http("POST", s.base + "/api/rentals/%s/return" % rid, body)


def rentals(s, viewer):
    st, body = http("GET", s.base + "/api/rentals?" + urllib.parse.urlencode({"viewer": viewer}))
    assert st == 200 and isinstance(body, list), ("GET /api/rentals", viewer, st, body)
    return body


def detail(s, rid, viewer):
    return http("GET", s.base + "/api/rentals/%s?" % rid + urllib.parse.urlencode({"viewer": viewer}))


def ok_quote(s, rid, body):
    st, b = quote(s, rid, body)
    assert st == 200 and isinstance(b, dict), ("미리보기 200", rid, body, st, b)
    return b


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


BASE_1001 = dict(fuel=6, km=12480, damages=[])     # R-1001 을 연료 · 거리 그대로, 손상 없이 — 지연만 보려고


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    pg = open_page(pw, srv)
    assert "반납" in pg.title() or "반납" in pg.inner_text("body")
    pg.close()


def test_T2_contract(srv):
    st, users = http("GET", srv.base + "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {(u, r) for u, _, r in USERS}, users
    mine = rentals(srv, "c1")
    assert [r["rental_id"] for r in mine] == ["R-1001", "R-1005"], ("고객은 자기 것만 · 반납 예정 순", [r["rental_id"] for r in mine])
    alls = rentals(srv, "s1")
    assert [r["rental_id"] for r in alls] == ["R-1004", "R-1001", "R-1005", "R-1002", "R-1006", "R-1003"], ("직원은 전부 · 반납 예정 순", [r["rental_id"] for r in alls])
    r1 = mine[0]
    assert set(r1["pre_damages"]) == {"앞범퍼", "휠"} and r1["plate"] == "12가 3456" and r1["status"] == "out" and int(r1["out_fuel"]) == 6, r1
    st, d = detail(srv, "R-1001", "c1")
    assert st == 200 and d["rental_id"] == "R-1001" and d.get("charges") is None, ("대여 중이면 charges null", st, d)


def test_T3_late_fee(srv):
    cases = [(plus(DUE_1001, 30), 30, 0), (plus(DUE_1001, 31), 31, 10000), (plus(DUE_1001, 150), 150, 30000),
             (plus(DUE_1001, 30 * 60), 1800, 80000), (plus(DUE_1001, -60), 0, 0)]
    for when, minutes, fee in cases:
        q = ok_quote(srv, "R-1001", body_of("s1", when, **BASE_1001))
        assert (q["late_minutes"], q["late_fee"]) == (minutes, fee), ("지연", when, "기대", minutes, fee, "응답", q)
        assert q["total"] == fee and q["fuel_fee"] == 0 and q["damage_fee"] == 0, q


def test_T4_fuel_fee(srv):
    when = plus(DUE_1001, 30)
    assert ok_quote(srv, "R-1001", body_of("s1", when, 4, 12480, []))["fuel_fee"] == 30000, "6칸 → 4칸은 2칸 × 15,000"
    assert ok_quote(srv, "R-1001", body_of("s1", when, 7, 12480, []))["fuel_fee"] == 0, "더 채워 와도 0"
    st, b = quote(srv, "R-1001", body_of("s1", when, 9, 12480, []))
    assert st == 400 and "연료" in b.get("detail", ""), ("연료 9칸은 400", st, b)


def test_T5_damage_fee(srv):
    when = plus(DUE_1001, 30)
    dm = [{"part": "뒷범퍼", "grade": "minor", "photos": 1}, {"part": "운전석문", "grade": "major", "photos": 2}, {"part": "보닛", "grade": "severe", "photos": 1}]
    q = ok_quote(srv, "R-1001", body_of("s1", when, 6, 12480, dm))
    assert q["damage_fee"] == 680000 and q["total"] == 680000, ("minor + major + severe", q)
    q = ok_quote(srv, "R-1001", body_of("s1", when, 6, 12480, [{"part": "앞범퍼", "grade": "minor", "photos": 1}]))
    assert q["damage_fee"] == 0 and len(q["damages"]) == 1 and q["damages"][0]["pre_existing"] is True and q["damages"][0]["fee"] == 0, ("대여 전 손상은 남기되 0원", q)
    st, b = quote(srv, "R-1001", body_of("s1", when, 6, 12480, [{"part": "뒷범퍼", "grade": "minor", "photos": 0}]))
    assert st == 400 and "사진" in b.get("detail", ""), ("사진 0장은 400", st, b)
    st, b = quote(srv, "R-1001", body_of("s1", when, 6, 12480, [{"part": "뒷범퍼", "grade": "minor", "photos": 1}, {"part": "뒷범퍼", "grade": "major", "photos": 1}]))
    assert st == 400 and "두 번" in b.get("detail", ""), ("같은 부위 두 번은 400", st, b)
    st, b = quote(srv, "R-1001", body_of("s1", when, 6, 12480, [{"part": "뒷범퍼", "grade": "big", "photos": 1}]))
    assert st == 400 and "등급" in b.get("detail", ""), ("등급 오타는 400", st, b)


def test_T6_return(srv):
    when = plus(DUE_1005, 100)          # 100분 늦음 → 시작된 2시간 → 20,000
    dm = [{"part": "뒷범퍼", "grade": "minor", "photos": 1}, {"part": "트렁크", "grade": "minor", "photos": 1}]   # 뒷범퍼는 대여 전 손상
    body = body_of("s1", when, 5, 20100, dm)
    q = ok_quote(srv, "R-1005", body)
    assert (q["late_fee"], q["fuel_fee"], q["damage_fee"], q["total"]) == (20000, 15000, 30000, 65000), q
    st, d = detail(srv, "R-1005", "s1")
    assert st == 200 and d["status"] == "out" and d.get("charges") is None, ("미리보기는 상태를 안 바꾼다", d)
    st, r = ret(srv, "R-1005", body)
    assert st == 201 and r["status"] == "returned" and r["total"] == 65000, ("반납 처리", st, r)
    st, d = detail(srv, "R-1005", "c1")
    assert st == 200 and d["status"] == "returned" and d["charges"]["total"] == 65000 and len(d["charges"]["damages"]) == 2, ("청구가 남는다", d)
    assert {x["part"]: x["pre_existing"] for x in d["charges"]["damages"]} == {"뒷범퍼": True, "트렁크": False}, d["charges"]["damages"]
    assert [x for x in rentals(srv, "c1") if x["rental_id"] == "R-1005"][0]["status"] == "returned"


def test_T7_state_and_time(srv):
    body = body_of("s1", plus(DUE_1005, 100), 5, 20100, [])
    st, b = ret(srv, "R-1005", body)
    assert st == 409 and "이미" in b.get("detail", ""), ("두 번째 반납은 409", st, b)
    st, b = quote(srv, "R-1005", body)
    assert st == 409, ("반납 완료 건의 미리보기도 409", st, b)
    st, b = quote(srv, "R-1004", body_of("s1", at_h(-29), 7, 55100, []))
    assert st == 409, ("CSV 에서 이미 반납 완료인 건도 409", st, b)
    st, b = quote(srv, "R-1001", body_of("s1", plus(RENTALS[0][3], -60), 6, 12480, []))
    assert st == 400 and "반납 시각" in b.get("detail", ""), ("대여 시각보다 앞선 반납 시각은 400", st, b)
    st, b = quote(srv, "R-1001", body_of("s1", plus(DUE_1001, 30), 6, 12000, []))
    assert st == 400 and "주행거리" in b.get("detail", ""), ("주행거리가 대여 때보다 적으면 400", st, b)


def test_T8_roles_and_reject_order(srv):
    when = plus(DUE_1001, 30)
    st, b = quote(srv, "R-1001", body_of("c1", when, **BASE_1001))
    assert st == 403, ("고객의 미리보기는 403", st, b)
    st, b = detail(srv, "R-1002", "c1")
    assert st == 403, ("고객이 남의 건 조회는 403", st, b)
    st, b = quote(srv, "R-9999", {})
    assert st == 400, ("본문에 user 없음 + 없는 건은 400 이 먼저", st, b)
    st, b = quote(srv, "R-9999", body_of("s1", when, **BASE_1001))
    assert st == 404, ("없는 건은 404", st, b)
    st, b = quote(srv, "R-1001", body_of("c1", when, 6, 1, []))
    assert st == 403, ("고객이 주행거리를 잘못 넣어도 403 이 먼저(대여 건을 찾아야 아는 400 보다)", st, b)
    st, b = quote(srv, "R-9999", body_of("s1", when, 9, 12480, []))
    assert st == 400, ("연료 9 + 없는 건이면 본문 400 이 먼저", st, b)


def test_T9_screen(srv, pw):
    pg = open_page(pw, srv)
    pg.select_option('[data-testid="user"]', "s1")
    pg.wait_for_timeout(1000)
    row = pg.query_selector('[data-testid="rental"][data-id="R-1001"]')
    assert row is not None, "R-1001 줄이 없다"
    row.click()
    pg.wait_for_timeout(800)
    for tid in ("fuel", "km", "add-damage", "quote", "pre-damage"):
        assert pg.query_selector('[data-testid="%s"]' % tid) is not None, "직원 점검표에 %s 가 없다" % tid
    pg.select_option('[data-testid="fuel"]', "4")
    pg.click('[data-testid="quote"]')
    pg.wait_for_timeout(1200)
    tot = pg.query_selector('[data-testid="fee-total"]')
    assert tot is not None and digits(tot.inner_text()), ("요금 상자에 합계 숫자가 없다", tot.inner_text() if tot else None)
    pg.select_option('[data-testid="user"]', "c1")
    pg.wait_for_timeout(1000)
    assert pg.query_selector('[data-testid="quote"]') is None and pg.query_selector('[data-testid="return"]') is None, "고객에게 미리보기 · 반납 처리 버튼이 보인다"
    pg.close()
