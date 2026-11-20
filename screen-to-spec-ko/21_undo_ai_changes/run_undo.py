# -*- coding: utf-8 -*-
"""ep098 — AI 가 고쳐서 달라진 앱(broken/)에서 "원래대로 되돌려 줘" 를 세 조건으로 시킨다. tools/run_build.py 의 build() 를 그대로 쓴다.

단계:
  break   base/ 를 임시 폴더(<임시>/s2s_runs/21_undo_ai_changes/U1/app)에 놓고 BREAK 요청 1회 → broken/ (+ broken/build.json 에 session_id)
  U1      같은 폴더를 broken 상태로 되돌려 놓고 그 대화를 이어서(--resume <id> --fork-session) "방금 바꾼 거 전부 원래대로"
  U2      새 폴더에 broken 만, 새 대화
  U3      새 폴더에 base 를 git commit("AI 시키기 전") 한 뒤 broken 을 덮어씀(.git 있음), 새 대화
사용(윈도우는 pythonw): pythonw -u _scratch/s2s/21_undo_ai_changes/run_undo.py break > _scratch/s2s/21_undo_ai_changes/build_log_break.txt 2>&1
                        pythonw -u _scratch/s2s/21_undo_ai_changes/run_undo.py U1 U2 U3 [--trials=3] [--only=U2_1] > _scratch/s2s/21_undo_ai_changes/build_log.txt 2>&1
결과: 21_undo_ai_changes/runs/<U1_1 …>/ + build.json (U3 은 git_before · git_after 도)
한 번에 하나씩 돈다(U1 이 같은 폴더를 써야 해서). 포트 묶음 · 덧붙임 한 줄(PARALLEL_NOTE)은 모든 실행에 같다."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import run_build   # noqa: E402
from port_block import BUILD_BASE, PortBlock   # noqa: E402

IGNORE = shutil.ignore_patterns("__pycache__", "*.db", ".pytest_cache", ".git", "_tmp")
# 이 PC 의 사용자 설정(플러그인 · 훅 · MCP)을 빌더가 읽지 않게 (ep097 실수 1)
EXTRA = ["--setting-sources", "project,local", "--strict-mcp-config"]
MORE = []
_popen = run_build.subprocess.Popen


def popen(cmd, *a, **k):
    if isinstance(cmd, list) and len(cmd) > 1 and cmd[1] == "-p":
        cmd = cmd + ([] if "--setting-sources" in cmd else EXTRA) + MORE   # run_build 가 이미 붙이면 두 번 붙이지 않는다
    return _popen(cmd, *a, **k)


run_build.subprocess.Popen = popen


def clear(work):
    """폴더 자체(와 .git)는 두고 안의 것만 지운다"""
    os.makedirs(work, exist_ok=True)
    for n in os.listdir(work):
        if n == ".git":
            continue
        p = os.path.join(work, n)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)


def put(src, work):
    for n in os.listdir(src):
        if n == "build.json":
            continue
        s, d = os.path.join(src, n), os.path.join(work, n)
        shutil.copytree(s, d, ignore=IGNORE) if os.path.isdir(s) else shutil.copy(s, d)


def git(work, *args):
    r = subprocess.run(["git", "-c", "user.name=lab", "-c", "user.email=lab@example.com"] + list(args), cwd=work,
                       capture_output=True, text=True, encoding="utf-8", errors="ignore", creationflags=run_build.NO_WINDOW)
    return (r.stdout + r.stderr).strip()


def run(claude, root, work, prompt, extra):
    MORE[:] = extra
    base = os.path.dirname(work)
    tmp = os.path.join(base, "_tmp")
    os.makedirs(tmp, exist_ok=True)
    run_build.check_parents(base)
    block = PortBlock(BUILD_BASE)
    try:
        return run_build.build(claude, work, prompt, "sonnet", 80, 1500, block, tmp, root)
    finally:
        block.close()


def keep(work, final):
    shutil.rmtree(final, ignore_errors=True)
    shutil.copytree(work, final, ignore=IGNORE)


def main():
    steps = [a for a in sys.argv[1:] if not a.startswith("--")]
    trials, only = 3, None
    for a in sys.argv[1:]:
        if a.startswith("--trials="):
            trials = int(a.split("=", 1)[1])
        elif a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
    prompts = json.load(open(os.path.join(HERE, "prompts.json"), encoding="utf-8"))
    claude = run_build.find_claude()
    root = run_build.neutral_root()
    labroot = os.path.join(root, "21_undo_ai_changes")
    u1_work = os.path.join(labroot, "U1", "app")
    broken = os.path.join(HERE, "broken")
    for step in steps:
        if step == "break":
            shutil.rmtree(os.path.join(labroot, "U1"), ignore_errors=True)
            clear(u1_work)
            put(os.path.join(HERE, "base"), u1_work)
            info = run(claude, root, u1_work, prompts["BREAK"], [])
            keep(u1_work, broken)
            run_build.say("break rc=%s 턴=%s %.0f초 $%.2f 세션=%s" % (info.get("rc"), info.get("num_turns"), info["wall_s"], info.get("total_cost_usd") or 0, info.get("session_id")))
            continue
        sid = json.load(open(os.path.join(broken, "build.json"), encoding="utf-8"))["session_id"]
        for k in range(1, trials + 1):
            name = "%s_%d" % (step, k)
            if only and name not in only:
                continue
            extra, more = [], {}
            if step == "U1":
                work = u1_work
                clear(work)
                put(broken, work)
                extra = ["--resume", sid, "--fork-session"]
            else:
                shutil.rmtree(os.path.join(labroot, name), ignore_errors=True)
                work = os.path.join(labroot, name, "app")
                os.makedirs(work)
                if step == "U3":
                    put(os.path.join(HERE, "base"), work)
                    git(work, "init", "-q")
                    git(work, "config", "core.autocrlf", "false")   # 줄 끝을 바꿔 쓰면 지문이 달라진다 — 내용 비교가 목적이라 끈다
                    git(work, "add", "-A")
                    git(work, "commit", "-q", "-m", "AI 시키기 전")
                    clear(work)
                put(broken, work)
                if step == "U3":
                    more["git_before"] = {"status": git(work, "status", "--porcelain"), "log": git(work, "log", "--oneline")}
            run_build.say("%s 시작" % name)
            info = run(claude, root, work, prompts[step], extra)
            if step == "U3":
                more["git_after"] = {"status": git(work, "status", "--porcelain"), "log": git(work, "log", "--oneline"), "stash": git(work, "stash", "list")}
            final = os.path.join(HERE, "runs", name)
            keep(work, final)
            if more:
                b = os.path.join(final, "build.json")
                j = json.load(open(b, encoding="utf-8"))
                j.update(more)
                json.dump(j, open(b, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            iso = info.get("isolation") or {}
            warn = {x: iso[x] for x in ("foreign_ports", "kill_by_name", "outside_refs") if iso.get(x)}
            run_build.say("%s rc=%s 턴=%s %.0f초 $%.2f%s" % (name, info.get("rc"), info.get("num_turns"), info["wall_s"], info.get("total_cost_usd") or 0,
                                                         " [격리 흔적 %s]" % json.dumps(warn, ensure_ascii=False)[:400] if warn else ""))
            if step != "U1":
                shutil.rmtree(os.path.join(labroot, name), ignore_errors=True)


if __name__ == "__main__":
    main()
