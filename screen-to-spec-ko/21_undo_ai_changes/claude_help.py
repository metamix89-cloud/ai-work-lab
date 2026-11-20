# -*- coding: utf-8 -*-
"""claude --help 에서 낱말이 든 줄과 그 아래 2줄을 보여 준다 (--resume · --fork-session 확인용).
사용: python _scratch/s2s/21_undo_ai_changes/claude_help.py resume fork session"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import run_build   # noqa: E402

c = run_build.find_claude()
env = dict(os.environ)
for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
    env.pop(k, None)
r = subprocess.run([c, "--help"], capture_output=True, text=True, encoding="utf-8", errors="ignore", env=env, timeout=60)
lines = r.stdout.splitlines()
words = [w.lower() for w in sys.argv[1:]]
for i, ln in enumerate(lines):
    if any(w in ln.lower() for w in words):
        print("\n".join(lines[i:i + 3]))
        print("--")
