# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 12편 — 사내 소식 피드 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users.csv · posts.csv · comments.csv · reports.csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
서버 하나를 T1~T9 가 차례로 쓴다 — 앞 테스트가 만든 상태(새 글 · 삭제 · 고정 · 신고)를 뒤 테스트가 전제로 한다.
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

# ── 고정 데이터 (정답을 아는 값) — 모두 가상 ─────────────────────────────────
USERS = [("u1", "김하나", "member"), ("u2", "이두리", "member"), ("u3", "박세찬", "member"),
         ("u4", "최다온", "member"), ("a1", "정운영", "admin")]
AUTHORS = ["u1", "u2", "u3", "u4"]
BASE = datetime(2026, 10, 20, 9, 0)
PINNED = {"P003", "P007"}                                   # 오래된 글 둘이 고정 — 그래도 맨 위


def _when(i):
    if i == 45:
        i = 44                                              # P044 · P045 는 같은 시각 → post_id 큰 P045 가 먼저(R1)
    return (BASE + timedelta(minutes=10 * i)).strftime("%Y-%m-%d %H:%M")


POSTS = [("P%03d" % i, AUTHORS[(i - 1) % 4], "소식 %d번 — 이번 주 팀 소식입니다." % i, _when(i), "1" if "P%03d" % i in PINNED else "0")
         for i in range(1, 46)]
COMMENTS = [("C001", "P045", "u2", "좋은 소식이네요", "2026-10-20 17:00"), ("C002", "P045", "u3", "확인했습니다", "2026-10-20 17:05"),
            ("C003", "P010", "u1", "감사합니다", "2026-10-20 11:00")]
REPORTS = [("P030", "u1"), ("P030", "u3")]                 # P030(작성자 u2)에 신고 2건 — 셋째(T7)에서 숨김
REGULAR = [p[0] for p in sorted((p for p in POSTS if p[4] == "0"), key=lambda p: (p[3], p[0]), reverse=True)]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("posts.csv", ["post_id", "author_id", "body", "created_at", "pinned"], POSTS),
              ("comments.csv", ["comment_id", "post_id", "author_id", "body", "created_at"], COMMENTS),
              ("reports.csv", ["post_id", "reporter_id"], REPORTS)]
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


def page(s, viewer="u1", before=None):
    q = {"viewer": viewer}
    if before is not None:
        q["before"] = before
    st, body = http("GET", s.base + "/api/posts?" + urllib.parse.urlencode(q))
    assert st == 200 and isinstance(body, dict), ("GET /api/posts", st, body)
    return body


def ids(items):
    return [p["post_id"] for p in items]


def all_posts(s, viewer):
    first = page(s, viewer)
    out, cur, n = list(first["posts"]), first.get("next_cursor"), 0
    while cur and n < 10:
        nxt = page(s, viewer, cur)
        out += nxt["posts"]
        cur, n = nxt.get("next_cursor"), n + 1
    return first["pinned"] + out


def new_post(s, user, body):
    return http("POST", s.base + "/api/posts", {"user": user, "body": body})


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


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    pg = open_page(pw, srv)
    assert "소식" in pg.title() or "소식" in pg.inner_text("body")
    pg.close()


def test_T2_first_page(srv):
    b = page(srv)
    assert ids(b["pinned"]) == ["P007", "P003"], ("고정 글은 첫 쪽 pinned 에, 최신 순", ids(b["pinned"]))
    assert ids(b["posts"]) == REGULAR[:20], ("일반 글 20개 최신 순(같은 시각이면 post_id 큰 순)", ids(b["posts"])[:5])
    assert b.get("next_cursor"), "다음 쪽이 있으면 next_cursor"
    st, users = http("GET", srv.base + "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} >= {("u1", "member"), ("a1", "admin")}, users


def test_T3_cursor_no_overlap(srv):
    first = page(srv)
    st, body = new_post(srv, "u3", "더 보기 사이에 올라온 새 글")
    assert st == 201, ("새 글", st, body)
    second = page(srv, before=first["next_cursor"])
    assert second["pinned"] == [], "둘째 쪽의 pinned 는 빈 목록"
    assert ids(second["posts"]) == REGULAR[20:40], ("새 글이 올라와도 둘째 쪽은 이어서 — 겹침 · 빠짐 없음", ids(second["posts"])[:3])
    third = page(srv, before=second["next_cursor"])
    assert ids(third["posts"]) == REGULAR[40:] and third.get("next_cursor") is None, ("마지막 쪽", ids(third["posts"]), third.get("next_cursor"))


def test_T4_body_rules(srv):
    for bad in ["", "   ", "가" * 501]:
        st, body = new_post(srv, "u1", bad)
        assert st == 400, ("본문 1~500자(앞뒤 공백 뺀 길이)", len(bad), st, body)
    st, body = new_post(srv, "u1", "가" * 500)
    assert st == 201 and body.get("post_id"), (st, body)
    assert page(srv)["posts"][0]["post_id"] == body["post_id"], "새 글은 첫 쪽 일반 글 맨 앞"


def test_T5_delete(srv):
    st, body = http("DELETE", srv.base + "/api/posts/P045", {"user": "u2"})
    assert st == 403, ("직원이 남의 글을 지우면 403", st, body)
    st, body = http("DELETE", srv.base + "/api/posts/P045", {"user": "u1"})
    assert st == 200, ("자기 글 삭제", st, body)
    assert "P045" not in ids(all_posts(srv, "u1")), "지운 글은 피드에서 빠진다"
    st, body = http("DELETE", srv.base + "/api/posts/P044", {"user": "a1"})
    assert st == 200, ("운영자는 남의 글도 지운다", st, body)
    st, body = http("POST", srv.base + "/api/posts/P045/comments", {"user": "u2", "body": "늦게 단 댓글"})
    assert st == 404, ("지운 글에 댓글은 404", st, body)


def test_T6_pin(srv):
    st, body = http("POST", srv.base + "/api/posts/P040/pin", {"user": "u1", "pinned": True})
    assert st == 403, ("직원의 고정은 403", st, body)
    st, body = http("POST", srv.base + "/api/posts/P040/pin", {"user": "a1", "pinned": True})
    assert st == 200, ("운영자의 고정", st, body)
    b = page(srv)
    assert ids(b["pinned"]) == ["P040", "P007", "P003"] and "P040" not in ids(b["posts"]), ids(b["pinned"])
    st, body = http("POST", srv.base + "/api/posts/P039/pin", {"user": "a1", "pinned": True})
    assert st == 409, ("넷째 고정은 409", st, body)


def test_T7_report(srv):
    st, body = http("POST", srv.base + "/api/posts/P030/reports", {"user": "u2"})
    assert st == 403, ("자기 글 신고는 403", st, body)
    st, body = http("POST", srv.base + "/api/posts/P030/reports", {"user": "u1"})
    assert st == 409, ("같은 사람의 두 번째 신고는 409", st, body)
    st, body = http("POST", srv.base + "/api/posts/P030/reports", {"user": "u4"})
    assert st == 201 and body.get("hidden") is True, ("서로 다른 3명 → 숨김", st, body)
    assert "P030" not in ids(all_posts(srv, "u3")), "숨긴 글은 다른 직원의 피드에서 빠진다"
    for v in ("u2", "a1"):
        p = {x["post_id"]: x for x in all_posts(srv, v)}.get("P030")
        assert p is not None and p.get("hidden") is True, ("작성자 · 운영자에게는 hidden: true 로 보인다", v, p)


def test_T8_reject_order(srv):
    st, body = http("POST", srv.base + "/api/posts/P999/pin", {"pinned": True})
    assert st == 400, ("user 없음 + 없는 글은 400 이 먼저", st, body)
    st, body = http("POST", srv.base + "/api/posts/P999/pin", {"user": "a1", "pinned": True})
    assert st == 404, ("없는 글은 404", st, body)
    st, body = http("POST", srv.base + "/api/posts/P010/pin", {"user": "nobody", "pinned": True})
    assert st == 404, ("없는 사용자는 404", st, body)
    st, body = http("POST", srv.base + "/api/posts/P010/pin", {"user": "u1", "pinned": True})
    assert st == 403, ("고정 3개가 찬 상태에서 직원의 고정은 권한(403)이 먼저", st, body)


def test_T9_screen(srv, pw):
    pg = open_page(pw, srv)
    posts = pg.query_selector_all('[data-testid="post"]')
    assert posts and posts[0].get_attribute("data-pinned") == "1", "고정 글이 맨 위(data-pinned=1)에 없다"
    regular = lambda: [e.get_attribute("data-id") for e in pg.query_selector_all('[data-testid="post"][data-pinned="0"]')]
    assert len(regular()) == 20, ("첫 쪽 일반 글 20개", len(regular()))
    more = pg.query_selector('[data-testid="more"]')
    assert more is not None, "더 보기 버튼이 없다"
    more.click()
    pg.wait_for_timeout(1200)
    r = regular()
    assert len(r) == 40 and len(set(r)) == 40, ("더 보기 뒤 일반 글 40개, 겹침 없음", len(r), len(set(r)))
    pg.fill('[data-testid="compose"]', "")
    pg.click('[data-testid="submit"]')
    pg.wait_for_timeout(1000)
    msg = pg.query_selector('[data-testid="message"]')
    assert msg is not None and "내용을 확인하세요" in msg.inner_text(), ("빈 글 → 서버의 detail", msg.inner_text() if msg else None)
    pg.fill('[data-testid="compose"]', "<b>굵게</b>")
    pg.click('[data-testid="submit"]')
    pg.wait_for_timeout(1200)
    texts = [e.inner_text() for e in pg.query_selector_all('[data-testid="post"]')]
    assert any("<b>굵게</b>" in t for t in texts), "본문을 글자 그대로 보여 주지 않는다(HTML 로 해석됨)"
    pg.close()
