# -*- coding: utf-8 -*-
"""ep097 채점 · 셈 — runs/<M1_1 …> 마다
  ① 기존 T1~T9 통과 수(회귀 = 9 - 통과)  ② 새 T10~T12(PRD 이름으로 부른 엄격 채점)
  ③ 시키지 않은 변경: 사라진 data-testid · 사라진 API 경로 · seed 칸 이름 변경 · 한 번짜리 예약 응답에서 사라진 칸
  ④ 바꾼 파일 수 · 더한 줄 · 뺀 줄(base 와 비교)  ⑤ 기록(jsonl)에서 pytest 를 실제로 돌린 횟수 · 서버를 띄워 본 횟수 · 보고에 '테스트' 가 있나
사용: python _scratch/s2s/20_feature_regression/analyze.py [--only=M1_1,M3_2] [--port=9200]   → results.json · summary.json
'자기 이름' 채점(문서 없이 만든 앱을 그 앱의 칸 이름으로 부르기)은 own_probe.py 가 따로 한다."""
import csv
import difflib
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "tests"))
from grade_run import grade_dir, routes_of   # noqa: E402
from port_block import PortBlock   # noqa: E402

BASE = os.path.join(HERE, "base")
APP_FILES = ("main.py", "static", "seed")
SKIP = ("__pycache__", "_grader", "seed_backup", ".pytest_cache", ".claude")


def app_files(d):
    out = {}
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, d).replace(os.sep, "/")
            if f.endswith((".db", ".pyc", ".log")) or rel in ("build.json",):
                continue
            out[rel] = p
    return out


def read(p):
    try:
        return open(p, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""


def testids(d):
    src = "".join(read(p) for rel, p in app_files(d).items() if rel.endswith((".html", ".js", ".py")) and not rel.startswith("tests/"))
    return set(re.findall(r"data-testid=\\?[\"']([\w-]+)", src))


def seed_headers(d):
    out = {}
    for p in sorted(glob.glob(os.path.join(d, "seed", "*.csv"))):
        with open(p, encoding="utf-8-sig", newline="") as f:
            out[os.path.basename(p)] = next(csv.reader(f), [])
    return out


def norm_route(r):
    return re.sub(r"\{[^}]*\}", "{}", r.rstrip("/")) or "/"


def diff_stats(d):
    base, run = app_files(BASE), app_files(d)
    given = {k for k in base if k.split("/")[0] in APP_FILES}
    changed, added, plus, minus = [], [], 0, 0
    for rel in sorted(run):
        if rel.split("/")[0] in ("tests",) or rel in ("PRD.md", "CLAUDE.md"):
            continue
        a = read(base[rel]).splitlines() if rel in given else []
        b = read(run[rel]).splitlines()
        if a == b:
            continue
        (changed if rel in given else added).append(rel)
        for line in difflib.unified_diff(a, b, lineterm="", n=0):
            if line.startswith("+") and not line.startswith("+++"):
                plus += 1
            elif line.startswith("-") and not line.startswith("---"):
                minus += 1
    removed = sorted(k for k in given if k not in run)
    return {"changed": changed, "added": added, "removed": removed, "lines_added": plus, "lines_removed": minus}


def single_contract(d, port):
    """한 번짜리 예약의 요청 · 응답 모양이 v1 그대로인가 — 서버를 띄워 직접 본다 (고정 데이터는 그 앱의 seed 그대로)."""
    from test_dod import find_app_target
    os.environ["APP_DIR"] = d
    import test_dod
    test_dod.APP = d
    target, _ = find_app_target()
    if not target:
        return {"error": "앱을 못 찾음"}
    for p in glob.glob(os.path.join(d, "**", "*.db"), recursive=True):
        try:
            os.remove(p)
        except OSError:
            pass
    env = dict(os.environ, PORT=str(port), PYTHONUTF8="1")
    pr = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--port", str(port)], cwd=d, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    out = {}
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        st, body = test_dod.http("POST", base + "/api/reservations",
                                 {"room_id": "C", "date": "2027-03-02", "start": "09:00", "end": "09:30", "user": "박지연"})
        out["post_status"] = st
        out["post_keys"] = sorted(body) if isinstance(body, dict) else str(type(body).__name__)
        st, rows = test_dod.http("GET", base + "/api/reservations?date=2027-03-02")
        out["get_status"] = st
        out["get_keys"] = sorted(rows[0]) if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
        st, users = test_dod.http("GET", base + "/api/users")
        out["users_shape"] = type(users[0]).__name__ if isinstance(users, list) and users else None
    except Exception as e:
        out["error"] = repr(e)[:200]
    finally:
        pr.kill()
        pr.wait()
    return out


def transcript_facts(build):
    sid = (build or {}).get("session_id")
    facts = {"pytest_runs": 0, "server_runs": 0, "wrote_tests": [], "transcript": False}
    found = glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", "%s.jsonl" % sid)) if sid else []
    if not found:
        return facts
    facts["transcript"] = True
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
            if re.search(r"\bpytest\b", cmd):
                facts["pytest_runs"] += 1
            if re.search(r"uvicorn|python\s+main\.py", cmd):
                facts["server_runs"] += 1
            fp = str(inp.get("file_path") or "").replace("\\", "/")
            if c.get("name") in ("Write", "Edit") and re.search(r"/tests?/|test_\w+\.py$", fp):
                facts["wrote_tests"].append(os.path.basename(fp))
    facts["wrote_tests"] = sorted(set(facts["wrote_tests"]))
    return facts


def main():
    only, port = None, 9200
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        elif a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    res_path, sum_path = os.path.join(HERE, "results.json"), os.path.join(HERE, "summary.json")
    results = json.load(open(res_path, encoding="utf-8")) if os.path.exists(res_path) else {}
    summary = json.load(open(sum_path, encoding="utf-8")) if os.path.exists(sum_path) else {}
    base_ids, base_routes, base_seed = testids(BASE), {norm_route(r) for r in routes_of(BASE)}, seed_headers(BASE)
    for d in sorted(glob.glob(os.path.join(HERE, "runs", "*"))):
        name = os.path.basename(d)
        if not os.path.isdir(d) or (only and name not in only):
            continue
        with PortBlock(port) as pb:
            r = grade_dir(d, os.path.join(HERE, "tests"), port=pb.port)
            contract = single_contract(d, pb.port + 1)
        build = json.load(open(os.path.join(d, "build.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "build.json")) else {}
        r["build"] = build
        results[name] = r
        old = sum(1 for i in range(1, 10) if r["tests"].get("T%d" % i) == "pass")
        new = sum(1 for i in range(10, 13) if r["tests"].get("T%d" % i) == "pass")
        ids, routes, seed = testids(d), {norm_route(x) for x in routes_of(d)}, seed_headers(d)
        want_keys = {"res_id", "room_id", "date", "start", "end", "user"}
        s = {
            "old_pass": old, "regressions": 9 - old, "old_failed": [t for t in ("T%d" % i for i in range(1, 10)) if r["tests"].get(t) != "pass"],
            "new_pass_strict": new, "new_detail": {t: (r["detail"].get(t) or "")[:300] for t in ("T10", "T11", "T12") if r["tests"].get(t) != "pass"},
            "testid_removed": sorted(base_ids - ids), "testid_added": sorted(ids - base_ids),
            "routes_removed": sorted(base_routes - routes), "routes_added": sorted(routes - base_routes),
            "seed_changed": {k: v for k, v in seed.items() if base_seed.get(k) != v}, "seed_removed": sorted(set(base_seed) - set(seed)),
            "single_contract": contract,
            "single_keys_missing": sorted(want_keys - set(contract.get("post_keys") or [])) if isinstance(contract.get("post_keys"), list) else None,
            "single_keys_extra": sorted(set(contract.get("post_keys") or []) - want_keys) if isinstance(contract.get("post_keys"), list) else None,
            "tests_modified": r.get("tests_modified"),
            "cost": build.get("total_cost_usd"), "turns": build.get("num_turns"), "wall_s": build.get("wall_s"), "rc": build.get("rc"),
            "report_mentions_test": bool(re.search(r"pytest|테스트|DoD|9/9", build.get("result") or "")),
        }
        s.update(diff_stats(d))
        s.update(transcript_facts(build))
        s["unasked"] = len(s["testid_removed"]) + len(s["routes_removed"]) + len(s["seed_changed"]) + len(s["seed_removed"]) + len(s["single_keys_missing"] or [])
        summary[name] = s
        print("%s 기존 %d/9 · 새(엄격) %d/3 · 시키지 않은 변경 %d · 파일 %d(+%d) · +%d/-%d줄 · pytest %d회 · 서버 %d회 · $%.2f" % (
            name, old, new, s["unasked"], len(s["changed"]), len(s["added"]), s["lines_added"], s["lines_removed"],
            s["pytest_runs"], s["server_runs"], s["cost"] or 0), flush=True)
        if s["old_failed"]:
            for t in s["old_failed"]:
                print("    떨어짐", t, (r["detail"].get(t) or "")[:200].replace("\n", " "))
        json.dump(dict(sorted(results.items())), open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(dict(sorted(summary.items())), open(sum_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", res_path, sum_path)


if __name__ == "__main__":
    main()
