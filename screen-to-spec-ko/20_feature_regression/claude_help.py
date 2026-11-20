# -*- coding: utf-8 -*-
"""빌더로 쓰는 claude 실행 파일의 버전과 도움말을 본다 (플러그인 · 설정을 끄는 옵션을 찾으려고).
사용: python _scratch/s2s/20_feature_regression/claude_help.py"""
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
for args in (["--version"], ["--help"]):
    r = subprocess.run([c] + args, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=env, timeout=60)
    print(r.stdout[-9000:], r.stderr[-500:])
