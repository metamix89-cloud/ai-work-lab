# -*- coding: utf-8 -*-
"""Claude Code(비대화 `claude -p`)로 같은 화면을 조건별로 만들게 한다 — 「이 화면, PRD 로는 이렇게」 실측 빌더.

조건 (lab_dir/prompts.json 에 정의):
  A 한 줄 요청           빈 폴더 + 한 줄
  B PRD 만              PRD.md 복사 + "PRD 대로 만들어 줘"
  C PRD + CLAUDE.md     PRD.md · CLAUDE.md · tests/ 복사 (완료 기준이 코드로 들어감)
사용: python _scratch/s2s/tools/run_build.py <lab_dir> [--conds=A,B,C] [--trials=3] [--model=sonnet] [--only=A1,C2] [--max-turns=80]
  → lab_dir/runs/<cond><n>/ 에 생성물 + build.json(비용 · 시간 · 턴 · 마지막 답)
Claude Code 실행 파일: 환경 변수 CLAUDE_BIN, 없으면 PATH 의 claude, 없으면 데스크톱 앱이 번들한 것을 찾는다.

윈도우에서는 pythonw.exe 로 돌린다(출력은 파일로 돌려받기): pythonw -u run_build.py ... > build_log.txt
빌더가 자기가 띄운 서버를 치우려고 `taskkill /F /IM python.exe` 를 하는 일이 있다(10편 C1). 그러면 python.exe 로 돌던
이 스크립트도 같이 죽어(rc=1, 트레이스백 없음) 빌더는 고아로 남고 결과(build.json)를 못 받는다. pythonw.exe 는 그 이름에 걸리지 않는다."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # pythonw 에서 콘솔 프로그램을 띄울 때 창이 뜨지 않게


def find_claude():
    p = os.environ.get("CLAUDE_BIN")
    if p and os.path.exists(p):
        return p
    p = shutil.which("claude") or shutil.which("claude.cmd")
    if p:
        return p
    appdata = os.environ.get("APPDATA", "")
    cands = sorted(glob.glob(os.path.join(appdata, "Claude", "claude-code", "*", "*", "claude.exe")))
    if cands:
        return cands[-1]
    sys.exit("claude 실행 파일을 못 찾음 — CLAUDE_BIN 을 지정하세요")


def neutral_root():
    """빌드 작업 폴더는 lab 폴더 '밖'에 둔다.
    Claude Code 는 상위 폴더의 CLAUDE.md 를 자동으로 읽는다. 첫 실행에서 runs/ 를 lab 안에 두었더니 A(한 줄 요청)도
    상위 폴더의 CLAUDE.md · PRD.md · tests/ 를 찾아 읽어 9/9 를 냈다 — 실험이 오염됐다. 그래서 CLAUDE.md 가 하나도 없는
    자리(임시 폴더)에서 만들고, 끝난 뒤 lab/runs/ 로 옮긴다."""
    root = os.environ.get("S2S_RUNS") or os.path.join(tempfile.gettempdir(), "s2s_runs")
    os.makedirs(root, exist_ok=True)
    d = root
    while True:
        parent = os.path.dirname(d)
        for f in ("CLAUDE.md", "PRD.md"):
            if os.path.exists(os.path.join(d, f)):
                sys.exit("빌드 폴더 상위에 %s 가 있음: %s — S2S_RUNS 를 다른 곳으로" % (f, d))
        if parent == d:
            break
        d = parent
    return root


def kill_servers(work):
    """빌더(Claude Code)가 확인용으로 띄우고 안 끈 uvicorn 을 정리한다 — 작업 폴더를 cwd 로 가진 python 프로세스."""
    if os.name != "nt":
        return
    try:
        out = subprocess.run(["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine", "/format:list"], creationflags=NO_WINDOW,
                             capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=20).stdout
    except Exception:
        return
    pid, cmd = None, ""
    for line in out.splitlines() + ["ProcessId="]:
        if line.startswith("CommandLine="):
            cmd = line[12:]
        elif line.startswith("ProcessId="):
            if pid and "uvicorn" in cmd and os.path.basename(work) in cmd + os.getcwd():
                subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True, creationflags=NO_WINDOW)
            pid, cmd = line[10:].strip(), ""


def prepare(lab, cond, run_dir):
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    if cond in ("B", "C"):
        shutil.copy(os.path.join(lab, "PRD.md"), run_dir)
    if cond in ("P1", "P2"):   # ep088: AI 가 쓴 PRD(lab/ai_prd/<P1_1>.md)를 PRD.md 로
        shutil.copy(os.path.join(lab, "ai_prd", os.path.basename(run_dir) + ".md"), os.path.join(run_dir, "PRD.md"))
    if cond == "C":
        shutil.copy(os.path.join(lab, "CLAUDE.md"), run_dir)
        shutil.copytree(os.path.join(lab, "tests"), os.path.join(run_dir, "tests"))
    if cond in ("N", "S", "L"):   # ep089: PRD · tests 는 같고 CLAUDE.md 만 다르다(N 없음 · S 15줄 · L 150줄, lab/claudemd/)
        shutil.copy(os.path.join(lab, "PRD.md"), run_dir)
        shutil.copytree(os.path.join(lab, "tests"), os.path.join(run_dir, "tests"))
        if cond != "N":
            shutil.copy(os.path.join(lab, "claudemd", cond + ".md"), os.path.join(run_dir, "CLAUDE.md"))


def build(claude, run_dir, prompt, model, max_turns, timeout):
    env = dict(os.environ, PYTHONUTF8="1")
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    cmd = [claude, "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions",
           "--model", model, "--max-turns", str(max_turns)]
    if os.environ.get("S2S_GUARD_PYTHON"):
        # 같은 PC 에서 렌더(python.exe)가 돌 때: 빌더의 '이름으로 python 전부 죽이기' 만 막는다. PID 로 끄는 것은 그대로 된다.
        cmd += ["--disallowedTools", "Bash(taskkill /F /IM python*)", "Bash(taskkill //F //IM python*)", "Bash(taskkill /IM python*)",
                "Bash(pkill python*)", "Bash(killall python*)", "Bash(Stop-Process -Name python*)"]
    t0 = time.time()
    info = {"model": model, "prompt": prompt, "max_turns": max_turns}
    try:
        pr = subprocess.run(cmd, cwd=run_dir, env=env, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout,
                            creationflags=NO_WINDOW)
        info["rc"] = pr.returncode
        info["stderr_tail"] = (pr.stderr or "")[-1500:]
        try:
            j = json.loads(pr.stdout)
            info.update({k: j.get(k) for k in ("duration_api_ms", "num_turns", "total_cost_usd", "stop_reason", "terminal_reason", "is_error")})
            info["usage"] = j.get("usage")
            info["result"] = (j.get("result") or "")[-8000:]
        except Exception:
            info["stdout_tail"] = (pr.stdout or "")[-3000:]
    except subprocess.TimeoutExpired:
        info["rc"] = "timeout"
    info["wall_s"] = round(time.time() - t0, 1)
    json.dump(info, open(os.path.join(run_dir, "build.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return info


def main():
    lab = os.path.abspath(sys.argv[1])
    conds, trials, model, only, max_turns = ["A", "B", "C"], 3, "sonnet", None, 80
    for a in sys.argv[2:]:
        if a.startswith("--conds="):
            conds = a.split("=", 1)[1].split(",")
        elif a.startswith("--trials="):
            trials = int(a.split("=", 1)[1])
        elif a.startswith("--model="):
            model = a.split("=", 1)[1]
        elif a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        elif a.startswith("--max-turns="):
            max_turns = int(a.split("=", 1)[1])
    prompts = json.load(open(os.path.join(lab, "prompts.json"), encoding="utf-8"))
    claude = find_claude()
    work_root = os.path.join(neutral_root(), os.path.basename(lab))
    print("claude:", os.path.basename(claude), "| model:", model, "| 작업 폴더:", work_root)
    for cond in conds:
        for k in range(1, trials + 1):
            name = ("%s_%d" if cond[-1].isdigit() else "%s%d") % (cond, k)
            if only and name not in only:
                continue
            work = os.path.join(work_root, name)
            # 앞 빌드(특히 B 의 자기 테스트)가 남긴 서버가 다음 빌드의 기본 포트를 막지 않게 — 포트 기준으로 정리 (ep074 C 셋이 PORT 를 바꿔 돌렸던 일)
            subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kill_servers.py")], capture_output=True, creationflags=NO_WINDOW)
            prepare(lab, cond, work)
            print(name, "빌드 중 ...", end=" ", flush=True)
            info = build(claude, work, prompts[cond], model, max_turns, timeout=1500)
            print("rc=%s 턴=%s %.0f초 $%.2f" % (info.get("rc"), info.get("num_turns"), info["wall_s"], info.get("total_cost_usd") or 0))
            final = os.path.join(lab, "runs", name)
            shutil.rmtree(final, ignore_errors=True)
            os.makedirs(os.path.dirname(final), exist_ok=True)
            # 빌더가 띄워 둔 서버가 로그 파일을 쥐고 있을 수 있어(ep072 A3 server.log) move 대신 복사 + 지울 수 있는 만큼만 지운다
            shutil.copytree(work, final, ignore=shutil.ignore_patterns("__pycache__", "*.db", ".pytest_cache"))
            kill_servers(work)
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
