# -*- coding: utf-8 -*-
"""렌더가 끝나길 기다렸다가 챕터 동기화 · 검수 프레임을 만든다 (셸 반복문 대신).
사용: python _scratch/s2s/tools/after_render.py <ep> [초 ...]     기본 프레임 100 110 120 130, 최대 90분 대기"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import config as C   # noqa: E402

ep = sys.argv[1]
secs = sys.argv[2:] or ["100", "110", "120", "130"]
video = os.path.join(C.ep_dir(ep), "video.mp4")
log = os.path.join(ROOT, "_scratch", "aieng", "render_%s.log" % ep)
t0 = time.time()
while time.time() - t0 < 90 * 60:
    if os.path.exists(video) and os.path.getmtime(video) > t0 - 120:
        break
    if os.path.exists(log) and os.path.getmtime(log) > t0 and "렌더를 중단" in open(log, encoding="utf-8", errors="ignore").read():
        print("렌더 중단됨 — 로그:", log)
        sys.exit(1)
    time.sleep(15)
else:
    print("90분 안에 영상이 생기지 않음")
    sys.exit(1)
print("영상:", video, "%.1f MB" % (os.path.getsize(video) / 1e6))
env = dict(os.environ, PYTHONUTF8="1")
tools = os.path.join(ROOT, "_scratch", "aieng", "tools")
for cmd in ([sys.executable, os.path.join(tools, "sync_chapters.py"), ep],
            [sys.executable, os.path.join(tools, "review_video.py"), ep] + secs):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    print("\n".join((r.stdout + r.stderr).strip().splitlines()[-6:]))
