# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 5편 — 사내 규정 검색 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/clauses.csv 를 서버가 시작할 때 읽는다.
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
import urllib.parse
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상 규정 ─────────────────────────────
CLAUSES = [
    ("L-01", "연차 규정", "제1조", "목적", "이 규정은 직원의 연차 휴가 부여와 사용에 관한 사항을 정한다.", "2024-01-01", ""),
    ("L-05", "연차 규정", "제5조", "연차 부여", "입사 1년이 지난 직원에게 매년 15일의 연차를 부여한다. 3년마다 1일을 더한다.", "2024-01-01", ""),
    ("L-06", "연차 규정", "제6조", "반차 사용", "연차는 반일 단위로 나누어 사용할 수 있다. 반차는 0.5일로 계산한다.", "2024-01-01", ""),
    ("L-07v1", "연차 규정", "제7조", "연차 이월", "사용하지 않은 연차는 다음 해로 이월하지 않는다.", "2024-01-01", "2025-12-31"),
    ("L-07", "연차 규정", "제7조", "연차 이월", "사용하지 않은 연차는 최대 5일까지 다음 해로 이월할 수 있다. 이월한 연차는 다음 해 6월 말까지 사용한다.", "2026-01-01", ""),
    ("L-08", "연차 규정", "제8조", "연차 신청", "연차는 사용일 3일 전까지 신청하고 팀장의 승인을 받는다.", "2024-01-01", ""),
    ("T-03", "출장 규정", "제3조", "국내 출장 숙박비", "국내 출장의 숙박비는 1박 10만 원 한도로 실비 지급한다.", "2024-01-01", ""),
    ("T-04v1", "출장 규정", "제4조", "해외 출장 숙박비", "해외 출장의 숙박비는 1박 15만 원 한도로 실비 지급한다.", "2024-01-01", "2025-06-30"),
    ("T-04", "출장 규정", "제4조", "해외 출장 숙박비", "해외 출장의 숙박비는 1박 20만 원 한도로 실비 지급한다. 영수증을 첨부한다.", "2025-07-01", ""),
    ("T-05", "출장 규정", "제5조", "교통비", "출장 교통비는 대중교통 실비를 지급한다. 자가용 이용 시 km 당 200원을 지급한다.", "2024-01-01", ""),
    ("H-02", "재택 규정", "제2조", "재택 근무 신청", "재택 근무는 주 2일까지 신청할 수 있다. 전주 금요일까지 팀장에게 신청한다.", "2024-03-01", ""),
    ("H-03", "재택 규정", "제3조", "근무 시간", "근무 시간은 09시부터 18시까지로 하며, 재택인 날에도 같다. 점심시간은 12시부터 13시까지다.", "2024-03-01", ""),
]
CURRENT_IDS = {c[0] for c in CLAUSES if c[6] == ""}


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    with open(os.path.join(seed, "clauses.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clause_id", "doc", "article", "title", "body", "effective_from", "effective_to"])
        w.writerows(CLAUSES)


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


def http(method, url):
    req = urllib.request.Request(url, method=method)
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


def search(s, q):
    return http("GET", s.base + "/api/search?q=" + urllib.parse.quote(q))


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
    page = pw.new_page(viewport={"width": 1300, "height": 900})
    try:
        page.goto(s.base + "/", wait_until="load", timeout=15000)
        page.wait_for_timeout(1200)
    except Exception as e:
        page.close()
        pytest.fail("화면이 열리지 않음: %s" % str(e)[:200])
    return page


def ui_search(page, q):
    box = page.query_selector('[data-testid="q"]')
    btn = page.query_selector('[data-testid="search-btn"]')
    if not box or not btn:
        pytest.fail("검색창(q) 또는 검색 버튼(search-btn)이 없음")
    box.fill(q)
    btn.click()
    page.wait_for_timeout(1000)


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "규정" in page.title() or "규정" in page.inner_text("body")
    page.close()


def test_T2_only_current_clause(srv):
    st, body = search(srv, "연차 이월")
    assert st == 200, (st, body)
    ids = [r["clause_id"] for r in body["results"]]
    assert "L-07" in ids, ids
    assert "L-07v1" not in ids, "개정 전 조항이 검색 결과에 나왔다: %s" % ids
    assert body["count"] == len(ids)
    assert all(i in CURRENT_IDS for i in ids), ids


def test_T3_every_result_has_basis(srv, pw):
    st, body = search(srv, "연차")
    assert st == 200 and body["count"] >= 4, body
    for r in body["results"]:
        for k in ("doc", "article", "effective_from"):
            assert r.get(k), "결과에 %s 가 없다: %s" % (k, r)
    page = open_page(pw, srv)
    ui_search(page, "연차 이월")
    card = page.query_selector('[data-testid="result"][data-clause="L-07"]')
    assert card is not None, "L-07 카드가 화면에 없다"
    text = card.inner_text()
    assert "제7조" in text and re.search(r"2026-01-01", text), "카드에 조 번호 · 시행일이 없다: %r" % text[:120]
    assert card.get_attribute("data-article") == "제7조"
    page.close()


def test_T4_no_result_is_empty(srv, pw):
    st, body = search(srv, "헬스장")
    assert st == 200, (st, body)
    assert body["count"] == 0 and body["results"] == [], "없는 규정인데 결과를 돌려줬다: %s" % body
    page = open_page(pw, srv)
    ui_search(page, "헬스장")
    assert page.query_selector('[data-testid="no-result"]') is not None, "no-result 가 없다"
    assert "해당 규정 없음" in page.inner_text("body")
    assert not page.query_selector_all('[data-testid="result"]'), "없음인데 결과 카드가 있다"
    page.close()


def test_T5_all_words_required(srv):
    st, body = search(srv, "출장 숙박비 해외")
    assert st == 200, (st, body)
    ids = [r["clause_id"] for r in body["results"]]
    assert ids == ["T-04"], "해외 숙박비 조항만 나와야 한다(국내 숙박비 T-03 은 '해외' 가 없다): %s" % ids
    st, body = search(srv, "숙박비")
    ids = {r["clause_id"] for r in body["results"]}
    assert ids == {"T-03", "T-04"}, ids


def test_T6_history_returns_old_version(srv):
    st, body = http("GET", srv.base + "/api/clauses/L-07/history")
    assert st == 200, (st, body)
    ids = [h["clause_id"] for h in body]
    assert ids == ["L-07v1"], ids
    assert body[0].get("effective_to") == "2025-12-31"
    st, body = http("GET", srv.base + "/api/clauses/L-08/history")
    assert st == 200 and body == [], ("개정 없는 조항은 빈 목록", st, body)
    st, body = http("GET", srv.base + "/api/clauses/L-07")
    assert st == 200 and body.get("has_history") is True, body


def test_T7_bad_input_and_missing(srv):
    st, body = http("GET", srv.base + "/api/search?q=")
    assert st == 400, ("빈 검색어는 400", st, body)
    st, body = http("GET", srv.base + "/api/search?q=%20%20")
    assert st == 400, ("공백만도 400", st, body)
    st, body = http("GET", srv.base + "/api/clauses/X-99")
    assert st == 404, ("없는 조항은 404", st, body)


def test_T8_title_match_first(srv):
    st, body = search(srv, "재택")
    assert st == 200, (st, body)
    ids = [r["clause_id"] for r in body["results"]]
    assert ids[0] == "H-02", "제목에 '재택' 이 있는 H-02 가 먼저 와야 한다(H-03 은 본문에만): %s" % ids
    assert "H-03" in ids


def test_T9_history_collapsed_until_clicked(srv, pw):
    page = open_page(pw, srv)
    ui_search(page, "연차 이월")
    assert not page.query_selector_all('[data-testid="history-item"]'), "누르기 전에 개정 이력이 보인다"
    btn = page.query_selector('[data-testid="result"][data-clause="L-07"] [data-testid="history-btn"]')
    assert btn is not None, "L-07 카드에 개정 이력 버튼이 없다"
    btn.click()
    page.wait_for_timeout(800)
    items = page.query_selector_all('[data-testid="history-item"]')
    assert len(items) == 1, "개정 전 1건이어야 한다: %d" % len(items)
    assert "개정 전" in items[0].inner_text()
    other = page.query_selector('[data-testid="result"][data-clause="L-08"] [data-testid="history-btn"]')
    assert other is None, "개정 없는 조항에 이력 버튼이 있다"
    page.close()
