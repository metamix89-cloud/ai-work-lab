# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 4편 — 당직 순번표 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/staff.csv · seed/unavailable.csv · seed/roster.csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
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
MONTH = "2026-11"

# ── 고정 데이터 (정답을 아는 값) ────────────────────────────────────────────
STAFF = [("김민수", "선임"), ("박지연", "일반"), ("이서준", "일반"), ("최유나", "선임"), ("정하늘", "일반"), ("한도윤", "일반")]
NAMES = [s[0] for s in STAFF]
UNAVAILABLE = [("박지연", "2026-11-03", "휴가"), ("박지연", "2026-11-04", "휴가"), ("박지연", "2026-11-05", "휴가"),
               ("박지연", "2026-11-06", "휴가"), ("박지연", "2026-11-07", "휴가"), ("이서준", "2026-11-15", "교육"),
               ("정하늘", "2026-11-21", "교육"), ("한도윤", "2026-11-22", "병가")]
# 지난달(2026-10) 순번: 마지막 날 10-31 은 김민수 → 11-01 은 김민수가 아니어야 한다 (R3 경계)
PREV = [("2026-10-%02d" % d, NAMES[(d - 1) % 6], 1) for d in range(1, 32)]
assert PREV[-1][1] == "김민수"
DAYS = [("2026-11-%02d" % d) for d in range(1, 31)]
WEEKENDS = {d for d in DAYS if dt.date.fromisoformat(d).weekday() >= 5}   # 토 · 일 9일


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("staff.csv", ["name", "grade"], STAFF),
              ("unavailable.csv", ["name", "date", "reason"], UNAVAILABLE),
              ("roster.csv", ["date", "name", "confirmed"], PREV)]
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
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                out = self.proc.communicate(timeout=5)[0]
                self.log = (out or b"").decode("utf-8", "ignore")
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


@pytest.fixture(scope="module")
def roster(srv):
    """생성 한 번 → {date: name}. 뒤 테스트들이 같은 순번을 본다."""
    st, body = http("POST", srv.base + "/api/roster/generate", {"month": MONTH}, timeout=20)
    assert st == 200, ("생성이 %s" % st, body)
    return get_roster(srv)


def get_roster(s):
    st, body = http("GET", s.base + "/api/roster?month=" + MONTH)
    assert st == 200, "GET /api/roster 가 %s" % st
    return {d["date"]: d["name"] for d in body["days"]}


def open_page(pw, s):
    page = pw.new_page(viewport={"width": 1400, "height": 900})
    try:
        page.goto(s.base + "/", wait_until="load", timeout=15000)
        page.wait_for_timeout(1500)
    except Exception as e:
        page.close()
        pytest.fail("화면이 열리지 않음: %s" % str(e)[:200])
    return page


def counts(r):
    total = {n: 0 for n in NAMES}
    wk = {n: 0 for n in NAMES}
    for d, n in r.items():
        if n in total:
            total[n] += 1
            if d in WEEKENDS:
                wk[n] += 1
    return total, wk


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "당직" in page.title() or "당직" in page.inner_text("body")
    page.close()


def test_T2_every_day_has_exactly_one(roster):
    assert sorted(roster) == DAYS, "그 달의 모든 날이 있어야 한다 (30일)"
    assert all(roster[d] in NAMES for d in DAYS), "빈 날 또는 모르는 이름: %s" % [(d, roster[d]) for d in DAYS if roster[d] not in NAMES]


def test_T3_unavailable_days_respected(roster):
    bad = [(n, d) for n, d, _ in UNAVAILABLE if roster.get(d) == n]
    assert not bad, "제외일에 배정됨: %s" % bad


def test_T4_no_consecutive_including_previous_month(roster):
    prev = "김민수"   # 10-31
    for d in DAYS:
        assert roster[d] != prev, "연속 당직: %s 전날과 같은 %s" % (d, prev)
        prev = roster[d]


def test_T5_total_fair(roster):
    total, _ = counts(roster)
    assert max(total.values()) - min(total.values()) <= 1, total


def test_T6_weekend_fair(roster):
    _, wk = counts(roster)
    assert max(wk.values()) - min(wk.values()) <= 1, wk


def find_swap(r, valid=True):
    """교환해도 R2 · R3 을 어기지 않는(또는 어기는) 두 날짜를 찾는다.
    교환 '뒤' 의 이웃으로 판단한다. 이웃한 두 날(하루 차이)은 판단이 헷갈리기 쉬워 후보에서 뺀다(C2 가 지적한 모호함, 2026-10-24)."""
    unav = {(n, d) for n, d, _ in UNAVAILABLE}

    def ok(after_swap, d):
        name = after_swap[d]
        i = DAYS.index(d)
        before = after_swap[DAYS[i - 1]] if i > 0 else "김민수"
        nxt = after_swap[DAYS[i + 1]] if i < len(DAYS) - 1 else None
        return (name, d) not in unav and name != before and name != nxt

    for a in DAYS:
        for b in DAYS:
            if a >= b or r[a] == r[b] or abs(DAYS.index(a) - DAYS.index(b)) == 1:
                continue
            new = dict(r)
            new[a], new[b] = r[b], r[a]
            good = ok(new, a) and ok(new, b)
            if good == valid:
                return a, b
    return None


def test_T7_swap_within_rules(srv, roster):
    pair = find_swap(roster, valid=True)
    assert pair, "규칙 안에서 바꿀 수 있는 두 날이 없다(순번이 이상하다)"
    a, b = pair
    st, body = http("POST", srv.base + "/api/roster/swap", {"date_a": a, "date_b": b})
    assert st == 200, (st, body)
    r2 = get_roster(srv)
    assert r2[a] == roster[b] and r2[b] == roster[a], "달력이 바뀌지 않았다"
    bad = find_swap(r2, valid=False)
    assert bad, "규칙을 어기는 교환 쌍을 못 찾음"
    st, body = http("POST", srv.base + "/api/roster/swap", {"date_a": bad[0], "date_b": bad[1]})
    assert st == 409, ("연속 또는 제외일을 만드는 교환은 409", st, body)
    assert get_roster(srv) == r2, "409 인데 달력이 바뀌었다"
    st, body = http("POST", srv.base + "/api/roster/swap", {"date_a": a, "date_b": a})
    assert st == 400, ("같은 날짜 교환은 400", st, body)


def test_T8_confirm_locks_generate_not_swap(srv, roster):
    st, body = http("POST", srv.base + "/api/roster/confirm", {"month": MONTH})
    assert st == 200, (st, body)
    st, body = http("POST", srv.base + "/api/roster/generate", {"month": MONTH}, timeout=20)
    assert st == 409, ("확정 뒤 재생성은 409", st, body)
    r = get_roster(srv)
    pair = find_swap(r, valid=True)
    assert pair
    st, body = http("POST", srv.base + "/api/roster/swap", {"date_a": pair[0], "date_b": pair[1]})
    assert st == 200, ("확정 뒤 바꾸기는 200", st, body)


def test_T9_screen_days_and_stats(srv, roster, pw):
    page = open_page(pw, srv)
    m = page.query_selector('[data-testid="month"]')
    if m and m.evaluate("e => e.tagName.toLowerCase()") in ("input", "select"):
        try:
            m.fill(MONTH) if m.evaluate("e => e.tagName.toLowerCase()") == "input" else m.select_option(MONTH)
            page.wait_for_timeout(800)
        except Exception:
            pass
    days = page.query_selector_all('[data-testid="day"]')
    named = [d for d in days if (d.get_attribute("data-date") or "").startswith(MONTH) and d.get_attribute("data-name")]
    assert len(named) == 30, "이름이 있는 day 칸 %d (기대 30)" % len(named)
    rows = page.query_selector_all('[data-testid="stat-row"]')
    assert rows, "stat-row 가 없다"
    total = sum(int(r.get_attribute("data-total") or 0) for r in rows)
    assert total == 30, "stat-row 의 data-total 합이 %d" % total
    page.close()
