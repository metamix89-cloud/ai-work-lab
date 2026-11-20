# -*- coding: utf-8 -*-
"""AI 에게 테스트 파일을 쓰게 한다 — ep093 「테스트도 AI 한테 써 달라고 하면」 실측용.

조건 (lab/test_prompts.json 의 프롬프트 + 공통 틀 문장 _frame):
  prd   PRD.md 만 (앱 코드 없음)                 → 요구사항으로 쓰는 테스트
  both  PRD.md + 함정 앱 코드(selftest/trap_app)  → 사람들이 실제로 하는 요청
  code  함정 앱 코드만 + 한 줄 설명              → PRD 없이 바이브코딩한 사람
모든 조건에 tests/conftest.py(lab/ai_tests_frame/conftest.py — 서버 띄우기 · 고정 데이터 · http 도우미)를 같이 준다.
사용: python _scratch/s2s/tools/write_ai_tests.py <lab_dir> [--conds=prd,both,code] [--trials=3] [--start=1] [--model=sonnet] [--workers=3]
  → lab/ai_tests/<cond>_<n>/test_*.py (+ info.json 비용 · 턴 · 마지막 답 · 파일 목록)
작업 폴더는 lab 밖 임시 폴더(run_build.neutral_root) — 상위 CLAUDE.md · PRD.md 를 읽어 오염되지 않게.
포트는 작업마다 10칸을 예약해(port_block) PORT 로 넘긴다 — AI 가 테스트를 직접 돌려 봐도 옆 작업과 안 겹친다."""
import concurrent.futures
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from port_block import PortBlock  # noqa: E402
from run_build import ISOLATE, NO_WINDOW, Job, check_parents, find_claude, neutral_root  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
TRAP = ("main.py", "seed")


def strip_docstring(src):
    """함정 앱 main.py 의 모듈 설명글을 뗀다 — 거기에 '일부러 넣은 실수' 목록이 적혀 있어 AI 가 답을 보고 쓴다(2026-11-06 첫 both · code 실행이 이렇게 오염됨)."""
    import ast
    tree = ast.parse(src)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(getattr(tree.body[0], "value", None), ast.Constant) and isinstance(tree.body[0].value.value, str):
        lines = src.splitlines(True)
        a, b = tree.body[0].lineno - 1, tree.body[0].end_lineno
        return "".join(lines[:a] + lines[b:])
    return src


def prepare(lab, cond, work):
    os.makedirs(work)
    if cond in ("prd", "both"):
        shutil.copy(os.path.join(lab, "PRD.md"), work)
    if cond in ("both", "code"):
        trap = os.path.join(lab, "selftest", "trap_app")
        src = open(os.path.join(trap, "main.py"), encoding="utf-8").read()
        open(os.path.join(work, "main.py"), "w", encoding="utf-8", newline="\n").write(strip_docstring(src))
        shutil.copytree(os.path.join(trap, "seed"), os.path.join(work, "seed"))
    os.makedirs(os.path.join(work, "tests"))
    shutil.copy(os.path.join(lab, "ai_tests_frame", "conftest.py"), os.path.join(work, "tests", "conftest.py"))


def main():
    lab = os.path.abspath(sys.argv[1])
    conds, trials, start, model, workers = ["prd", "both", "code"], 3, 1, "sonnet", 3
    for a in sys.argv[2:]:
        if a.startswith("--conds="):
            conds = a.split("=", 1)[1].split(",")
        elif a.startswith("--trials="):
            trials = int(a.split("=", 1)[1])
        elif a.startswith("--start="):
            start = int(a.split("=", 1)[1])
        elif a.startswith("--model="):
            model = a.split("=", 1)[1]
        elif a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
    prompts = json.load(open(os.path.join(lab, "test_prompts.json"), encoding="utf-8"))
    out_root = os.path.join(lab, "ai_tests")
    os.makedirs(out_root, exist_ok=True)
    claude = find_claude()
    root = os.path.join(neutral_root(), os.path.basename(lab) + "_tests")
    os.makedirs(root, exist_ok=True)
    check_parents(root)
    lock = threading.Lock()

    def say(t):
        with lock:
            print(t, flush=True)

    def one(cond, k):
        name = "%s_%d" % (cond, k)
        prompt = prompts[cond] + "\n" + prompts["_frame"]
        work = os.path.join(root, "%s_%d" % (name, int(time.time())))
        prepare(lab, cond, work)
        out_dir = os.path.join(out_root, name)
        shutil.rmtree(out_dir, ignore_errors=True)
        os.makedirs(out_dir)
        info = {"model": model, "cond": cond, "prompt": prompt}
        with PortBlock() as pb:
            env = dict(os.environ, PYTHONUTF8="1", PORT=str(pb.port), TEMP=os.path.join(work, "_tmp"), TMP=os.path.join(work, "_tmp"))
            os.makedirs(env["TEMP"], exist_ok=True)
            for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
                env.pop(key, None)
            cmd = [claude, "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions",
                   "--model", model, "--max-turns", "40"] + ISOLATE
            info["port"] = pb.port
            say("%s 쓰는 중 ... (포트 %d)" % (name, pb.port))
            t0 = time.time()
            job = Job()
            with open(os.path.join(out_dir, "stdout.json"), "w", encoding="utf-8") as out, open(os.path.join(out_dir, "stderr.txt"), "w", encoding="utf-8") as err:
                pr = subprocess.Popen(cmd, cwd=work, env=env, stdout=out, stderr=err, creationflags=NO_WINDOW)
                info["job"] = job.assign(pr)
                try:
                    info["rc"] = pr.wait(timeout=1500)
                except subprocess.TimeoutExpired:
                    info["rc"] = "timeout"
                    pr.kill()
                job.kill_all()
                pr.wait()
            info["wall_s"] = round(time.time() - t0, 1)
        try:
            j = json.load(open(os.path.join(out_dir, "stdout.json"), encoding="utf-8"))
            info.update({x: j.get(x) for x in ("num_turns", "total_cost_usd", "is_error", "session_id")})
            info["usage"] = j.get("usage")
            info["result"] = (j.get("result") or "")[-3000:]
        except ValueError:
            info["result"] = None
        files = []
        for p in sorted(glob.glob(os.path.join(work, "tests", "test_*.py"))) + sorted(glob.glob(os.path.join(work, "test_*.py"))):
            shutil.copy(p, out_dir)
            files.append(os.path.relpath(p, work).replace(os.sep, "/"))
        info["test_files"] = files
        info["all_files"] = sorted(os.path.relpath(p, work).replace(os.sep, "/") for p in glob.glob(os.path.join(work, "**", "*"), recursive=True)
                                   if os.path.isfile(p) and "_tmp" not in p and "__pycache__" not in p and ".pytest_cache" not in p)
        # 틀 · 앱 코드를 고쳤나
        info["conftest_modified"] = open(os.path.join(work, "tests", "conftest.py"), encoding="utf-8", errors="ignore").read() != open(os.path.join(lab, "ai_tests_frame", "conftest.py"), encoding="utf-8").read() if os.path.exists(os.path.join(work, "tests", "conftest.py")) else None
        if cond in ("both", "code"):
            given = strip_docstring(open(os.path.join(lab, "selftest", "trap_app", "main.py"), encoding="utf-8").read())
            info["app_modified"] = open(os.path.join(work, "main.py"), encoding="utf-8", errors="ignore").read() != given   # 준 것(설명글 뗀 것)과 비교
        json.dump(info, open(os.path.join(out_dir, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        say("%s rc=%s 턴=%s %.0f초 $%.2f 파일 %s 틀 수정 %s 앱 수정 %s" % (name, info["rc"], info.get("num_turns"), info["wall_s"],
                                                                    info.get("total_cost_usd") or 0, files, info["conftest_modified"], info.get("app_modified")))
        shutil.rmtree(work, ignore_errors=True)

    jobs = [(c, k) for c in conds for k in range(start, start + trials)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for f in [ex.submit(one, c, k) for c, k in jobs]:
            f.result()


if __name__ == "__main__":
    main()
