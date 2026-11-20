# -*- coding: utf-8 -*-
"""ep097 — 이미 돌고 있는 앱(base/)에 기능 하나를 더하게 한다. tools/run_build.py 의 빌더를 그대로 쓰고, 폴더 준비만 바꾼다.

조건 (prompts.json):
  M1 채팅 한 줄          base 의 main.py · static/ · seed/ 만 (PRD · CLAUDE.md · tests 없음 — 문서를 서랍에 넣어 둔 상황)
  M2 한 줄 + 당부        M1 과 같은 폴더, 요청에 "기존 기능은 하나도 깨지지 않게, 바꾼 파일을 알려 줘"
  M3 PRD 갱신            M1 폴더 + PRD.md(PRD_v2.md) + CLAUDE.md(CLAUDE_v2.md) + tests/test_dod.py(기존 9개. 새 T10~T12 테스트는 주지 않는다)
사용(윈도우는 pythonw): pythonw -u _scratch/s2s/20_feature_regression/run_modify.py [--conds=M1,M2,M3] [--trials=3] [--only=M1_1] [--workers=3] > _scratch/s2s/20_feature_regression/build_log.txt 2>&1
결과: 20_feature_regression/runs/<M1_1 …>/ + build.json"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import run_build   # noqa: E402


def prepare(lab, cond, run_dir):
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    base = os.path.join(lab, "base")
    shutil.copy(os.path.join(base, "main.py"), run_dir)
    shutil.copytree(os.path.join(base, "static"), os.path.join(run_dir, "static"))
    shutil.copytree(os.path.join(base, "seed"), os.path.join(run_dir, "seed"))
    if cond == "M3":
        shutil.copy(os.path.join(lab, "PRD_v2.md"), os.path.join(run_dir, "PRD.md"))
        shutil.copy(os.path.join(lab, "CLAUDE_v2.md"), os.path.join(run_dir, "CLAUDE.md"))
        os.makedirs(os.path.join(run_dir, "tests"))
        shutil.copy(os.path.join(lab, "tests", "test_dod.py"), os.path.join(run_dir, "tests"))


# 이 PC 의 사용자 설정(설치한 플러그인 · 훅 · MCP)을 빌더가 읽지 않게 한다.
# 첫 9회(2026-11-15)는 superpowers 플러그인의 시작 훅이 끼어들어 M1 셋이 코드를 안 고치고 되묻기만 했다 → runs_contaminated_plugin/.
# 프로젝트 폴더의 CLAUDE.md(M3)는 그대로 읽힌다.
EXTRA = ["--setting-sources", "project,local", "--strict-mcp-config"]
_popen = run_build.subprocess.Popen


def popen(cmd, *a, **k):
    if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "-p" and "--setting-sources" not in cmd:
        cmd = cmd + EXTRA   # run_build 가 이미 붙이면(2026-11-15 뒤) 두 번 붙이지 않는다
    return _popen(cmd, *a, **k)


run_build.subprocess.Popen = popen
run_build.prepare = prepare
args = [a for a in sys.argv[1:]]
if not any(a.startswith("--conds=") for a in args):
    args.append("--conds=M1,M2,M3")
sys.argv = [sys.argv[0], HERE] + args
run_build.main()
