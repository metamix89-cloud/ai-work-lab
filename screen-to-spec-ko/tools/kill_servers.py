# -*- coding: utf-8 -*-
"""테스트 · 빌더가 남긴 uvicorn(python) 서버를 정리한다 — 8000~8999 포트에서 듣고 있는 python 프로세스만.
사용: python _scratch/s2s/tools/kill_servers.py [--dry]"""
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
dry = "--dry" in sys.argv
out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
pids = set()
for line in out.splitlines():
    m = re.match(r"\s*TCP\s+\S+:(8\d{3})\s+\S+\s+LISTENING\s+(\d+)", line)
    if m:
        pids.add((m.group(1), m.group(2)))
n = 0
for port, pid in sorted(pids):
    info = subprocess.run(["tasklist", "/FI", "PID eq %s" % pid, "/FO", "CSV", "/NH"], capture_output=True, text=True,
                          encoding="utf-8", errors="ignore").stdout
    if "python" not in info.lower():
        continue
    print("포트 %s · PID %s · python%s" % (port, pid, "" if dry else " → 종료"))
    if not dry:
        subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True)
    n += 1
print("정리한 서버 %d개" % n)
