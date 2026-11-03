# -*- coding: utf-8 -*-
"""Claude Code(비대화 `claude -p`)로 같은 화면을 조건별로 만들게 한다 — 「이 화면, PRD 로는 이렇게」 실측 빌더.

조건 (lab_dir/prompts.json 에 정의):
  A 한 줄 요청           빈 폴더 + 한 줄
  B PRD 만              PRD.md 복사 + "PRD 대로 만들어 줘"
  C PRD + CLAUDE.md     PRD.md · CLAUDE.md · tests/ 복사 (완료 기준이 코드로 들어감)
사용: python _scratch/s2s/tools/run_build.py <lab_dir> [--conds=A,B,C] [--trials=3] [--model=sonnet] [--only=A1,C2] [--max-turns=80] [--workers=3]
  → lab_dir/runs/<cond><n>/ 에 생성물 + build.json(비용 · 시간 · 턴 · 마지막 답 · 포트 · isolation)
Claude Code 실행 파일: 환경 변수 CLAUDE_BIN, 없으면 PATH 의 claude, 없으면 데스크톱 앱이 번들한 것을 찾는다.

--workers=N(기본 3)만큼 동시에 돈다. 빌드마다 따로 쓰는 것:
  포트 10칸(port_block, 9600~)  PORT · UVICORN_PORT 로 넘기고, 문서에 적힌 8000 대신 쓰라고 시스템 프롬프트에 한 줄 덧붙인다
  작업 폴더 <임시>/s2s_runs/<lab>/p<포트>/<이름>  형제 빌드의 PRD 가 `..` 에 보이지 않게 한 겹 더 둔다
  TEMP/TMP                     git bash 의 /tmp 가 여기로 간다(빌더가 /tmp/uv.log 같은 이름을 자주 쓴다)
  윈도우 Job                    끝나면 빌더와 그 자식(남은 서버 · 브라우저)을 통째로 끈다. 다른 빌드의 프로세스는 건드리지 않는다
덧붙인 한 줄은 조건과 상관없이 같지만 실험 조건이 하나 는 것이다. 옛 조건 그대로 재현하려면 --workers=1(덧붙임 · PORT 없음).
동시 실행의 위험은 빌더가 남의 서버를 부르거나 끄는 것 — build.json 의 isolation 에 기록에서 찾은 흔적이 남고, 비어 있지 않으면 그 실행을 의심한다.

윈도우에서는 pythonw.exe 로 돌린다(출력은 파일로 돌려받기): pythonw -u run_build.py ... > build_log.txt
빌더가 자기가 띄운 서버를 치우려고 `taskkill /F /IM python.exe` 를 하는 일이 있다(10편 C1). 그러면 python.exe 로 돌던
이 스크립트도 같이 죽어(rc=1, 트레이스백 없음) 빌더는 고아로 남고 결과(build.json)를 못 받는다. pythonw.exe 는 그 이름에 걸리지 않는다."""
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from port_block import BUILD_BASE, PortBlock  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # pythonw 에서 콘솔 프로그램을 띄울 때 창이 뜨지 않게

# 동시 실행 때 빌더에게 덧붙이는 한 줄 — 조건(prompts.json)은 그대로 두고 시스템 프롬프트로만
PARALLEL_NOTE = ("이 PC 에서는 같은 일을 하는 다른 작업이 동시에 돌고 있다. 서버를 띄우거나 부를 때 포트는 문서에 적힌 값 대신 환경 변수 PORT 의 값(%d, 서버가 둘이면 다음 번호)을 쓴다. "
                 "프로세스를 끌 때는 네가 띄운 것의 PID 로만 끄고, 이름이나 명령줄 패턴(python.exe · uvicorn)으로 찾아 끄지 않는다. 이 작업 폴더 밖은 보지 않는다.")
PYTHON_GUARD = ["Bash(taskkill /F /IM python*)", "Bash(taskkill //F //IM python*)", "Bash(taskkill /IM python*)",
                "Bash(pkill python*)", "Bash(killall python*)", "Bash(Stop-Process -Name python*)",
                "Bash(pkill *uvicorn*)", "Bash(taskkill *python*)", "PowerShell(Stop-Process -Name python*)"]
PORT_RE = re.compile(r"(?:--port[ =]+|localhost:|127\.0\.0\.1:|0\.0\.0\.0:|PORT=)(\d{2,5})")
KILL_BY_NAME_RE = re.compile(r"taskkill[^|;&\n]*/IM\b|\bpkill\b|\bkillall\b|Stop-Process\s+-Name|(?:CommandLine|Get-Process|wmic)[^\n]*(?:Stop-Process|taskkill|\.Kill\()", re.I)


def say(text):
    """스레드끼리 줄이 섞이지 않게 줄바꿈까지 한 번에 쓴다"""
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


class Job:
    """윈도우 Job Object — 빌더가 끝나면 그 자식까지 통째로 끈다. 고아가 된 서버도 Job 안에 남으므로 잡힌다."""

    def __init__(self):
        self.h = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.CreateJobObjectW.restype = wintypes.HANDLE
        self.k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self.k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.h = self.k.CreateJobObjectW(None, None)

    def assign(self, proc):
        return bool(self.h and self.k.AssignProcessToJobObject(self.h, int(proc._handle)))

    def kill_all(self):
        if self.h:
            self.k.TerminateJobObject(self.h, 1)
            self.k.CloseHandle(self.h)
            self.h = None


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


def check_parents(path):
    """path 와 그 상위 어디에도 CLAUDE.md · PRD.md 가 없어야 한다(claude-code-parent-claudemd)."""
    d = path
    while True:
        parent = os.path.dirname(d)
        for f in ("CLAUDE.md", "PRD.md"):
            if os.path.exists(os.path.join(d, f)):
                sys.exit("빌드 폴더 상위에 %s 가 있음: %s — S2S_RUNS 를 다른 곳으로" % (f, d))
        if parent == d:
            break
        d = parent


def neutral_root():
    """빌드 작업 폴더는 lab 폴더 '밖'에 둔다.
    Claude Code 는 상위 폴더의 CLAUDE.md 를 자동으로 읽는다. 첫 실행에서 runs/ 를 lab 안에 두었더니 A(한 줄 요청)도
    상위 폴더의 CLAUDE.md · PRD.md · tests/ 를 찾아 읽어 9/9 를 냈다 — 실험이 오염됐다. 그래서 CLAUDE.md 가 하나도 없는
    자리(임시 폴더)에서 만들고, 끝난 뒤 lab/runs/ 로 옮긴다."""
    root = os.environ.get("S2S_RUNS") or os.path.join(tempfile.gettempdir(), "s2s_runs")
    os.makedirs(root, exist_ok=True)
    check_parents(root)
    return root


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


def isolation_of(session_id, work, root, ports):
    """빌더 기록에서 격리가 깨진 흔적을 찾는다 — 받은 포트 밖을 부름 · 이름으로 프로세스 끔 · 자기 폴더 밖을 봄.
    글자로 찾는 것이라 놓칠 수 있다. 비어 있으면 '깨진 흔적을 못 찾음' 이다."""
    if not session_id:
        return {"transcript": False}
    found = glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", session_id + ".jsonl"))
    if not found:
        return {"transcript": False}
    norm = lambda s: str(s).replace("\\", "/").lower()
    work_n, root_n = norm(work), norm(root)
    foreign, kills, outside = set(), [], []
    for line in open(found[0], encoding="utf-8", errors="ignore"):
        try:
            content = (json.loads(line).get("message") or {}).get("content")
        except ValueError:
            continue
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            inp = c.get("input") or {}
            cmd = str(inp.get("command") or "")
            foreign.update(int(p) for p in PORT_RE.findall(cmd) if int(p) not in ports)
            if KILL_BY_NAME_RE.search(cmd):
                kills.append(cmd[:200])
            text = norm(" ".join(str(inp.get(k) or "") for k in ("command", "file_path", "path", "pattern")))
            if "../.." in text or text.replace(work_n, "").find(root_n) >= 0:
                outside.append(text[:200])
    return {"transcript": True, "foreign_ports": sorted(foreign), "kill_by_name": kills, "outside_refs": outside}


def build(claude, run_dir, prompt, model, max_turns, timeout, block=None, tmp=None, root=None):
    env = dict(os.environ, PYTHONUTF8="1")
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    cmd = [claude, "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions",
           "--model", model, "--max-turns", str(max_turns)]
    if block:
        env.update(PORT=str(block.port), UVICORN_PORT=str(block.port), TEMP=tmp, TMP=tmp, TMPDIR=tmp)
        cmd += ["--append-system-prompt", PARALLEL_NOTE % block.port]
    if block or os.environ.get("S2S_GUARD_PYTHON"):
        # 같은 PC 에서 다른 빌드 · 렌더(python.exe)가 돌 때: 빌더의 '이름으로 python 전부 죽이기' 만 막는다. PID 로 끄는 것은 그대로 된다.
        cmd += ["--disallowedTools"] + PYTHON_GUARD
    t0 = time.time()
    info = {"model": model, "prompt": prompt, "max_turns": max_turns}
    if block:
        info.update(port=block.port, parallel_note=PARALLEL_NOTE % block.port)
    job = Job()
    # 출력은 파이프 대신 임시 파일로 — 빌더가 남긴 서버가 파이프를 쥐고 있어도 빌더가 끝나면 바로 넘어간다
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        pr = subprocess.Popen(cmd, cwd=run_dir, env=env, stdout=out, stderr=err, creationflags=NO_WINDOW)
        info["job"] = job.assign(pr)
        try:
            info["rc"] = pr.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            info["rc"] = "timeout"
            pr.kill()
        job.kill_all()   # 남은 서버가 로그 파일을 쥔 채 복사되지 않게(ep072 A3 server.log) 복사 전에 끈다
        pr.wait()
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read().decode("utf-8", "ignore"), err.read().decode("utf-8", "ignore")
    if info["rc"] != "timeout":
        info["stderr_tail"] = stderr[-1500:]
        try:
            j = json.loads(stdout)
            info.update({k: j.get(k) for k in ("duration_api_ms", "num_turns", "total_cost_usd", "stop_reason", "terminal_reason", "is_error", "session_id")})
            info["usage"] = j.get("usage")
            info["result"] = (j.get("result") or "")[-8000:]
        except Exception:
            info["stdout_tail"] = stdout[-3000:]
    info["wall_s"] = round(time.time() - t0, 1)
    if block:
        info["isolation"] = isolation_of(info.get("session_id"), run_dir, root, block.ports)
    json.dump(info, open(os.path.join(run_dir, "build.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return info


def run_one(lab, prompts, claude, root, cond, name, model, max_turns, parallel, kill_script):
    lab_root = os.path.join(root, os.path.basename(lab))
    block = PortBlock(BUILD_BASE) if parallel else None
    try:
        # 형제 빌드가 `..` 에 보이지 않게 포트별 폴더를 한 겹 더 둔다. 그 안의 _tmp 는 이 빌드의 TEMP.
        base = os.path.join(lab_root, "p%d" % block.port) if block else lab_root
        work = os.path.join(base, name)
        tmp = os.path.join(base, "_tmp") if block else None
        if block:
            shutil.rmtree(base, ignore_errors=True)
            os.makedirs(tmp)
            check_parents(base)
        else:
            # 앞 빌드(특히 B 의 자기 테스트)가 남긴 서버가 다음 빌드의 기본 포트를 막지 않게 — 포트 기준으로 정리 (ep074 C 셋이 PORT 를 바꿔 돌렸던 일)
            subprocess.run([sys.executable, kill_script], capture_output=True, creationflags=NO_WINDOW)
        prepare(lab, cond, work)
        say("%s 빌드 시작%s" % (name, " 포트 %d" % block.port if block else ""))
        info = build(claude, work, prompts[cond], model, max_turns, 1500, block, tmp, root)
        iso = info.get("isolation") or {}
        warn = {k: iso[k] for k in ("foreign_ports", "kill_by_name", "outside_refs") if iso.get(k)}
        say("%s rc=%s 턴=%s %.0f초 $%.2f%s%s" % (name, info.get("rc"), info.get("num_turns"), info["wall_s"], info.get("total_cost_usd") or 0,
                                               "" if info["job"] else " [Job 실패]", " [격리 흔적 %s]" % json.dumps(warn, ensure_ascii=False)[:400] if warn else ""))
        final = os.path.join(lab, "runs", name)
        shutil.rmtree(final, ignore_errors=True)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        shutil.copytree(work, final, ignore=shutil.ignore_patterns("__pycache__", "*.db", ".pytest_cache"))
        shutil.rmtree(base if block else work, ignore_errors=True)
        return info
    finally:
        if block:
            block.close()


def main():
    lab = os.path.abspath(sys.argv[1])
    conds, trials, model, only, max_turns, workers = ["A", "B", "C"], 3, "sonnet", None, 80, 3
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
        elif a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
    prompts = json.load(open(os.path.join(lab, "prompts.json"), encoding="utf-8"))
    claude = find_claude()
    root = neutral_root()
    print("claude:", os.path.basename(claude), "| model:", model, "| 동시:", workers, "| 작업 폴더:", os.path.join(root, os.path.basename(lab)), flush=True)
    if os.name == "nt" and os.path.basename(sys.executable).lower() == "python.exe":
        print("주의: python.exe 로 돌고 있음 — 빌더의 이름 종료에 같이 죽을 수 있으니 pythonw 로", flush=True)
    jobs = []
    for cond in conds:
        for k in range(1, trials + 1):
            name = ("%s_%d" if cond[-1].isdigit() else "%s%d") % (cond, k)
            if not only or name in only:
                jobs.append((cond, name))
    kill_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kill_servers.py")
    parallel = workers > 1
    if parallel:   # 동시 실행 중엔 빌드마다 부르면 옆 빌드의 서버를 끈다 — 시작 전에 한 번만
        subprocess.run([sys.executable, kill_script], capture_output=True, creationflags=NO_WINDOW)
    t0 = time.time()
    infos = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        fs = {ex.submit(run_one, lab, prompts, claude, root, cond, name, model, max_turns, parallel, kill_script): name for cond, name in jobs}
        for f in concurrent.futures.as_completed(fs):
            try:
                infos.append(f.result())
            except Exception as e:   # 한 번이 실패해도 나머지는 끝까지 — 돈이 이미 든 빌드다
                say("%s 실패: %r" % (fs[f], e))
    total = sum(i.get("wall_s") or 0 for i in infos)
    say("끝: %d/%d회 · 전체 %.0f초 · 회별 시간 합 %.0f초 · $%.2f" % (len(infos), len(jobs), time.time() - t0, total, sum(i.get("total_cost_usd") or 0 for i in infos)))


if __name__ == "__main__":
    main()
