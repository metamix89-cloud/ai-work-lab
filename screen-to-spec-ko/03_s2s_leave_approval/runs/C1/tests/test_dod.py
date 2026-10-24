# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 3편 — 휴가 · 출장 신청과 결재 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users.csv · seed/requests.csv 를 서버가 시작할 때 읽는다.
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

# ── 고정 데이터 (정답을 아는 값) ────────────────────────────────────────────
# 박지연: 총 15 · 승인 2 · 신청 중 1 → 잔여 12. 11-05(목)~11-09(월) 은 주말 빼고 3일.
USERS = [("김민수", "개발팀", "manager", "", 15),
         ("박지연", "개발팀", "member", "김민수", 15),
         ("이서준", "개발팀", "member", "김민수", 15),
         ("최유나", "디자인팀", "manager", "", 15),
         ("정하늘", "디자인팀", "member", "최유나", 15)]
REQS = [(1, "박지연", "연차", "2026-10-12", "2026-10-13", 2, "개인 사정", "승인", "김민수", ""),
        (2, "박지연", "연차", "2026-11-20", "2026-11-20", 1, "병원", "신청", "", ""),
        (3, "이서준", "출장", "2026-11-10", "2026-11-11", 2, "고객사 방문", "신청", "", ""),
        (4, "박지연", "연차", "2026-12-01", "2026-12-02", 2, "여행", "반려", "김민수", "분기 마감 주간"),
        (5, "정하늘", "연차", "2026-11-12", "2026-11-12", 1, "가족 행사", "신청", "", "")]
MY_COUNT = sum(1 for r in REQS if r[1] == "박지연")   # 3


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user", "team", "role", "manager", "leave_total"], USERS),
              ("requests.csv", ["req_id", "user", "type", "start", "end", "days", "reason", "status", "approver", "reject_reason"], REQS)]
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


def q(s):
    return urllib.request.quote(s)


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


def select_user(page, name):
    sel = page.query_selector('[data-testid="user-select"]')
    if not sel:
        pytest.fail("사용자 선택 상자(user-select)가 없음")
    sel.select_option(label=name)
    page.wait_for_timeout(800)


def balance(s, user):
    st, data = http("GET", s.base + "/api/balance?user=" + q(user))
    assert st == 200, "GET /api/balance 가 %s" % st
    return data


def post_req(s, user, typ, start, end, reason="사유"):
    return http("POST", s.base + "/api/requests", {"user": user, "type": typ, "start": start, "end": end, "reason": reason})


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "휴가" in page.title() or "휴가" in page.inner_text("body")
    page.close()


def test_T2_balance_and_my_requests_on_screen(srv, pw):
    page = open_page(pw, srv)
    select_user(page, "박지연")
    el = page.query_selector('[data-testid="remaining"]')
    assert el is not None, "잔여 숫자(remaining)가 없음"
    assert re.search(r"\b12\b", el.inner_text()), "잔여가 12 가 아님: %r" % el.inner_text()
    rows = page.query_selector_all('[data-testid="my-request"]')
    assert len(rows) == MY_COUNT, "내 신청 행 %d (기대 %d)" % (len(rows), MY_COUNT)
    page.close()


def test_T3_days_exclude_weekend(srv):
    st, body = post_req(srv, "박지연", "연차", "2026-11-05", "2026-11-09", "가족 행사")
    assert st == 201, (st, body)
    assert body.get("days") == 3, ("목~월은 주말 빼고 3일", body)
    assert balance(srv, "박지연")["remaining"] == 12 - 3


def test_T4_over_balance_rejected_but_trip_allowed(srv):
    # 지금 잔여 9 (12 - 3). 10일 연차는 400, 같은 기간 출장은 201
    st, body = post_req(srv, "박지연", "연차", "2027-01-04", "2027-01-15", "장기 휴가")   # 평일 10일
    assert st == 400, ("잔여를 넘는 연차는 400", st, body)
    st, body = post_req(srv, "이서준", "출장", "2027-01-04", "2027-01-15", "장기 출장")
    assert st == 201, ("출장은 잔여를 검사하지 않는다", st, body)
    assert balance(srv, "이서준")["remaining"] == 15, "출장이 연차를 깎았다"


def test_T5_only_manager_can_approve(srv):
    before = balance(srv, "박지연")
    st, body = http("POST", srv.base + "/api/requests/2/approve", {"approver": "최유나"})
    assert st == 403, ("다른 팀 팀장은 403", st, body)
    st, body = http("POST", srv.base + "/api/requests/2/approve", {"approver": "박지연"})
    assert st == 403, ("본인 승인은 403", st, body)
    st, body = http("POST", srv.base + "/api/requests/2/approve", {"approver": "김민수"})
    assert st == 200 and body.get("status") == "승인", (st, body)
    after = balance(srv, "박지연")
    assert after["used"] == before["used"] + 1 and after["pending"] == before["pending"] - 1
    assert after["remaining"] == before["remaining"], "신청 중 → 승인은 잔여를 바꾸지 않는다(이미 대기로 뺐다)"


def test_T6_reject_requires_reason(srv):
    st, body = http("POST", srv.base + "/api/requests/5/reject", {"approver": "최유나", "reason": ""})
    assert st == 400, ("사유 없는 반려는 400", st, body)
    st, body = http("POST", srv.base + "/api/requests/5/reject", {"approver": "최유나", "reason": "행사 당일 대체 인력 없음"})
    assert st == 200 and body.get("status") == "반려", (st, body)
    st, mine = http("GET", srv.base + "/api/requests?user=" + q("정하늘"))
    row = next(r for r in mine if r["req_id"] == 5)
    assert row.get("reject_reason") == "행사 당일 대체 인력 없음"


def test_T7_decision_is_final(srv):
    st, body = http("POST", srv.base + "/api/requests/2/approve", {"approver": "김민수"})
    assert st == 409, ("이미 승인된 건 재승인은 409", st, body)
    st, body = http("POST", srv.base + "/api/requests/2/reject", {"approver": "김민수", "reason": "변경"})
    assert st == 409, ("이미 승인된 건 반려도 409", st, body)
    st, body = http("POST", srv.base + "/api/requests/4/cancel", {"user": "박지연"})
    assert st == 409, ("반려된 건 취소도 409", st, body)


def test_T8_overlap_with_pending_or_approved(srv):
    st, body = post_req(srv, "박지연", "연차", "2026-11-09", "2026-11-10", "겹침")   # T3 의 11-05~11-09 와 하루 겹침
    assert st == 409, ("신청 중인 기간과 겹치면 409", st, body)
    st, body = post_req(srv, "박지연", "연차", "2026-10-13", "2026-10-13", "겹침")   # 승인된 10-12~13 과 겹침
    assert st == 409, ("승인된 기간과 겹치면 409", st, body)
    st, body = post_req(srv, "박지연", "연차", "2026-12-01", "2026-12-01", "재신청")  # 반려된 12-01~02 과는 겹쳐도 됨
    assert st == 201, ("반려된 건과는 겹쳐도 201", st, body)


def test_T9_manager_sees_pending_with_buttons_member_does_not(srv, pw):
    page = open_page(pw, srv)
    select_user(page, "김민수")
    rows = page.query_selector_all('[data-testid="pending-request"]')
    assert rows, "팀장에게 결재 대기 행이 없다"
    assert rows[0].query_selector('[data-testid="approve-btn"]') is not None, "승인 버튼이 없다"
    users = {r.get_attribute("data-id") for r in rows}
    assert "3" in users, "이서준(개발팀)의 신청 3번이 김민수의 대기 목록에 없다"
    select_user(page, "박지연")
    assert not page.query_selector_all('[data-testid="pending-request"]'), "직원에게 결재 대기 행이 보인다"
    assert page.query_selector('[data-testid="approve-btn"]') is None
    page.close()
