# -*- coding: utf-8 -*-
"""AI 가 쓴 테스트(lab/ai_tests/<cond>_<n>/test_*.py)를 정답 앱 · 함정 앱에 각각 돌린다 — ep093.
  정답 앱(selftest/ref_app, 사람 테스트 9/9)에서 떨어지면 → 오판 후보
  함정 앱(selftest/trap_app, 실수 6개)에서 떨어지면 → 잡은 것 후보
어느 실수를 잡았는지 · 오판인지 설정 오류인지는 사람(판단 모델)이 ai_tests_dump.md 를 읽고 ai_tests_labels.json 에 적는다.
사용: python _scratch/s2s/tools/grade_ai_tests.py <lab_dir> [--only=prd_1,both_2] [--workers=3] [--port=9100]
  → <lab_dir>/ai_tests_results.json · ai_tests_dump.md
앱은 임시 폴더로 복사해 띄운다(원본 selftest/ 는 건드리지 않음). tests/ 에는 틀(conftest.py) + AI 테스트 파일만."""
import ast
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from port_block import PortBlock  # noqa: E402
from run_build import NO_WINDOW, neutral_root  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
APPS = ("ref_app", "trap_app")


def run_pytest(lab, test_dir, app, port):
    work = os.path.join(neutral_root(), os.path.basename(lab) + "_grade", os.path.basename(test_dir) + "_" + app)
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(os.path.join(lab, "selftest", app), work, ignore=shutil.ignore_patterns("*.db", "__pycache__"))
    tests = os.path.join(work, "tests")
    os.makedirs(tests)
    shutil.copy(os.path.join(lab, "ai_tests_frame", "conftest.py"), tests)
    for p in glob.glob(os.path.join(test_dir, "test_*.py")):
        shutil.copy(p, tests)
    xml_path = os.path.join(work, "junit.xml")
    env = dict(os.environ, APP_DIR=work, PORT=str(port), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDECODE", None)
    out = {"tests": {}, "rc": None}
    try:
        pr = subprocess.run([sys.executable, "-m", "pytest", tests, "-q", "-p", "no:cacheprovider", "--junitxml=" + xml_path,
                             "-o", "junit_family=xunit2"], cwd=work, env=env, capture_output=True, text=True, encoding="utf-8",
                            errors="ignore", timeout=900, creationflags=NO_WINDOW)
        out["rc"] = pr.returncode
        out["stdout_tail"] = (pr.stdout or "")[-3000:]
    except subprocess.TimeoutExpired:
        out["rc"] = "timeout"
    if os.path.exists(xml_path):
        for tc in ET.parse(xml_path).getroot().iter("testcase"):
            name = tc.get("name", "")
            child = next(iter(tc), None)
            if child is None:
                out["tests"][name] = {"status": "pass"}
            else:
                st = {"failure": "fail", "error": "error", "skipped": "skip"}.get(child.tag, child.tag)
                out["tests"][name] = {"status": st, "msg": ((child.get("message") or "") + "\n" + (child.text or ""))[:700]}
    shutil.rmtree(work, ignore_errors=True)
    return out


def functions_of(test_dir):
    """테스트 함수 이름 → 소스(들여쓰기 그대로)"""
    found = {}
    for p in sorted(glob.glob(os.path.join(test_dir, "test_*.py"))):
        src = open(p, encoding="utf-8", errors="ignore").read()
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            found["__syntax_error__"] = str(e)
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                start = min([d.lineno for d in node.decorator_list] + [node.lineno])
                found[node.name] = "\n".join(lines[start - 1:node.end_lineno])
    return found


def main():
    lab = os.path.abspath(sys.argv[1])
    only, port, workers = None, 9100, 3
    for a in sys.argv[2:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        elif a.startswith("--port="):
            port = int(a.split("=", 1)[1])
        elif a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
    out_path = os.path.join(lab, "ai_tests_results.json")
    results = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
    dirs = sorted(d for d in glob.glob(os.path.join(lab, "ai_tests", "*")) if os.path.isdir(d) and not os.path.basename(d).startswith("_"))
    lock = threading.Lock()

    def one(d):
        name = os.path.basename(d)
        r = {"functions": functions_of(d)}
        for app in APPS:
            with PortBlock(port) as pb:
                r[app] = run_pytest(lab, d, app, pb.port)
        info_p = os.path.join(d, "info.json")
        if os.path.exists(info_p):
            i = json.load(open(info_p, encoding="utf-8"))
            r["info"] = {k: i.get(k) for k in ("cond", "num_turns", "total_cost_usd", "wall_s", "conftest_modified", "app_modified", "test_files", "result")}
        names = sorted(set(r["ref_app"]["tests"]) | set(r["trap_app"]["tests"]))
        r["summary"] = {"n": len(names),
                        "ref_fail": sum(1 for n in names if r["ref_app"]["tests"].get(n, {}).get("status") != "pass"),
                        "trap_fail": sum(1 for n in names if r["trap_app"]["tests"].get(n, {}).get("status") != "pass")}
        with lock:
            results[name] = r
            print("채점 %s: 테스트 %d개, 정답 앱 실패 %d, 함정 앱 실패 %d" % (name, r["summary"]["n"], r["summary"]["ref_fail"], r["summary"]["trap_fail"]), flush=True)
            json.dump(dict(sorted(results.items())), open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for f in [ex.submit(one, d) for d in dirs if not only or os.path.basename(d) in only]:
            f.result()

    # 사람이 읽을 덤프
    md = ["# AI 테스트 채점 덤프 (자동 생성) — 함수마다 정답 앱 · 함정 앱 결과와 소스\n"]
    for name, r in sorted(results.items()):
        s = r["summary"]
        md.append("\n## %s — %d개 · 정답 앱 실패 %d · 함정 앱 실패 %d · 틀 수정 %s · 앱 수정 %s\n" % (
            name, s["n"], s["ref_fail"], s["trap_fail"], (r.get("info") or {}).get("conftest_modified"), (r.get("info") or {}).get("app_modified")))
        if (r.get("info") or {}).get("result"):
            md.append("AI 보고: " + re.sub(r"\s+", " ", r["info"]["result"])[:900] + "\n")
        for app in APPS:
            if not r[app]["tests"]:
                md.append("- %s: 테스트가 하나도 돌지 않음 rc=%s\n```\n%s\n```\n" % (app, r[app]["rc"], (r[app].get("stdout_tail") or "")[-1200:]))
        names = sorted(set(r["ref_app"]["tests"]) | set(r["trap_app"]["tests"]))
        for n in names:
            a, b = r["ref_app"]["tests"].get(n, {"status": "-"}), r["trap_app"]["tests"].get(n, {"status": "-"})
            md.append("\n### %s — 정답 %s · 함정 %s" % (n, a["status"], b["status"]))
            base = re.sub(r"\[.*\]$", "", n)
            src = r["functions"].get(n) or r["functions"].get(base)
            if src:
                md.append("```python\n%s\n```" % src)
            for label, x in (("정답 앱", a), ("함정 앱", b)):
                if x.get("msg"):
                    md.append("- %s: `%s`" % (label, re.sub(r"\s+", " ", x["msg"])[:400]))
    open(os.path.join(lab, "ai_tests_dump.md"), "w", encoding="utf-8").write("\n".join(md))
    print("→", out_path, "· ai_tests_dump.md")


if __name__ == "__main__":
    main()
