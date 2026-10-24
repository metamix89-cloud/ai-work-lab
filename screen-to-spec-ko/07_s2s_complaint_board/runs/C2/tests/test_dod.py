# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 7편 — 민원 접수 · 처리 현황판 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/staff.csv · seed/complaints.csv 를 서버가 시작할 때 읽는다. 날짜는 '오늘' 기준으로 만든다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
테스트는 파일 순서대로 돈다 — T2 · T3 은 아무것도 바꾸기 전, T4 부터 단계 이동.
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


def D(n):
    return (TODAY + dt.timedelta(days=n)).isoformat()


STAFF = [("김민수", "민원1팀"), ("박지연", "민원1팀"), ("이서준", "민원2팀"), ("최팀장", "민원1팀")]
# id, 제목, 분야, 접수일, 상태, 담당자, 답변 — 모두 가상 민원
COMPLAINTS = [
    ("C-01", "가로등 고장 신고", "도로", D(-1), "접수", "", ""),
    ("C-02", "불법 주차 단속 요청", "교통", D(-8), "접수", "", ""),                       # 기한 넘김(접수 그대로)
    ("C-03", "놀이터 시설 파손", "공원", D(-2), "배정", "김민수", ""),
    ("C-04", "소음 민원(공사장)", "환경", D(-9), "처리중", "박지연", ""),                 # 기한 넘김
    ("C-05", "쓰레기 무단 투기", "환경", D(-4), "처리중", "이서준", ""),
    ("C-06", "보도블록 파손", "도로", D(-10), "종결", "김민수", "보수 공사를 마쳤습니다."),  # 기한 지났지만 종결 → 넘김 아님
    ("C-07", "버스 정류장 의자 요청", "교통", D(-3), "종결", "박지연", "설치를 요청했습니다."),
    ("C-08", "하수구 악취", "환경", D(-7), "접수", "", ""),                               # 기한 당일 → 넘김 아님
]
COUNTS = {"접수": 3, "배정": 1, "처리중": 2, "종결": 2}
OVERDUE = {"C-02", "C-04"}


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("staff.csv", ["name", "team"], STAFF),
              ("complaints.csv", ["complaint_id", "title", "category", "received", "status", "assignee", "answer"], COMPLAINTS)]
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


def move(s, cid, to, by="최팀장", assignee="", answer=""):
    return http("POST", s.base + "/api/complaints/%s/transition" % cid, {"to": to, "by": by, "assignee": assignee, "answer": answer})


def items(s):
    st, body = http("GET", s.base + "/api/complaints")
    assert st == 200, "GET /api/complaints 가 %s" % st
    return {i["complaint_id"]: i for i in body["items"]}


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


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "민원" in page.title() or "민원" in page.inner_text("body")
    page.close()


def test_T2_summary_counts_and_overdue(srv):
    st, body = http("GET", srv.base + "/api/summary")
    assert st == 200, (st, body)
    assert body.get("counts") == COUNTS, body.get("counts")
    assert body.get("overdue") == 2, body.get("overdue")
    assert body.get("as_of") == TODAY.isoformat(), body.get("as_of")


def test_T3_overdue_rule(srv):
    it = items(srv)
    got = {k for k, v in it.items() if v.get("overdue")}
    assert got == OVERDUE, "기한 넘김: %s (기대 %s)" % (sorted(got), sorted(OVERDUE))
    assert it["C-08"]["days_left"] == 0, ("기한 당일은 days_left 0", it["C-08"])
    assert it["C-04"]["days_left"] == -2, ("9일 전 접수는 2일 지남", it["C-04"])
    assert it["C-01"]["due"] == D(6), it["C-01"]


def test_T4_forward_with_assignee(srv):
    st, body = move(srv, "C-01", "배정", assignee="이서준")
    assert st == 200, (st, body)
    assert items(srv)["C-01"]["status"] == "배정"
    assert items(srv)["C-01"]["assignee"] == "이서준"


def test_T5_skip_back_and_closed_are_409(srv):
    st, body = move(srv, "C-08", "처리중")
    assert st == 409, ("건너뛰기는 409", st, body)
    st, body = move(srv, "C-05", "배정", assignee="김민수")
    assert st == 409, ("되돌리기는 409", st, body)
    st, body = move(srv, "C-06", "처리중")
    assert st == 409, ("종결된 민원 이동은 409", st, body)
    it = items(srv)
    assert it["C-08"]["status"] == "접수" and it["C-05"]["status"] == "처리중" and it["C-06"]["status"] == "종결", "409 인데 상태가 바뀌었다"


def test_T6_required_inputs_are_400(srv):
    st, body = move(srv, "C-08", "배정", assignee="")
    assert st == 400, ("담당자 없는 배정은 400", st, body)
    st, body = move(srv, "C-08", "배정", assignee="홍길동")
    assert st == 400, ("모르는 담당자는 400", st, body)
    st, body = move(srv, "C-05", "종결", answer="   ")
    assert st == 400, ("답변 없는 종결은 400", st, body)
    st, body = move(srv, "C-08", "배정", by="아무개", assignee="김민수")
    assert st == 400, ("모르는 처리자는 400", st, body)
    assert items(srv)["C-08"]["status"] == "접수"


def test_T7_reject_order(srv):
    st, body = move(srv, "X-99", "완료")
    assert st == 400, ("없는 민원 + 잘못된 to 는 400 이 먼저", st, body)
    st, body = move(srv, "X-99", "배정", assignee="김민수")
    assert st == 404, ("없는 민원 + 올바른 본문은 404", st, body)
    st, body = http("GET", srv.base + "/api/complaints/X-99")
    assert st == 404, (st, body)


def test_T8_history_only_successes_in_order(srv):
    st, body = move(srv, "C-01", "처리중", by="이서준")
    assert st == 200, (st, body)
    st, body = move(srv, "C-01", "종결", by="이서준", answer="수리를 마쳤습니다.")
    assert st == 200, (st, body)
    st, hist = http("GET", srv.base + "/api/complaints/C-01/history")
    assert st == 200, (st, hist)
    steps = [(h["from_status"], h["to_status"], h["by"]) for h in hist]
    assert steps == [("접수", "배정", "최팀장"), ("배정", "처리중", "이서준"), ("처리중", "종결", "이서준")], steps
    st, hist = http("GET", srv.base + "/api/complaints/C-08/history")
    assert st == 200 and hist == [], ("거부된 시도는 이력에 남지 않는다", hist)


def test_T9_screen_columns_cards_overdue(srv, pw):
    page = open_page(pw, srv)
    cols = page.query_selector_all('[data-testid="column"]')
    assert len(cols) == 4, "열 %d개" % len(cols)
    col = page.query_selector('[data-testid="column"][data-status="처리중"]')
    assert col is not None and col.query_selector('[data-testid="complaint"][data-id="C-04"]') is not None, "C-04 가 처리중 열 안에 없다"
    c04 = page.query_selector('[data-testid="complaint"][data-id="C-04"]')
    assert c04.get_attribute("data-overdue") == "1", "기한 넘김 카드 표시가 없다"
    c08 = page.query_selector('[data-testid="complaint"][data-id="C-08"]')
    assert c08 is not None and c08.get_attribute("data-overdue") == "0", "기한 당일 카드가 넘김으로 표시됐다"
    st, body = http("GET", srv.base + "/api/summary")
    oc = page.query_selector('[data-testid="overdue-count"]')
    # 숫자 경계는 \b 가 아니라 '앞뒤가 숫자가 아님' 으로 — '기한 넘김2' 처럼 한글 바로 뒤에 숫자가 붙어도 읽는다(자가 시험에서 잡은 채점기 버그)
    assert oc is not None and re.search(r"(?<!\d)%d(?!\d)" % body["overdue"], oc.inner_text()), "overdue-count %r ≠ %s" % (oc.inner_text() if oc else None, body["overdue"])
    page.close()
