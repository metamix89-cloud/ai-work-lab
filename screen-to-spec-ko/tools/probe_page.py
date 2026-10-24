# -*- coding: utf-8 -*-
"""앱을 띄우고 화면(/)을 브라우저로 한 번 연 뒤, API 를 다시 불러 매달리는지 본다 (화면 JS 가 남긴 잠금 조사용).
사용: python _scratch/s2s/tools/probe_page.py <app_dir> <port> <api 경로 ...>   (경로는 앞 '/' 없이)"""
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

app_dir, port = os.path.abspath(sys.argv[1]), int(sys.argv[2])
paths = ["/" + p.lstrip("/") for p in sys.argv[3:]]
env = dict(os.environ, PORT=str(port), PYTHONUTF8="1")
p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)], cwd=app_dir, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    time.sleep(3)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        msgs = []
        pg.on("console", lambda m: msgs.append(m.text))
        pg.on("requestfinished", lambda r: msgs.append("완료 %s %s" % (r.method, r.url)))
        pg.on("requestfailed", lambda r: msgs.append("실패 %s %s" % (r.method, r.url)))
        pg.goto("http://127.0.0.1:%d/" % port, wait_until="load", timeout=15000)
        pg.wait_for_timeout(2000)
        print("\n".join(msgs))
        pg.close()
        b.close()
    for path in paths:
        t0 = time.time()
        try:
            r = urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=8)
            print(path, r.status, "%.2fs" % (time.time() - t0))
        except Exception as e:
            print(path, "오류", e, "%.2fs" % (time.time() - t0))
finally:
    p.kill()
    print("---- 서버 로그 ----")
    print(p.communicate(timeout=5)[0].decode("utf-8", "ignore")[-3000:])
