# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 9편 — 신입사원 온보딩 교육 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/ 의 CSV 5개를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
테스트는 파일 순서대로 돈다 — 진도 · 응시가 차례로 바뀐다.
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
import urllib.parse
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상 ─────────────────────────────────
USERS = [("김신입", "trainee"), ("이신입", "trainee"), ("박신입", "trainee"), ("최인사", "admin")]
LESSONS = [("L1", 1, "회사 소개와 조직도"), ("L2", 2, "근무 시간과 휴가"), ("L3", 3, "보안 수칙"), ("L4", 4, "업무 도구 사용법")]
ANSWERS = [0, 1, 2, 3, 0]
QUESTIONS = [("Q1", "근무 시작 시각은?", "9시|10시|11시|정해지지 않음", 0),
             ("Q2", "반차는 몇 일로 계산하나?", "1일|0.5일|0.25일|0일", 1),
             ("Q3", "외부 메일의 첨부 파일은?", "바로 연다|동료에게 넘긴다|보안팀 확인 뒤 연다|지운다", 2),
             ("Q4", "업무 메신저가 아닌 것은?", "팀 채팅|사내 게시판|화상 회의|개인 메신저", 3),
             ("Q5", "자리를 비울 때 화면은?", "잠근다|켜 둔다|끈다|밝기를 낮춘다", 0)]
PROGRESS = [("김신입", l, "2026-10-20 10:00") for l in ("L1", "L2", "L3", "L4")] + \
           [("이신입", "L1", "2026-10-21 10:00")] + \
           [("박신입", l, "2026-10-19 10:00") for l in ("L1", "L2", "L3", "L4")]
ATTEMPTS = [("김신입", 1, 60, 0, "2026-10-21 11:00"),
            ("박신입", 1, 40, 0, "2026-10-20 11:00"), ("박신입", 2, 60, 0, "2026-10-21 11:00")]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user", "role"], USERS), ("lessons.csv", ["lesson_id", "seq", "title"], LESSONS),
              ("questions.csv", ["q_id", "text", "choices", "answer"], QUESTIONS),
              ("progress.csv", ["user", "lesson_id", "completed_at"], PROGRESS),
              ("attempts.csv", ["user", "attempt", "score", "passed", "at"], ATTEMPTS)]
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
        return status, (json.loads(raw) if raw else None), raw
    except ValueError:
        return status, raw, raw


def q(s):
    return urllib.parse.quote(s)


def progress(s, user, viewer=None):
    return http("GET", s.base + "/api/progress?user=%s&viewer=%s" % (q(user), q(viewer or user)))


def complete(s, user, lesson):
    return http("POST", s.base + "/api/lessons/%s/complete" % lesson, {"user": user})


def submit(s, user, answers):
    return http("POST", s.base + "/api/quiz/submit", {"user": user, "answers": answers})


def with_right(n):
    """정답 n개, 나머지는 틀린 답."""
    return [a if i < n else (a + 1) % 4 for i, a in enumerate(ANSWERS)]


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
    page.wait_for_timeout(900)


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "온보딩" in page.title() or "온보딩" in page.inner_text("body")
    page.close()


def test_T2_quiz_has_no_answers(srv):
    st, body, raw = http("GET", srv.base + "/api/quiz")
    assert st == 200 and isinstance(body, list) and len(body) == 5, (st, raw[:200])
    for item in body:
        keys = {k.lower() for k in item}
        assert not keys & {"answer", "correct", "correct_index", "answer_index", "solution"}, "정답 칸이 나갔다: %s" % item
        assert len(item.get("choices", [])) == 4, item


def test_T3_lessons_in_order(srv):
    st, body, _ = complete(srv, "이신입", "L3")
    assert st == 409, ("L2 전에 L3 은 409", st, body)
    st, body, _ = complete(srv, "이신입", "L2")
    assert st == 200, (st, body)
    st, body, _ = progress(srv, "이신입")
    assert st == 200 and body["progress"] == 50, body
    states = {l["lesson_id"]: l["state"] for l in body["lessons"]}
    assert states == {"L1": "done", "L2": "done", "L3": "open", "L4": "locked"}, states


def test_T4_quiz_needs_all_lessons(srv):
    st, body, _ = submit(srv, "이신입", ANSWERS)
    assert st == 409, ("레슨 4개 전에는 409", st, body)


def test_T5_eighty_passes_and_no_answer_leak(srv):
    st, body, raw = submit(srv, "김신입", with_right(4))
    assert st == 200, (st, body)
    assert body["score"] == 80 and body["passed"] is True and body["certified"] is True and body["attempt"] == 2, body
    low = raw.lower()
    assert not any(k in low for k in ('"answer', '"correct', '"wrong', '"results"', '"detail_by')), "채점 결과에 정답 · 정오가 나갔다: %s" % raw[:300]
    st, body, _ = submit(srv, "김신입", ANSWERS)
    assert st == 409, ("합격 뒤 제출은 409", st, body)


def test_T6_three_attempts_then_locked(srv):
    st, body, _ = submit(srv, "박신입", with_right(3))
    assert st == 200 and body["score"] == 60 and body["passed"] is False and body["attempt"] == 3 and body["attempts_left"] == 0, body
    st, body, _ = submit(srv, "박신입", ANSWERS)
    assert st == 409, ("네 번째 제출은 409", st, body)
    st, body, _ = progress(srv, "박신입")
    assert body["certified"] is False and body["progress"] == 100, body


def test_T7_permissions_and_order(srv):
    st, _, _ = progress(srv, "김신입", viewer="이신입")
    assert st == 403, ("신입이 남의 진도는 403", st)
    st, _, _ = progress(srv, "김신입", viewer="최인사")
    assert st == 200, ("관리자는 200", st)
    st, _, _ = http("GET", srv.base + "/api/admin/incomplete?viewer=" + q("이신입"))
    assert st == 403, ("신입이 미수료자 목록은 403", st)
    st, body, _ = submit(srv, "아무개", [9, 9])
    assert st == 400, ("없는 사용자 + 잘못된 answers 는 400 이 먼저", st, body)
    st, body, _ = submit(srv, "아무개", ANSWERS)
    assert st == 404, ("없는 사용자 + 올바른 answers 는 404", st, body)


def test_T8_admin_incomplete_list(srv):
    st, body, _ = http("GET", srv.base + "/api/admin/incomplete?viewer=" + q("최인사"))
    assert st == 200, (st, body)
    users = [r["user"] for r in body]
    assert users == ["이신입", "박신입"], "수료자(김신입) 제외 · 진도 낮은 순: %s" % users
    assert [r["progress"] for r in body] == [50, 100], body


def test_T9_screen_trainee_and_admin(srv, pw):
    page = open_page(pw, srv)
    select_user(page, "이신입")
    rows = {r.get_attribute("data-id"): r.get_attribute("data-state") for r in page.query_selector_all('[data-testid="lesson"]')}
    assert rows == {"L1": "done", "L2": "done", "L3": "open", "L4": "locked"}, rows
    pg = page.query_selector('[data-testid="progress"]')
    assert pg is not None and re.search(r"(?<!\d)50\s*%", pg.inner_text()), "진도율 %r" % (pg.inner_text() if pg else None)
    quiz = page.query_selector('[data-testid="quiz"]')
    assert quiz is None or not quiz.is_visible(), "레슨을 다 안 마쳤는데 퀴즈가 보인다"
    select_user(page, "최인사")
    adm = [r.get_attribute("data-user") for r in page.query_selector_all('[data-testid="incomplete-row"]')]
    assert adm == ["이신입", "박신입"], "관리자 화면 미수료자 행: %s" % adm
    assert not page.query_selector_all('[data-testid="lesson"]') or not page.query_selector('[data-testid="lesson"]').is_visible(), "관리자 화면에 신입 레슨이 보인다"
    page.close()
