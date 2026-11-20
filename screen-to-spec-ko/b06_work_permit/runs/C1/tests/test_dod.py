# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 2부 6편 — 위험 작업 허가서 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users · zones · check_items · permits .csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
고정 데이터의 시각은 **테스트를 돌리는 시각(지금)** 기준(승인 9시간 전 = 만료, 30분 전 = 유효 …). 만료는 서버 시계로 판정한다 — 시간을 조작하지 않는다.
서버 하나를 T1~T9 가 차례로 쓴다 — T4 의 승인을 T9 가, T5 의 작업 시작을 T6 · T9 가 전제로 한다.
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

# ── 고정 데이터 (정답을 아는 값) — 모두 가상(뚝딱건설은 가상 회사), 시각은 지금 기준 ──
NOW = datetime.now().replace(second=0, microsecond=0)
FMT = "%Y-%m-%d %H:%M"
DAY0 = NOW.replace(hour=0, minute=0)


def at_h(h):
    return (NOW + timedelta(hours=h)).strftime(FMT)


def at_m(m):
    return (NOW + timedelta(minutes=m)).strftime(FMT)


def today_or(h):
    """지금 −h 시간, 단 오늘 00:00 보다 앞이면 오늘 00:00 (자정 직후에도 '유효한 승인' 이 되게)"""
    return max(NOW - timedelta(hours=h), DAY0).strftime(FMT)


def plus(ts, minutes):
    return (datetime.strptime(ts, FMT) + timedelta(minutes=minutes)).strftime(FMT)


def expected_valid_until(approved_at):
    a = datetime.strptime(approved_at, FMT)
    return min(a + timedelta(hours=8), a.replace(hour=23, minute=59)).strftime(FMT)


USERS = [("w1", "김작업", "worker"), ("w2", "이반장", "worker"), ("s1", "박안전", "safety"), ("m1", "최소장", "manager"), ("m2", "정부소장", "manager")]
ZONES = [("Z1", "본관 3층"), ("Z2", "지하 1층 기계실"), ("Z3", "옥상")]
CHECK_ITEMS = [("height", "H1", "안전대 착용"), ("height", "H2", "작업 발판 점검"), ("height", "H3", "추락 방지망 설치"),
               ("hot", "F1", "소화기 비치"), ("hot", "F2", "화기 감시자 배치"), ("hot", "F3", "가연물 제거"),
               ("confined", "C1", "산소 농도 측정"), ("confined", "C2", "환기 장치 가동"), ("confined", "C3", "외부 감시자 배치")]
H, F, C = "H1|H2|H3", "F1|F2|F3", "C1|C2|C3"
# permit_id, work_type, zone_id, requester_id, start_at, end_at, status, checked, reviewed_by, approved_by, approved_at, started_at, closed_at
PERMITS = [("WP-0101", "height", "Z1", "w1", at_h(-1), at_h(3), "requested", H, "", "", "", "", ""),            # T4 검토 → 승인 흐름, T9 작업 시작
           ("WP-0102", "hot", "Z2", "m2", at_h(0), at_h(2), "reviewed", F, "s1", "", "", "", ""),               # 책임자 m2 가 신청 — 본인 승인 403, m1 승인은 0105 와 상충 409
           ("WP-0103", "hot", "Z3", "w2", at_h(0), at_h(2), "reviewed", F, "s1", "", "", "", ""),               # 다른 구역 — 승인 200
           ("WP-0104", "hot", "Z2", "w2", at_h(4), at_h(6), "reviewed", F, "s1", "", "", "", ""),               # 같은 구역, 시간 안 겹침 — 승인 200
           ("WP-0105", "confined", "Z2", "w1", at_h(-1), at_h(3), "approved", C, "s1", "m1", today_or(0.5), "", ""),   # 유효한 승인 — w1 작업 시작, 상충의 상대
           ("WP-0106", "height", "Z1", "w1", at_h(-10), at_h(-2), "approved", H, "s1", "m1", at_h(-9), "", ""),   # 승인 9시간 전 — 만료
           ("WP-0107", "height", "Z3", "w2", at_h(-3), at_h(1), "started", H, "s1", "m1", today_or(2), today_or(1.5), ""),   # 작업 중 — 승인자 종료
           ("WP-0108", "hot", "Z1", "w1", at_h(-6), at_h(-5), "closed", F, "s1", "m2", at_h(-6), at_h(-6), at_h(-5)),   # 종료된 건
           ("WP-0109", "confined", "Z3", "w2", at_h(1), at_h(3), "requested", C, "", "", "", "", ""),          # 검토 전 — 승인 409, T9 안전 담당 화면
           ("WP-0110", "height", "Z1", "w1", at_h(-2), at_h(2), "started", H, "s1", "m1", today_or(1), today_or(0.5), "")]   # 작업 중 — 신청자 종료
PERMIT_COLS = ["permit_id", "work_type", "zone_id", "requester_id", "start_at", "end_at", "status", "checked", "reviewed_by", "approved_by", "approved_at", "started_at", "closed_at"]


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("zones.csv", ["zone_id", "name"], ZONES),
              ("check_items.csv", ["work_type", "item_id", "name"], CHECK_ITEMS),
              ("permits.csv", PERMIT_COLS, PERMITS)]
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


def get(s, path, **q):
    return http("GET", s.base + path + ("?" + urllib.parse.urlencode(q) if q else ""))


def act(s, pid, what, user):
    return http("POST", s.base + "/api/permits/%s/%s" % (pid, what), {"user": user} if user is not None else {})


def create(s, user, work_type, zone, start, end, checked):
    return http("POST", s.base + "/api/permits", {"user": user, "work_type": work_type, "zone_id": zone, "start_at": start, "end_at": end, "checked": checked})


def detail_of(s, pid, viewer):
    st, b = get(s, "/api/permits/%s" % pid, viewer=viewer)
    assert st == 200 and isinstance(b, dict), ("GET /api/permits/%s" % pid, viewer, st, b)
    return b


def msg(b):
    return (b or {}).get("detail", "") if isinstance(b, dict) else str(b)


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


def near_now(ts, minutes=3):
    return abs((datetime.strptime(ts, FMT) - datetime.now()).total_seconds()) <= minutes * 60


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    pg = open_page(pw, srv)
    assert "허가" in pg.title() or "허가" in pg.inner_text("body")
    pg.close()


def test_T2_contract(srv):
    st, users = get(srv, "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {(u, r) for u, _, r in USERS}, users
    st, wt = get(srv, "/api/work-types")
    assert st == 200 and {w["work_type"]: sorted(i["item_id"] for i in w["items"]) for w in wt} == {"height": ["H1", "H2", "H3"], "hot": ["F1", "F2", "F3"], "confined": ["C1", "C2", "C3"]}, wt
    st, zs = get(srv, "/api/zones")
    assert st == 200 and [z["zone_id"] for z in zs] == ["Z1", "Z2", "Z3"], zs
    st, mine = get(srv, "/api/permits", viewer="w1")
    assert st == 200 and sorted(p["permit_id"] for p in mine) == ["WP-0101", "WP-0105", "WP-0106", "WP-0108", "WP-0110"], ("작업자는 자기 것만", st, mine)
    st, alls = get(srv, "/api/permits", viewer="m1")
    assert st == 200 and len(alls) == 10, ("책임자는 전부", st, alls)
    assert [p["permit_id"] for p in alls] == [p["permit_id"] for p in sorted(alls, key=lambda p: (p["start_at"], p["permit_id"]))], "start_at 순"
    d = detail_of(srv, "WP-0105", "w1")
    assert d["status"] == "approved" and d["zone_name"] == "지하 1층 기계실" and sorted(d["checked"]) == ["C1", "C2", "C3"] and d["approved_by"] == "m1", d
    assert d["valid_until"] == expected_valid_until(d["approved_at"]), ("valid_until = 승인 + 8시간(당일 상한)", d)
    st, b = get(srv, "/api/dashboard", viewer="m1")
    assert st == 200 and [z["zone_id"] for z in b["zones"]] == ["Z1", "Z2", "Z3"] and b["hours"][0] == 6 and b["hours"][-1] == 18, ("현황판 틀", st, b)
    z2 = {p["permit_id"] for z in b["zones"] if z["zone_id"] == "Z2" for p in z["permits"]}
    assert {"WP-0102", "WP-0105"} <= z2, ("Z2 의 오늘 허가", z2)
    allp = {p["permit_id"] for z in b["zones"] for p in z["permits"]}
    assert "WP-0108" not in allp, "종료된 건은 현황판에 없다"
    pairs = [sorted(c["permit_ids"]) for c in b["conflicts"]]
    assert ["WP-0102", "WP-0105"] in pairs, ("상충 쌍 — 지하 기계실의 화기(검토 완료)와 밀폐(승인)", b["conflicts"])


def test_T3_create(srv):
    st, b = create(srv, "w1", "hot", "Z1", at_h(1), at_h(3), ["F1", "F2"])
    assert st == 400 and "점검 항목" in msg(b), ("항목 하나 빠지면 400", st, b)
    st, b = create(srv, "w1", "weld", "Z1", at_h(1), at_h(3), ["F1", "F2", "F3"])
    assert st == 400 and "작업 종류" in msg(b), ("작업 종류 오타 400", st, b)
    st, b = create(srv, "w1", "height", "Z1", at_h(3), at_h(1), ["H1", "H2", "H3"])
    assert st == 400 and "종료" in msg(b), ("종료가 앞이면 400", st, b)
    st, b = create(srv, "w1", "height", "Z9", at_h(1), at_h(3), ["H1", "H2", "H3"])
    assert st == 404, ("없는 구역 404", st, b)
    st, b = create(srv, "w1", "height", "Z1", at_h(1), at_h(3), ["H1", "H2", "H3"])
    assert st == 201 and b["permit_id"] == "WP-0111" and b["status"] == "requested", ("201 · 번호는 최댓값 + 1", st, b)
    assert re.fullmatch(r"WP-\d{4}", b["permit_id"]), b["permit_id"]
    assert [p["permit_id"] for p in get(srv, "/api/permits", viewer="w1")[1] if p["permit_id"] == "WP-0111"], "목록에 새 허가"


def test_T4_order_and_roles(srv):
    st, b = act(srv, "WP-0101", "review", "w1")
    assert st == 403, ("작업자의 검토 403", st, b)
    st, b = act(srv, "WP-0101", "review", "s1")
    assert st == 200 and b["status"] == "reviewed" and b["reviewed_by"] == "s1", ("안전 담당 검토 200", st, b)
    st, b = act(srv, "WP-0101", "review", "s1")
    assert st == 409, ("두 번째 검토 409", st, b)
    st, b = act(srv, "WP-0101", "approve", "w1")
    assert st == 403, ("작업자의 승인 403", st, b)
    st, b = act(srv, "WP-0101", "approve", "m1")
    assert st == 200 and b["status"] == "approved" and b["approved_by"] == "m1", ("책임자 승인 200", st, b)
    assert near_now(b["approved_at"]) and b["valid_until"] == expected_valid_until(b["approved_at"]), ("valid_until = 승인 + 8시간, 당일 23:59 상한", b)
    assert detail_of(srv, "WP-0101", "w1")["status"] == "approved"
    st, b = act(srv, "WP-0109", "approve", "m1")
    assert st == 409 and "검토" in msg(b), ("검토 전 승인 409", st, b)
    st, b = act(srv, "WP-0102", "approve", "m2")
    assert st == 403 and "자기" in msg(b), ("신청자 본인(책임자)의 승인 403", st, b)


def test_T5_start_and_expiry(srv):
    st, b = act(srv, "WP-0109", "start", "w2")
    assert st == 409 and "승인 전" in msg(b), ("승인 전 시작 409", st, b)
    st, b = act(srv, "WP-0105", "start", "w2")
    assert st == 403, ("남이 시작 403", st, b)
    st, b = act(srv, "WP-0105", "start", "w1")
    assert st == 200 and b["status"] == "started" and near_now(b["started_at"]), ("신청자 시작 200", st, b)
    st, b = act(srv, "WP-0105", "start", "w1")
    assert st == 409, ("두 번째 시작 409", st, b)
    d = detail_of(srv, "WP-0106", "w1")
    assert d["status"] == "expired", ("승인 9시간 전인 허가는 응답에서 expired", d)
    assert d["valid_until"] == expected_valid_until(d["approved_at"]), d
    st, b = act(srv, "WP-0106", "start", "w1")
    assert st == 409 and "만료" in msg(b), ("만료된 허가로 작업 시작은 409", st, b)


def test_T6_conflict(srv):
    st, b = act(srv, "WP-0102", "approve", "m1")
    assert st == 409 and "상충" in msg(b) and "WP-0105" in msg(b), ("같은 구역 · 겹치는 시간의 화기를 밀폐 위에 승인하면 409", st, b)
    assert detail_of(srv, "WP-0102", "m1")["status"] == "reviewed", "거부됐으니 상태 그대로"
    st, b = act(srv, "WP-0103", "approve", "m1")
    assert st == 200 and b["status"] == "approved", ("다른 구역은 200", st, b)
    st, b = act(srv, "WP-0104", "approve", "m1")
    assert st == 200 and b["status"] == "approved", ("같은 구역이라도 시간이 안 겹치면 200", st, b)


def test_T7_close(srv):
    st, b = act(srv, "WP-0107", "close", "s1")
    assert st == 403, ("제3자 종료 403", st, b)
    st, b = act(srv, "WP-0107", "close", "m1")
    assert st == 200 and b["status"] == "closed" and near_now(b["closed_at"]), ("승인자 종료 200", st, b)
    st, b = act(srv, "WP-0110", "close", "w1")
    assert st == 200 and b["status"] == "closed", ("신청자 종료 200", st, b)
    st, b = act(srv, "WP-0107", "start", "w2")
    assert st == 409, ("종료 뒤 시작 409", st, b)
    st, b = act(srv, "WP-0107", "close", "m1")
    assert st == 409, ("두 번째 종료 409", st, b)
    st, b = act(srv, "WP-0103", "close", "w2")
    assert st == 409, ("승인만 된 건 종료 409", st, b)
    assert "WP-0107" not in {p["permit_id"] for z in get(srv, "/api/dashboard", viewer="m1")[1]["zones"] for p in z["permits"]}, "종료하면 현황판에서 빠진다"


def test_T8_reject_order(srv):
    st, b = act(srv, "WP-0109", "approve", None)
    assert st == 400, ("사용자 없음 400", st, b)
    st, b = act(srv, "WP-9999", "approve", "m1")
    assert st == 404, ("없는 허가 404", st, b)
    st, b = act(srv, "WP-9999", "approve", "w1")
    assert st == 404, ("없는 허가는 권한보다 먼저 404", st, b)
    st, b = act(srv, "WP-0109", "approve", "w1")
    assert st == 403, ("권한 403 은 상태 409 보다 먼저", st, b)
    st, b = act(srv, "WP-0106", "start", "w2")
    assert st == 403, ("남의 만료 허가 시작은 403 이 먼저", st, b)
    st, b = create(srv, "w1", "weld", "Z9", at_h(1), at_h(3), ["F1"])
    assert st == 400, ("작업 종류 오타 + 없는 구역은 본문 400 이 먼저", st, b)
    st, b = create(srv, "w1", "hot", "Z9", at_h(1), at_h(3), ["F1"])
    assert st == 404, ("없는 구역 + 항목 누락은 404 가 먼저", st, b)
    st, b = get(srv, "/api/dashboard", viewer="w1")
    assert st == 403, ("작업자의 현황판 403", st, b)
    st, b = get(srv, "/api/permits/WP-0103", viewer="w1")
    assert st == 403, ("작업자가 남의 건 조회 403", st, b)
    st, b = get(srv, "/api/permits", viewer="x9")
    assert st == 404, ("없는 사용자 404", st, b)


def test_T9_screen(srv, pw):
    pg = open_page(pw, srv)
    pg.select_option('[data-testid="user"]', "m1")
    pg.wait_for_timeout(1200)
    assert pg.query_selector('[data-testid="grid"]') is not None, "책임자에게 현황판 격자가 없다"
    cells = pg.query_selector_all('[data-testid="cell"]')
    assert len(cells) >= 13 * 3, ("격자 칸이 모자라다", len(cells))
    assert pg.query_selector('[data-testid="conflict"]') is not None, "상충 경고가 없다 (WP-0102 · WP-0105)"
    pg.select_option('[data-testid="user"]', "w1")
    pg.wait_for_timeout(1000)
    assert pg.query_selector('[data-testid="grid"]') is None, "작업자에게 격자가 보인다"
    row = pg.query_selector('[data-testid="permit"][data-id="WP-0101"]')
    assert row is not None, "WP-0101 줄이 없다"
    row.click()
    pg.wait_for_timeout(800)
    assert pg.query_selector('[data-testid="start"]') is not None, "승인된 자기 허가에 작업 시작 단추가 없다"
    pg.click('[data-testid="start"]')
    pg.wait_for_timeout(1200)
    assert detail_of(srv, "WP-0101", "w1")["status"] == "started", "화면의 작업 시작이 서버에 반영되지 않았다"
    pg.select_option('[data-testid="user"]', "s1")
    pg.wait_for_timeout(1000)
    row = pg.query_selector('[data-testid="permit"][data-id="WP-0109"]')
    assert row is not None, "안전 담당에게 WP-0109 줄이 없다"
    row.click()
    pg.wait_for_timeout(800)
    assert pg.query_selector('[data-testid="review"]') is not None, "신청 건에 검토 단추가 없다"
    assert pg.query_selector('[data-testid="approve"]') is None, "안전 담당에게 승인 단추가 보인다"
    pg.close()
