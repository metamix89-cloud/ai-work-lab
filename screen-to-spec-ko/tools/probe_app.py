# -*- coding: utf-8 -*-
"""앱 폴더를 uvicorn 으로 띄워 / 와 /api/summary 를 한 번씩 받아 보고 서버 로그를 보여 준다 (채점기 디버그용).
사용: python _scratch/s2s/tools/probe_app.py <app_dir> [port]"""
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
    for path in ("/", "/api/summary", "/"):
        for _ in range(40):
            try:
                t0 = time.time()
                r = urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5)
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
