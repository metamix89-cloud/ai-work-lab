# -*- coding: utf-8 -*-
"""테스트 틀 — 서버 띄우기 · 고정 데이터 · HTTP 도우미. (이 파일은 바꾸지 않는다)

픽스처
  srv   FastAPI 앱(main.py 의 app)을 uvicorn 으로 띄운다. srv.base 가 주소("http://127.0.0.1:포트").
        시작 전에 seed/ 를 아래 고정 데이터로 바꿔 끼우고, 끝나면 되돌린다.
  pw    Playwright 크로미움 브라우저 (화면 검사용). page = pw.new_page()
도우미
  http(method, url, body=None) → (상태 코드, JSON 또는 글자). 4xx 도 예외 없이 돌려준다.
상수
  DATE · ROOMS · USERS · RES  — 서버가 시작할 때 읽는 고정 데이터
환경: APP_DIR(앱 루트, 기본은 이 폴더의 상위) · PORT(기본 8765)
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

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.environ.get("APP_DIR") or os.path.dirname(HERE))
PORT = int(os.environ.get("PORT", "8765"))
DATE = "2026-11-03"

# 고정 데이터 — seed/rooms.csv · seed/users.csv · seed/reservations.csv
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
        self._out = None

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
        self._out = tempfile.TemporaryFile()
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", self.target, "--port", str(self.port)],
                                     cwd=APP, env=env, stdout=self._out, stderr=subprocess.STDOUT)
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
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=10)
        if self._out:
            try:
                self._out.seek(0)
                self.log = self._out.read().decode("utf-8", "ignore")
            except Exception:
                pass
            self._out.close()
        restore_seed()


def http(method, url, body=None):
    """(status, json|text). 4xx 도 예외 없이 돌려준다. 주소 속 한글(?user=김민수)은 퍼센트 부호로 바꿔 보낸다."""
    url = urllib.parse.quote(url, safe=":/?=&%+,;@!$'()*[]~-._")   # 2026-11-06 틀 손질: 한글을 그대로 넣으면 urllib 이 UnicodeEncodeError
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
