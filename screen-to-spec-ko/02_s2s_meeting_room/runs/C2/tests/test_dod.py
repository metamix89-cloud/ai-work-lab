# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 2편 — 회의실 예약 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/rooms.csv · seed/users.csv · seed/reservations.csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
"""
import csv
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
DATE = "2026-11-03"

# ── 고정 데이터 (정답을 아는 값) ────────────────────────────────────────────
ROOMS = [("A", "A 회의실", 8), ("B", "B 회의실", 6), ("C", "C 회의실", 12)]
USERS = ["김민수", "박지연", "이서준", "최유나", "정하늘", "한도윤"]
RES = [(1, "A", DATE, "10:00", "11:00", "김민수"),
       (2, "A", DATE, "14:00", "14:30", "박지연"),
       (3, "B", DATE, "10:00", "10:30", "이서준"),
       (4, "C", DATE, "16:00", "18:00", "최유나"),
       (5, "B", DATE, "13:00", "15:00", "김민수")]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("rooms.csv", ["room_id", "name", "capacity"], ROOMS),
              ("users.csv", ["user"], [(u,) for u in USERS]),
              ("reservations.csv", ["res_id", "room_id", "date", "start", "end", "user"], RES)]
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


def http(method, url, body=None):
    """(status, json|text). 4xx 도 예외 없이 돌려준다."""
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
    """화면을 연다. 요청 하나가 멈춰도 테스트가 매달리지 않게 load 까지만 기다리고 1.5초 더 준다."""
    page = pw.new_page(viewport={"width": 1400, "height": 800})
    try:
        page.goto(s.base + "/?date=" + DATE, wait_until="load", timeout=15000)
        page.wait_for_timeout(1500)
    except Exception as e:
        page.close()
        pytest.fail("화면이 열리지 않음: %s" % str(e)[:200])
    return page


def select_user(page, name):
    sel = page.query_selector('[data-testid="user-select"]')
    if not sel:
        pytest.fail("사용자 선택 상자(user-select)가 없음")
    sel.select_option(label=name)
    page.wait_for_timeout(700)


def slot(page, room, start):
    return page.query_selector('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def state(page, room, start):
    el = slot(page, room, start)
    return el.get_attribute("data-state") if el else None


def slot_count(page):
    n = len(page.query_selector_all('[data-testid="slot"]'))
    if n:
        return n
    return len(page.query_selector_all("tbody td, .slot, [class*=slot], [class*=cell]"))


def reservations(s):
    st, data = http("GET", s.base + "/api/reservations?date=" + DATE)
    assert st == 200, "GET /api/reservations 가 %s" % st
    return data


def post(s, room, start, end, user="박지연"):
    return http("POST", s.base + "/api/reservations", {"room_id": room, "date": DATE, "start": start, "end": end, "user": user})


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "회의실" in page.title() or "회의실" in page.inner_text("body")
    page.close()


def test_T2_grid_is_3_rooms_x_18_slots(srv, pw):
    page = open_page(pw, srv)
    assert slot_count(page) == 54
    page.close()


def test_T3_seeded_reservations_show_as_booked_or_mine(srv, pw):
    page = open_page(pw, srv)
    assert state(page, "A", "10:00") in ("booked", "mine"), state(page, "A", "10:00")
    assert state(page, "A", "10:30") in ("booked", "mine"), "11:00 까지의 예약은 10:30 칸도 채운다"
    assert state(page, "A", "11:00") == "free", "11:00 에 끝나는 예약이 11:00 칸을 채우면 안 된다"
    select_user(page, "김민수")
    assert state(page, "A", "10:00") == "mine"
    assert state(page, "B", "10:00") == "booked", "남(이서준)의 예약은 booked"
    page.close()


def test_T4_overlap_is_409_and_count_unchanged(srv):
    before = len(reservations(srv))
    st, body = post(srv, "A", "10:30", "11:30")
    assert st == 409, (st, body)
    assert len(reservations(srv)) == before


def test_T5_adjacent_end_equals_start_is_allowed(srv):
    st, body = post(srv, "A", "11:00", "11:30")
    assert st == 201, ("10:00~11:00 뒤에 11:00~11:30 은 겹침이 아니다", st, body)
    st, body = post(srv, "B", "10:30", "11:00")
    assert st == 201, ("10:00~10:30 뒤에 10:30~11:00", st, body)


def test_T6_30min_unit_and_business_hours(srv):
    st, body = post(srv, "A", "10:15", "10:45")
    assert st == 400, ("10:15 는 30분 단위가 아니다", st, body)
    st, body = post(srv, "A", "17:30", "18:30")
    assert st == 400, ("18:00 을 넘는다", st, body)
    st, body = post(srv, "A", "08:30", "09:00")
    assert st == 400, ("09:00 전", st, body)


def test_T7_max_two_hours(srv):
    st, body = post(srv, "C", "09:00", "11:30")
    assert st == 400, ("2시간 30분은 거부", st, body)
    st, body = post(srv, "C", "09:00", "11:00")
    assert st == 201, ("딱 2시간은 허용", st, body)


def test_T8_delete_only_by_owner(srv):
    st, _ = http("DELETE", srv.base + "/api/reservations/1?user=%s" % urllib.request.quote("박지연"))
    assert st == 403, ("남의 예약 취소는 403", st)
    assert any(r["res_id"] == 1 for r in reservations(srv)), "403 인데 예약이 사라졌다"
    st, _ = http("DELETE", srv.base + "/api/reservations/1?user=%s" % urllib.request.quote("김민수"))
    assert st == 204, ("본인 취소는 204", st)
    assert not any(r["res_id"] == 1 for r in reservations(srv))


def test_T9_cancel_button_only_on_my_slots(srv, pw):
    page = open_page(pw, srv)
    select_user(page, "김민수")
    mine = slot(page, "B", "13:00")
    other = slot(page, "B", "10:00")
    assert mine is not None and mine.get_attribute("data-state") == "mine"
    assert mine.query_selector('[data-testid="cancel-btn"]') is not None, "내 예약 칸에 취소 버튼이 없다"
    assert other is not None and other.get_attribute("data-state") == "booked"
    assert other.query_selector('[data-testid="cancel-btn"]') is None, "남의 예약 칸에 취소 버튼이 있다"
    page.close()
