# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 2부 1편 — 불량 신고 · 조치 추적판 DoD(완료 기준) 테스트 T1~T9.
이 파일이 곧 채점기다. 빌더(AI)에게 그대로 주고, 채점할 때도 원본 사본으로 다시 돈다.

실행: python -m pytest tests -q            (프로젝트 루트에서. 서버는 테스트가 띄운다)
환경: APP_DIR  검사할 프로젝트 루트 (기본: 이 파일의 상위 폴더)
      PORT     테스트 서버 포트 (기본 8765)

데이터 계약(PRD 5 데이터): seed/users · lots · symptoms · causes · defects .csv 를 서버가 시작할 때 읽는다.
테스트는 seed/ 를 자기 고정 데이터로 바꿔 쓰고(원래 파일은 seed_backup/ 에 보관) 끝나면 되돌린다.
고정 데이터의 날짜는 **테스트를 돌리는 날(오늘 = D)** 기준. 서버 하나를 T1~T9 가 차례로 쓴다 — 앞 테스트의 결과(신고 · 상태 변화)를 뒤 테스트가 전제로 한다.
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
import urllib.request
from datetime import date, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))

# ── 고정 데이터 (정답을 아는 값) — 모두 가상(콩알반도체는 가상 회사), 날짜는 오늘(D) 기준 ──
D = date.today()


def day(n):
    return (D - timedelta(days=n)).isoformat()


def at(n, hm):
    return "%s %s" % (day(n), hm)


USERS = [("w1", "김작업", "worker"), ("w2", "이작업", "worker"),
         ("q1", "박품질", "quality"), ("q2", "최품질", "quality"), ("q3", "정품질", "quality")]
LOTS = [("L-1001", "콩알칩 A", "1라인", 500), ("L-1002", "콩알칩 A", "2라인", 300),
        ("L-1003", "콩알칩 B", "1라인", 200), ("L-1004", "콩알센서", "3라인", 50)]
SYMPTOMS = [("S01", "외관 스크래치"), ("S02", "치수 불량"), ("S03", "전기 특성 불량"), ("S04", "이물")]
CAUSES = [("C01", "장비"), ("C02", "자재"), ("C03", "작업"), ("C04", "설계"), ("C05", "미상")]
# defect_id, lot_id, symptom, severity, qty, status, reporter, assignee, cause, reported_at, rework
DEFECTS = [("F001", "L-1001", "S01", "중", 5, "reported", "q1", "", "", at(0, "09:00"), 0),      # T4~T6 흐름 (신고자가 품질팀)
           ("F002", "L-1002", "S02", "중", 3, "reported", "w2", "", "", at(4, "10:00"), 0),      # 중 · 4일 전 → 기한 넘김
           ("F003", "L-1003", "S03", "치명", 1, "closed", "w1", "q2", "C01", at(10, "08:00"), 0),   # 종결 — 기한 지났어도 넘김 아님
           ("F004", "L-1001", "S04", "경", 2, "fixing", "w1", "q1", "C03", at(7, "09:30"), 0),    # 경 · 7일 전 → 기한 당일, 넘김 아님
           ("F005", "L-1004", "S01", "치명", 10, "verifying", "w1", "q3", "C02", at(1, "14:00"), 0),  # 치명 · 어제 → 기한 오늘
           ("F006", "L-1002", "S03", "경", 1, "fixing", "w2", "q2", "C05", at(2, "11:00"), 1)]     # 재작업 1


def write_seed():
    seed = os.path.join(APP, "seed")
    bak = os.path.join(APP, "seed_backup")
    if os.path.isdir(seed) and not os.path.isdir(bak):
        shutil.copytree(seed, bak)
    os.makedirs(seed, exist_ok=True)
    tables = [("users.csv", ["user_id", "name", "role"], USERS),
              ("lots.csv", ["lot_id", "product", "line", "qty"], LOTS),
              ("symptoms.csv", ["code", "label"], SYMPTOMS),
              ("causes.csv", ["code", "label"], CAUSES),
              ("defects.csv", ["defect_id", "lot_id", "symptom", "severity", "qty", "status", "reporter", "assignee", "cause", "reported_at", "rework"], DEFECTS)]
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


def act(s, did, action, body):
    return http("POST", s.base + "/api/defects/%s/%s" % (did, action), body)


def report(s, user, lot, symptom, severity, qty):
    return http("POST", s.base + "/api/defects", {"user": user, "lot_id": lot, "symptom": symptom, "severity": severity, "qty": qty})


def board(s):
    st, body = http("GET", s.base + "/api/defects")
    assert st == 200 and isinstance(body, dict) and "defects" in body and "summary" in body, ("GET /api/defects", st, body)
    return body


def one(s, did):
    for d in board(s)["defects"]:
        if d["defect_id"] == did:
            return d
    return None


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


# ── T1~T9 ────────────────────────────────────────────────────────────────────
def test_T1_page_loads(srv, pw):
    pg = open_page(pw, srv)
    assert "불량" in pg.title() or "불량" in pg.inner_text("body")
    pg.close()


def test_T2_contract(srv):
    st, users = http("GET", srv.base + "/api/users")
    assert st == 200 and {(u["user_id"], u["role"]) for u in users} == {(u, r) for u, _, r in USERS}, users
    st, lots = http("GET", srv.base + "/api/lots")
    assert st == 200 and {(l["lot_id"], l["qty"]) for l in lots} == {(l, q) for l, _, _, q in LOTS}, lots
    b = board(srv)
    ids = [d["defect_id"] for d in b["defects"]]
    assert ids == ["F003", "F004", "F002", "F006", "F005", "F001"], ("신고 시각 오래된 순", ids)
    d = {x["defect_id"]: x for x in b["defects"]}
    assert {x["status"] for x in b["defects"]} == {"reported", "fixing", "verifying", "closed"}
    assert d["F001"]["assignee"] is None and d["F001"]["cause"] is None, ("빈칸은 null", d["F001"])
    assert (d["F004"]["product"], d["F004"]["line"], d["F004"]["due"]) == ("콩알칩 A", "1라인", day(0)), d["F004"]
    assert b["summary"] == {"open": 5, "overdue": 1, "rework": 1}, b["summary"]


def test_T3_report(srv):
    st, body = report(srv, "w1", "L-1001", "S01", "중", 0)
    assert st == 400, ("수량 0 은 400", st, body)
    st, body = report(srv, "w1", "L-1001", "S01", "중", 501)
    assert st == 400, ("로트 수량(500) 초과는 400", st, body)
    st, body = report(srv, "w1", "L-9999", "S01", "중", 1)
    assert st == 404, ("없는 로트는 404", st, body)
    st, body = report(srv, "w1", "L-1001", "S99", "중", 1)
    assert st == 400, ("없는 증상은 400", st, body)
    st, body = report(srv, "w1", "L-1001", "S01", "엄청", 1)
    assert st == 400, ("심각도는 세 값 중 하나", st, body)
    st, body = report(srv, "w1", "L-1002", "S02", "중", 1)
    assert st == 409, ("같은 로트 · 증상의 미종결 건(F002)이 있으면 409", st, body)
    st, body = report(srv, "w1", "L-1003", "S03", "치명", 1)
    assert st == 201 and body.get("defect_id") and body["status"] == "reported", ("종결된 F003 과 같은 로트 · 증상은 된다", st, body)
    assert body["due"] == day(-1), ("치명은 기한이 내일", body.get("due"))
    assert body["defect_id"] not in {x[0] for x in DEFECTS}, "새 id 는 기존과 겹치지 않는다"
    assert board(srv)["summary"]["open"] == 6


def test_T4_analyze(srv):
    st, body = act(srv, "F001", "analyze", {"user": "w1", "cause": "C01", "assignee": "q2"})
    assert st == 403, ("작업자의 원인 분석은 403", st, body)
    st, body = act(srv, "F001", "analyze", {"user": "q1", "cause": "C99", "assignee": "q2"})
    assert st == 400, ("없는 원인은 400", st, body)
    st, body = act(srv, "F001", "analyze", {"user": "q1", "cause": "C01", "assignee": "w2"})
    assert st == 400, ("작업자를 담당으로는 400", st, body)
    st, body = act(srv, "F001", "analyze", {"user": "q1", "cause": "C01", "assignee": "q2"})
    assert st == 200 and body["status"] == "fixing" and body["assignee"] == "q2" and body["cause"] == "C01", (st, body)


def test_T5_fix(srv):
    st, body = act(srv, "F001", "fix", {"user": "q3", "note": "리플로우 온도 재설정"})
    assert st == 403, ("담당자가 아닌 품질팀은 403", st, body)
    st, body = act(srv, "F001", "fix", {"user": "q2", "note": "   "})
    assert st == 400, ("빈 조치 내용은 400", st, body)
    st, body = act(srv, "F005", "fix", {"user": "q3", "note": "다시 등록"})
    assert st == 409, ("검증 대기 건에 다시 조치 등록은 409", st, body)
    st, body = act(srv, "F001", "fix", {"user": "q2", "note": "리플로우 온도 재설정"})
    assert st == 200 and body["status"] == "verifying", (st, body)


def test_T6_verify_third_party(srv):
    st, body = act(srv, "F001", "verify", {"user": "q2", "result": "pass"})
    assert st == 403, ("담당자 본인의 검증은 403", st, body)
    st, body = act(srv, "F001", "verify", {"user": "q1", "result": "pass"})
    assert st == 403, ("신고자의 검증은 403", st, body)
    st, body = act(srv, "F001", "verify", {"user": "w1", "result": "pass"})
    assert st == 403, ("작업자의 검증은 403", st, body)
    st, body = act(srv, "F001", "verify", {"user": "q3", "result": "fail"})
    assert st == 200 and body["status"] == "fixing" and body["rework"] == 1, ("실패는 조치 중으로, rework 1", st, body)
    st, body = act(srv, "F001", "fix", {"user": "q2", "note": "노즐 교체"})
    assert st == 200 and body["status"] == "verifying", (st, body)
    st, body = act(srv, "F001", "verify", {"user": "q3", "result": "pass"})
    assert st == 200 and body["status"] == "closed" and body["rework"] == 1, (st, body)


def test_T7_overdue(srv):
    b = board(srv)
    d = {x["defect_id"]: x for x in b["defects"]}
    assert d["F002"]["overdue"] is True, ("중 · 4일 전 신고(기한 어제)는 넘김", d["F002"])
    assert d["F004"]["overdue"] is False, ("경 · 7일 전 신고(기한 오늘)는 넘김 아님", d["F004"])
    assert d["F003"]["overdue"] is False, ("종결은 기한이 지났어도 넘김 아님", d["F003"])
    assert d["F005"]["overdue"] is False and d["F001"]["overdue"] is False
    assert b["summary"] == {"open": 5, "overdue": 1, "rework": 2}, ("open = 종결 아닌 건, rework = 전체 합", b["summary"])


def test_T8_reject_order(srv):
    st, body = act(srv, "F999", "verify", {})
    assert st == 400, ("본문에 user 없음 + 없는 건은 400 이 먼저", st, body)
    st, body = act(srv, "F999", "verify", {"user": "q3", "result": "pass"})
    assert st == 404, ("없는 건은 404", st, body)
    st, body = act(srv, "F002", "verify", {"user": "nobody", "result": "pass"})
    assert st == 404, ("없는 사용자는 404", st, body)
    st, body = act(srv, "F003", "verify", {"user": "w1", "result": "pass"})
    assert st == 403, ("작업자가 종결 건을 검증하면 권한(403)이 상태(409)보다 먼저", st, body)
    st, body = act(srv, "F003", "verify", {"user": "q3", "result": "pass"})
    assert st == 409, ("품질팀이 종결 건을 검증하면 409", st, body)


def test_T9_screen(srv, pw):
    pg = open_page(pw, srv)
    row = pg.query_selector('[data-testid="defect"][data-id="F002"]')
    assert row is not None and row.get_attribute("data-status") == "reported", "F002 줄(data-status=reported)이 없다"
    assert row.get_attribute("data-overdue") == "1", "기한 넘긴 F002 에 data-overdue=1 이 없다"
    assert row.query_selector('[data-testid="act-analyze"]') is None, "작업자(첫 사용자)에게 원인 분석 버튼이 보인다"
    pg.select_option('[data-testid="user"]', "q1")
    pg.wait_for_timeout(1200)
    row = pg.query_selector('[data-testid="defect"][data-id="F002"]')
    assert row is not None and row.query_selector('[data-testid="act-analyze"]') is not None, "품질팀에게 신고 건의 원인 분석 버튼이 없다"
    pg.select_option('[data-testid="user"]', "q3")
    pg.wait_for_timeout(1200)
    row = pg.query_selector('[data-testid="defect"][data-id="F005"]')
    assert row is not None and row.query_selector('[data-testid="act-pass"]') is None, "담당자 본인(q3)에게 자기 건(F005)의 검증 버튼이 보인다"
    so = pg.query_selector('[data-testid="sum-open"]')
    assert so is not None and digits(so.inner_text()), "요약 숫자가 없다"
    pg.fill('[data-testid="qty"]', "0")
    pg.click('[data-testid="report"]')
    pg.wait_for_timeout(1000)
    msg = pg.query_selector('[data-testid="message"]')
    assert msg is not None and "수량을 확인하세요" in msg.inner_text(), ("수량 0 → 서버의 detail", msg.inner_text() if msg else None)
    pg.close()
