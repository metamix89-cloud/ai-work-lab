# -*- coding: utf-8 -*-
"""앱 폴더를 uvicorn 으로 띄워 / 와 /api/summary 를 한 번씩 받아 보고 서버 로그를 보여 준다 (채점기 디버그용).
사용: python _scratch/s2s/tools/probe_app.py <app_dir> [port] [경로 ...]   (경로 기본: / /api/summary /)"""
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
app_dir = os.path.abspath(sys.argv[1])
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8899
env = dict(os.environ, PORT=str(port), PYTHONUTF8="1")
env.pop("CLAUDECODE", None)
p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)], cwd=app_dir, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    # Git Bash 는 '/api/..' 인자를 윈도우 경로로 바꾸므로 앞의 '/' 없이 받아도 된다 (api/products → /api/products)
    # 'POST:api/carts' 처럼 앞에 POST: 를 붙이면 빈 JSON 본문으로 POST
    for raw in (sys.argv[3:] or ["/", "/api/summary", "/"]):
        method = "GET"
        if raw.startswith("POST:"):
            method, raw = "POST", raw[5:]
        path = "/" + raw.split("/", 3)[-1] if ":" in raw[:3] else "/" + raw.lstrip("/")
        for _ in range(40):
            try:
                t0 = time.time()
                req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                             data=b"{}" if method == "POST" else None, headers={"Content-Type": "application/json"})
                r = urllib.request.urlopen(req, timeout=8)
                body = r.read()
                print(path, r.status, len(body), "bytes", "%.2fs" % (time.time() - t0), body[:160])
                break
            except Exception as e:
                if "Connection refused" in str(e) or "10061" in str(e):
                    time.sleep(0.5)
                    continue
                print(path, "오류:", e)
                break
finally:
    p.kill()
    out = p.communicate(timeout=5)[0]
    print("---- 서버 로그 ----")
    print(out.decode("utf-8", "ignore")[-3000:])
