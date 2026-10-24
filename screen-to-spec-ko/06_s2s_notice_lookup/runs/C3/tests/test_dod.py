# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 6편 — 고시 · 공고 열람 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/notices.csv 를 서버가 시작할 때 읽는다. 날짜는 '오늘' 기준으로 만든다.
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
import urllib.parse
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))
TODAY = dt.date.today()


def D(n):
    """오늘에서 n일 뒤(음수면 앞) YYYY-MM-DD."""
    return (TODAY + dt.timedelta(days=n)).isoformat()


U = "https://notice.pureun-gu.example/n/"
# ── 고정 데이터 (정답을 아는 값) — 모두 가상 고시 ─────────────────────────────
# id, 제목, 분야, 부서, 공고일, 시행일, 폐지일, 원문 링크, 원문, 요약
NOTICES = [
    ("N-01", "공영주차장 요금 조정 고시", "주차", "교통행정과", D(-40), D(-30), "", U + "N-01",
     "푸른구 공영주차장의 기본 요금을 30분 1,000원으로 정한다. 이후 10분마다 300원을 더한다.", "공영주차장 기본 요금 30분 1,000원, 이후 10분당 300원."),
    ("N-02", "거주자 우선주차 신청 공고", "주차", "교통행정과", D(-10), D(3), "", U + "N-02",
     "거주자 우선주차 구획을 신청받는다. 신청은 구청 누리집에서 하며 선정은 추첨으로 한다.", "거주자 우선주차 신청, 추첨 선정."),
    ("N-03", "공영주차장 요금 고시(구)", "주차", "교통행정과", D(-400), D(-390), D(-30), U + "N-03",
     "푸른구 공영주차장의 기본 요금을 30분 800원으로 정한다.", "공영주차장 기본 요금 30분 800원."),
    ("N-04", "음식점 위생 점검 기준 고시", "위생", "위생과", D(-20), D(-5), "", U + "N-04",
     "일반음식점의 위생 점검 항목을 12개로 정한다. 점검 결과는 구청 누리집에 공개한다.", ""),
    ("N-05", "식품 접객업소 영업시간 안내 공고", "위생", "위생과", D(-5), D(10), "", U + "N-05",
     "축제 기간 동안 식품 접객업소의 영업시간 제한을 풀지 않는다.", "축제 기간에도 영업시간 제한 유지."),
    ("N-06", "건축물 외벽 도색 지원 공고", "건축", "건축과", D(-15), D(-15), "", U + "N-06",
     "노후 건축물 외벽 도색 비용의 절반을 지원한다. 한 건물당 300만 원까지.", "외벽 도색 비용 50% 지원, 건물당 300만 원 한도."),
    ("N-07", "건축 허가 서류 간소화 고시(구)", "건축", "건축과", D(-300), D(-290), D(-60), U + "N-07",
     "건축 허가 신청 서류를 7종에서 5종으로 줄인다.", "허가 서류 7종 → 5종."),
    ("N-08", "경로당 냉방비 지원 공고", "복지", "복지정책과", D(-8), D(-8), "", U + "N-08",
     "관내 경로당의 여름철 냉방비를 월 10만 원까지 지원한다.", ""),
    ("N-09", "복지 시설 이용 안내(출처 미확인)", "복지", "복지정책과", D(-3), D(-3), "", "",
     "출처가 확인되지 않은 안내문. 원문 링크가 없다.", "출처 없는 요약."),
    ("N-10", "공영주차장 야간 무료 개방 공고", "주차", "교통행정과", D(-2), D(-2), "", U + "N-10",
     "공영주차장 3곳을 밤 10시부터 아침 7시까지 무료로 연다.", "공영주차장 3곳 야간 무료."),
]
DEFAULT_IDS = {"N-01", "N-02", "N-04", "N-05", "N-06", "N-08", "N-10"}      # 폐지 N-03 · N-07, 출처 없음 N-09 제외
ALL_IDS = DEFAULT_IDS | {"N-03", "N-07"}


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    with open(os.path.join(seed, "notices.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["notice_id", "title", "category", "issuer", "published", "effective_from", "repealed", "source_url", "original", "summary"])
        w.writerows(NOTICES)


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


def http(url):
    try:
        r = urllib.request.urlopen(url, timeout=5)
        raw = r.read().decode("utf-8")
        status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        status = e.code
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw


def notices(s, **params):
    return http(s.base + "/api/notices" + ("?" + urllib.parse.urlencode(params) if params else ""))


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


def by_id(body):
    return {i["notice_id"]: i for i in body["items"]}


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    page = open_page(pw, srv)
    assert "고시" in page.title() or "고시" in page.inner_text("body")
    page.close()


def test_T2_default_hides_repealed_and_sourceless(srv):
    st, body = notices(srv)
    assert st == 200, (st, body)
    ids = set(by_id(body))
    assert ids == DEFAULT_IDS, "기본 목록: %s (기대 %s)" % (sorted(ids), sorted(DEFAULT_IDS))
    assert body["count"] == len(DEFAULT_IDS)


def test_T3_upcoming_status_and_days(srv):
    st, body = notices(srv)
    items = by_id(body)
    assert items["N-02"]["status"] == "시행 예정" and items["N-02"]["days_until"] == 3, items["N-02"]
    assert items["N-05"]["status"] == "시행 예정" and items["N-05"]["days_until"] == 10, items["N-05"]
    assert items["N-01"]["status"] == "시행 중" and items["N-01"]["days_until"] is None, items["N-01"]


def test_T4_include_repealed(srv):
    st, body = notices(srv, include_repealed=1)
    assert st == 200, (st, body)
    items = by_id(body)
    assert set(items) == ALL_IDS, "폐지 포함: %s" % sorted(items)
    assert items["N-03"]["status"] == "폐지" and items["N-07"]["status"] == "폐지"
    assert "N-09" not in items, "원문 링크 없는 고시가 나왔다"


def test_T5_summary_not_fabricated(srv):
    st, body = notices(srv)
    items = by_id(body)
    for nid in ("N-04", "N-08"):
        assert items[nid]["summary"] == "", "%s 요약이 비어 있어야 한다(원문을 잘라 채우지 않는다): %r" % (nid, items[nid]["summary"])
        assert items[nid]["has_summary"] is False
    assert items["N-01"]["has_summary"] is True


def test_T6_every_item_has_basis_and_as_of(srv):
    st, body = notices(srv, include_repealed=1)
    assert body.get("as_of") == TODAY.isoformat(), "as_of 가 오늘이 아니다: %r" % body.get("as_of")
    for i in body["items"]:
        for k in ("issuer", "published", "effective_from"):
            assert i.get(k), "%s 에 %s 가 없다" % (i.get("notice_id"), k)
        assert str(i.get("source_url", "")).startswith("http"), "%s 원문 링크: %r" % (i.get("notice_id"), i.get("source_url"))


def test_T7_category_and_query_and_order(srv):
    st, body = notices(srv, category="주차", q="공영주차장 요금")
    assert st == 200, (st, body)
    assert [i["notice_id"] for i in body["items"]] == ["N-01"], body["items"]
    st, body = notices(srv, category="주차")
    assert [i["notice_id"] for i in body["items"]] == ["N-10", "N-02", "N-01"], "공고일 최신 먼저: %s" % [i["notice_id"] for i in body["items"]]
    st, body = notices(srv, q="헬스장")
    assert st == 200 and body["count"] == 0 and body["items"] == []


def test_T8_bad_input_and_missing(srv):
    st, _ = notices(srv, category="교육")
    assert st == 400, ("알 수 없는 분야는 400", st)
    st, _ = notices(srv, include_repealed=2)
    assert st == 400, ("include_repealed=2 는 400", st)
    st, _ = http(srv.base + "/api/notices/X-99")
    assert st == 404, ("없는 고시는 404", st)
    st, _ = http(srv.base + "/api/notices/N-09")
    assert st == 404, ("원문 링크 없는 고시의 상세는 404", st)
    st, body = http(srv.base + "/api/notices/N-03")
    assert st == 200 and body.get("status") == "폐지" and body.get("original"), ("폐지 고시 상세는 열린다", st, body)


def test_T9_screen_badges_links_summary(srv, pw):
    page = open_page(pw, srv)
    card = page.query_selector('[data-testid="notice"][data-id="N-02"]')
    assert card is not None, "N-02 카드가 없다"
    badge = card.query_selector('[data-testid="badge"]')
    assert badge is not None and re.search(r"D-\s*3", badge.inner_text()), "시행 예정 배지에 D-3 이 없다: %r" % (badge.inner_text() if badge else None)
    link = card.query_selector('[data-testid="source-link"]')
    assert link is not None and (link.get_attribute("href") or "").startswith("http"), "원문 링크가 없다"
    card.click()
    page.wait_for_timeout(900)
    summ = page.query_selector('[data-testid="summary"]')
    assert summ is not None and "법적 효력은 원문" in summ.inner_text(), "요약 칸 표시가 없다: %r" % (summ.inner_text() if summ else None)
    assert page.query_selector('[data-testid="original"]') is not None
    page.query_selector('[data-testid="notice"][data-id="N-04"]').click()
    page.wait_for_timeout(900)
    summ = page.query_selector('[data-testid="summary"]')
    assert summ is not None and "요약 없음" in summ.inner_text(), "요약 없는 고시인데 '요약 없음' 이 아니다: %r" % (summ.inner_text() if summ else None)
    page.close()
