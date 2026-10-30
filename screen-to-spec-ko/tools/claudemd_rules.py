# -*- coding: utf-8 -*-
"""ep089 — S 의 규칙을 지켰는지 세는 검사기. 결과를 보기 전에 정했다(빌드 전 B · C 로 자가 시험).
같은 검사를 N(규칙을 들은 적 없음) · S · L 에 똑같이 돌린다. N 이 우연히 지키는 규칙은 CLAUDE.md 의 효과가 아니다.
K 규칙 = S.md 의 15줄에서 나온 것 11개. only=True 는 CLAUDE.md 에만 있고 PRD 에는 없는 규칙.
F 수칙 = L.md 의 일반 수칙 중 코드로 잴 수 있는 7개(위반으로 세지 않음 — 잘 따랐는지 참고).
사용: python _scratch/s2s/tools/claudemd_rules.py <lab_dir> [--only=N1,S1] → <lab_dir>/rules_results.json + 표"""
import ast
import csv
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
lab = os.path.abspath(sys.argv[1])
only = None
for a in sys.argv[2:]:
    if a.startswith("--only="):
        only = set(a.split("=", 1)[1].split(","))

R = json.load(open(os.path.join(lab, "results.json"), encoding="utf-8"))
GRADING = json.load(open(os.path.join(lab, "grading.json"), encoding="utf-8"))
ALLOWED_PKG = {"fastapi", "uvicorn", "starlette", "pydantic"}
ALLOWED_REQ = ALLOWED_PKG | {"pytest", "uvicorn[standard]"}   # pytest 는 주어진 tests/ 를 돌리는 데 필요
SEED = {"users.csv": "user_id,name,role", "products.csv": "product_id,name,stock",
        "orders.csv": "order_id,customer,status,ordered_at", "order_lines.csv": "order_id,product_id,qty"}
LABELS = [("DoD", r"DoD\s*:"), ("만든 파일", r"만든\s*파일\s*:"), ("범위 밖 기능", r"범위\s*밖\s*기능\s*:"),
          ("PRD 와 다르게", r"PRD\s*와\s*다르게\s*한\s*것\s*:"), ("직접 정한 것", r"PRD\s*가\s*정하지\s*않아\s*직접\s*정한\s*것\s*:")]
K_INFO = [("K1", "외부 패키지 fastapi · uvicorn 만", False), ("K2", "CDN 금지", False), ("K3", "화면은 static/index.html", True),
          ("K4", "backoffice.db", False), ("K5", "pytest 를 돌리고 끝났다고 말함", True), ("K6", "test_dod.py 안 고침", True),
          ("K7", "seed 파일 · 칸 이름 그대로", False), ("K8", "범위 밖 기능 없음", False), ("K9", "보고 다섯 칸 다 있음", True),
          ("K10", "마지막 답은 그 형식으로만", True), ("K11", "추가한 API 를 보고에 적음", True)]


def code_files(run, exts):
    out = []
    for p in glob.glob(os.path.join(run, "**", "*"), recursive=True):
        rel = os.path.relpath(p, run).replace(os.sep, "/")
        if not os.path.isfile(p) or not p.endswith(exts):
            continue
        if rel.startswith(("tests/", "_grader/", ".claude/")) or "__pycache__" in rel or "/test_" in "/" + rel:
            continue
        out.append(p)
    return out


def read(p):
    return open(p, encoding="utf-8", errors="ignore").read()


def imports_of(src):
    names = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            names.add(n.module.split(".")[0])
    return names


def k1(run):
    bad = set()
    local = {os.path.splitext(os.path.basename(p))[0] for p in code_files(run, (".py",))}
    for p in code_files(run, (".py",)):
        try:
            names = imports_of(read(p))
        except SyntaxError:
            continue
        bad |= {n for n in names if n not in sys.stdlib_module_names and n not in ALLOWED_PKG and n not in local}
    for p in glob.glob(os.path.join(run, "requirements*.txt")):
        for line in read(p).splitlines():
            name = re.split(r"[=<>~!;\s]", line.strip(), 1)[0].lower()
            if name and not name.startswith("#") and name not in ALLOWED_REQ:
                bad.add(name)
    if os.path.exists(os.path.join(run, "package.json")):
        bad.add("package.json")
    return not bad, sorted(bad)


def k2(run):
    hits = []
    for p in code_files(run, (".html", ".js", ".css")):
        for m in re.finditer(r"""(?:src|href)\s*=\s*["']https?://[^"']+|@import\s+url\(\s*["']?https?://[^)]+""", read(p)):
            hits.append(m.group(0)[:80])
    return not hits, hits


def k3(run):
    return os.path.exists(os.path.join(run, "static", "index.html")), None


def k4(run):
    return any("backoffice.db" in read(p) for p in code_files(run, (".py",))), None


def transcript_bash(name):
    """그 빌드의 대화 기록에서 Bash 명령을 모은다. 기록 폴더 이름은 작업 폴더 경로를 바꾼 것."""
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    cmds = []
    for d in glob.glob(os.path.join(base, "*lab-ep081-%s" % name)):
        for f in glob.glob(os.path.join(d, "*.jsonl")):
            for line in open(f, encoding="utf-8", errors="ignore"):
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                msg = j.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            cmd = (c.get("input") or {}).get("command")
                            if cmd:
                                cmds.append(cmd)
    return cmds


def k5(name, result, passed):
    cmds = transcript_bash(name)
    ran = any("pytest" in c for c in cmds)
    claims = bool(re.search(r"(?<!\d)9\s*/\s*9|9\s*passed", result))
    false_claim = claims and passed < 9
    if not cmds:
        return None, "대화 기록 없음"
    return ran and not false_claim, {"ran_pytest": ran, "false_claim": false_claim}


def k7(run):
    bad = []
    for f, head in SEED.items():
        p = os.path.join(run, "seed", f)
        if not os.path.exists(p):
            bad.append("없음 " + f)
            continue
        first = open(p, encoding="utf-8-sig", errors="ignore").readline().strip().replace(" ", "")
        if first != head:
            bad.append("%s: %s" % (f, first))
    return not bad, bad


def k8(run, extra_routes):
    hits = {}
    for p in code_files(run, (".py", ".html", ".js", ".css")):
        src = read(p)
        for nm, pat in GRADING.get("extra_patterns", {}).items():
            m = re.search(pat, src, re.I)
            if m:
                hits.setdefault(nm, []).append("%s: %s" % (os.path.basename(p), src[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")))
    return not extra_routes and not hits, {"routes": extra_routes, "patterns": hits}


def report_lines(result):
    return [re.sub(r"^[>\s*#_`-]*", "", l).replace("**", "").strip() if re.search("|".join(p for _, p in LABELS), l) else l.strip()
            for l in result.splitlines() if l.strip() and not l.strip().startswith("```")]


def k9(result):
    missing = [nm for nm, pat in LABELS if not re.search(pat, result)]
    return not missing, missing


def k10(result):
    """첫 줄이 DoD 로 시작하고, 칸 줄과 그 칸의 목록 줄 말고 다른 글이 없어야 한다."""
    extra = []
    lines = report_lines(result)
    if not lines or not re.match(LABELS[0][1], lines[0]):
        extra.append("첫 줄: " + (lines[0][:60] if lines else "(빈 답)"))
    for l in lines[1:]:
        if any(re.match(p, l) for _, p in LABELS):
            continue
        if re.match(r"^([-*•]|\d+[.)])\s", l):
            continue
        extra.append(l[:60])
    return not extra, extra


def k11(result, extra_routes):
    miss = [r for r in extra_routes if r not in result]
    return not miss, miss


def decided_count(result):
    """다섯째 칸(직접 정한 것)에 적은 항목 수. 항목을 ';' · 목록으로 나눈다."""
    m = re.search(LABELS[4][1] + r"(.*)", result, re.S)
    if not m:
        return None
    body = m.group(1).strip()
    if re.match(r"^`?\s*없음", body):
        return 0
    items = [l for l in body.splitlines() if re.match(r"^\s*([-*•]|\d+[.)])\s", l)]
    if items:
        return len(items)
    return len([x for x in re.split(r"[;；]|\s/\s", body) if x.strip()])


def filler(run):
    """L 의 일반 수칙 중 코드로 잴 수 있는 것. 빌드에 있는 파이썬 전체."""
    funcs, ret, long_f, doc_mod, has_print, has_log = 0, 0, 0, True, False, False
    pys = code_files(run, (".py",))
    for p in pys:
        src = read(p)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        doc_mod = doc_mod and bool(ast.get_docstring(tree))
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs += 1
                ret += n.returns is not None
                long_f += (n.end_lineno - n.lineno + 1) > 40
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print":
                has_print = True
        has_log = has_log or "logging" in imports_of(src)
    htmls = "".join(read(p) for p in code_files(run, (".html",)))
    tests_new = [os.path.basename(p) for p in glob.glob(os.path.join(run, "tests", "*.py")) if os.path.basename(p) not in ("test_dod.py", "conftest.py", "__init__.py")]
    other_tests = [os.path.basename(p) for p in glob.glob(os.path.join(run, "test_*.py"))]
    return {"F1 모듈 docstring": bool(pys) and doc_mod, "F2 함수 반환 타입 힌트 90%": bool(funcs) and ret / funcs >= 0.9, "F3 README": os.path.exists(os.path.join(run, "README.md")),
            "F4 print 없음": not has_print, "F5 logging 씀": has_log, "F6 단위 테스트 추가": bool(tests_new + other_tests), "F7 함수 40줄 이하": long_f == 0,
            "F8 접근성 이름": bool(re.search(r"aria-label|<label", htmls)), "funcs": funcs, "ret": ret, "long_funcs": long_f, "tests_new": tests_new + other_tests}


def sizes(run):
    n_py = sum(len(read(p).splitlines()) for p in code_files(run, (".py",)))
    n_web = sum(len(read(p).splitlines()) for p in code_files(run, (".html", ".js", ".css")))
    files = [os.path.relpath(p, run).replace(os.sep, "/") for p in glob.glob(os.path.join(run, "**", "*"), recursive=True)
             if os.path.isfile(p) and "__pycache__" not in p and not p.endswith((".db", ".pyc")) and ".claude" not in p and "_grader" not in p]
    return {"py_lines": n_py, "web_lines": n_web, "file_count": len(files), "files": files}


out_p = os.path.join(lab, "rules_results.json")
out = json.load(open(out_p, encoding="utf-8")) if os.path.exists(out_p) else {}
for name in sorted(R):
    if only and name not in only:
        continue
    run = os.path.join(lab, "runs", name)
    r = R[name]
    b = json.load(open(os.path.join(run, "build.json"), encoding="utf-8"))
    res = (b.get("result") or "").strip()
    er = r.get("extra_routes") or []
    checks = {}
    for k, fn in [("K1", lambda: k1(run)), ("K2", lambda: k2(run)), ("K3", lambda: k3(run)), ("K4", lambda: k4(run)), ("K5", lambda: k5(name, res, r["passed"])),
                  ("K6", lambda: (r.get("tests_modified") is False, r.get("tests_modified"))), ("K7", lambda: k7(run)), ("K8", lambda: k8(run, er)),
                  ("K9", lambda: k9(res)), ("K10", lambda: k10(res)), ("K11", lambda: k11(res, er))]:
        ok, why = fn()
        checks[k] = {"ok": ok, "why": why}
    u = b.get("usage") or {}
    out[name] = {"passed": r["passed"], "checks": checks, "kept": sum(1 for c in checks.values() if c["ok"]), "unknown": sum(1 for c in checks.values() if c["ok"] is None),
                 "decided": decided_count(res), "filler": filler(run), "sizes": sizes(run), "turns": b.get("num_turns"), "cost": b.get("total_cost_usd"), "wall_s": b.get("wall_s"),
                 "input_tokens": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
                 "result_chars": len(res)}
json.dump(out, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

names = sorted(out, key=lambda x: (x[0], int(re.sub(r"\D", "", x) or 0)))
keys = [k for k, _, _ in K_INFO]
print("| 실행 | DoD | " + " | ".join(keys) + " | 지킴 | 직접 정한 것 | 턴 | 비용 | 코드 줄(py+web) | 파일 |")
print("|---|---|" + "---|" * (len(keys) + 6))
for n in names:
    o = out[n]
    marks = ["O" if o["checks"][k]["ok"] else ("?" if o["checks"][k]["ok"] is None else "X") for k in keys]
    print("| %s | %d/9 | %s | %d/11 | %s | %s | $%.2f | %d+%d | %d |" % (n, o["passed"], " | ".join(marks), o["kept"], o["decided"], o["turns"], o["cost"] or 0,
                                                                  o["sizes"]["py_lines"], o["sizes"]["web_lines"], o["sizes"]["file_count"]))
print()
for k, label, only_md in K_INFO:
    print(k, label, "(CLAUDE.md 에만)" if only_md else "(PRD 에도)")
print()
fk = [k for k in out[names[0]]["filler"] if k.startswith("F")]
print("| 실행 | " + " | ".join(fk) + " |")
print("|---|" + "---|" * len(fk))
for n in names:
    print("| %s | %s |" % (n, " | ".join("O" if out[n]["filler"][k] else "-" for k in fk)))
print()
for n in names:
    for k in keys:
        c = out[n]["checks"][k]
        if c["ok"] is not True:
            print(n, k, json.dumps(c["why"], ensure_ascii=False)[:400])
