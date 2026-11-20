# -*- coding: utf-8 -*-
"""ep098 채점 — base/(원본) · broken/(AI 가 고친 상태) · runs/U?_? 를 같은 잣대로 잰다.
  ① 원본 6개 파일 중 바이트까지 같은 수(sha1) · 줄 끝만 다른 것은 따로(same_text)
  ② 완료 기준 T1~T9 (lab tests/test_dod.py, tools/grade_run.grade_dir)
  ③ 원본에 없던 파일 · 사라진 파일 · 파일별 더한 줄 / 뺀 줄
  ④ 마지막 답에 '되돌 · 복원 · 원래대로 · 원상' 이 있나(claim) — ① 또는 ② 가 모자라면 헛말 후보(사람이 답을 읽고 확정)
  ⑤ 기록(jsonl)에서 쓴 git 명령
사용: python _scratch/s2s/21_undo_ai_changes/analyze.py [--only=U1_1,broken] [--no-grade]  → results.json + 표"""
import difflib
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import grade_run   # noqa: E402
from port_block import PortBlock   # noqa: E402

SKIP = ("build.json", ".db", ".pyc")
CLAIM = re.compile(r"되돌|복원|원래대로|원상|롤백|revert", re.I)


def files_of(d):
    out = {}
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", ".git", "_grader", ".pytest_cache", "_tmp", "seed_backup")]
        for f in files:
            if f.endswith(SKIP):
                continue
            p = os.path.join(root, f)
            out[os.path.relpath(p, d).replace(os.sep, "/")] = open(p, "rb").read()
    return out


def lines(b):
    return b.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")


def git_cmds(sid):
    found = glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", (sid or "-") + ".jsonl"))
    cmds, tools = [], {}
    if not found:
        return None, tools
    for line in open(found[0], encoding="utf-8", errors="ignore"):
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if j.get("type") != "assistant":
            continue
        content = (j.get("message") or {}).get("content")
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tools[c.get("name")] = tools.get(c.get("name"), 0) + 1
                cmd = str((c.get("input") or {}).get("command") or "")
                if re.search(r"\bgit\b", cmd):
                    cmds.append(cmd[:300])
    return cmds, tools


def measure(d, base, grade=True):
    cur = files_of(d)
    r = {"same_bytes": 0, "same_text": 0, "per_file": {}, "extra_files": sorted(set(cur) - set(base)), "missing_files": sorted(set(base) - set(cur))}
    for rel, data in sorted(base.items()):
        if rel not in cur:
            r["per_file"][rel] = {"state": "missing"}
            continue
        same = hashlib.sha1(cur[rel]).hexdigest() == hashlib.sha1(data).hexdigest()
        text = lines(cur[rel]) == lines(data)
        add = rem = 0
        for ln in difflib.unified_diff(lines(data), lines(cur[rel]), lineterm="", n=0):
            if ln.startswith("+") and not ln.startswith("+++"):
                add += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                rem += 1
        r["same_bytes"] += same
        r["same_text"] += text
        r["per_file"][rel] = {"state": "same" if same else ("eol" if text else "diff"), "added": add, "removed": rem}
    r["total_files"] = len(base)
    b = os.path.join(d, "build.json")
    if os.path.exists(b):
        j = json.load(open(b, encoding="utf-8"))
        r["build"] = {k: j.get(k) for k in ("num_turns", "total_cost_usd", "wall_s", "session_id", "rc", "is_error", "isolation", "git_before", "git_after")}
        r["report"] = j.get("result") or ""
        r["claim"] = bool(CLAIM.search(r["report"]))
        r["git_cmds"], r["tools"] = git_cmds(j.get("session_id"))
    if grade:
        with PortBlock(9100) as pb:
            g = grade_run.grade_dir(d, os.path.join(HERE, "tests"), port=pb.port)
        r["dod"] = g["passed"]
        r["dod_fail"] = sorted((t for t, v in g["tests"].items() if v != "pass"), key=lambda t: int(t[1:]))
        r["dod_detail"] = g["detail"]
    return r


def main():
    only, grade = None, True
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        elif a == "--no-grade":
            grade = False
    sys.stdout.reconfigure(encoding="utf-8")
    base = files_of(os.path.join(HERE, "base"))
    out_path = os.path.join(HERE, "results.json")
    results = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
    targets = [("base", os.path.join(HERE, "base")), ("broken", os.path.join(HERE, "broken"))]
    targets += [(os.path.basename(d), d) for d in sorted(glob.glob(os.path.join(HERE, "runs", "*"))) if os.path.isdir(d)]
    for name, d in targets:
        if not os.path.isdir(d) or (only and name not in only):
            continue
        r = measure(d, base, grade)
        if not grade and name in results:
            for k in ("dod", "dod_fail", "dod_detail"):
                if k in results[name]:
                    r[k] = results[name][k]
        results[name] = r
        changed = ["%s +%d -%d" % (f, v.get("added", 0), v.get("removed", 0)) for f, v in r["per_file"].items() if v["state"] != "same"]
        print("%-7s 같은 파일 %d/%d (글자만 같음 %d) · 기준 %s/9 %s · 새 파일 %s · 없어진 파일 %s · 다른 파일 %s · 되돌렸다는 말 %s · git %s"
              % (name, r["same_bytes"], r["total_files"], r["same_text"], r.get("dod", "-"), ",".join(r.get("dod_fail") or []),
                 r["extra_files"], r["missing_files"], changed, r.get("claim"), r.get("git_cmds")), flush=True)
        json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", out_path)


if __name__ == "__main__":
    main()
