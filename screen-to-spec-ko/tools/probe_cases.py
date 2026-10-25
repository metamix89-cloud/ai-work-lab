# -*- coding: utf-8 -*-
"""여러 결과물에 같은 요청 몇 개를 보내 응답 코드를 나란히 본다 — PRD 가 정하지 않은 틈을 각자 어떻게 메웠는지 비교할 때.
각 앱을 임시 폴더로 복사하고, 그 편 테스트의 고정 데이터(write_seed)를 넣고 띄운다. 원본 runs/ 는 건드리지 않는다.
사용: python _scratch/s2s/tools/probe_cases.py <lab_dir> <cases.json> <app_dir> [<app_dir> ...] [--port=9300]
cases.json: [{"name": "설명", "method": "POST", "path": "api/carts/{cart}/items", "body": {...}}, ...]
  경로의 {cart} 는 POST /api/carts 로 새로 받은 cart_id 로 바뀐다(그 편에 /api/carts 가 있을 때).
  "find": {"key": "product_id", "value": "P04", "field": "stock"} — 목록 응답에서 그 항목의 칸 값을 보여 준다.
  고정 데이터에 행을 더하려면 cases.json 을 {"add": {"ORDERS": [[...]], "LINES": [[...]]}, "cases": [...]} 로 —
  키는 그 편 test_dod.py 의 표 이름(대문자 리스트)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def call(base, method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + "/" + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return "ERR", str(e)


def probe(app_src, lab, cases, port, add=None):
    work = os.path.join(tempfile.mkdtemp(), "app")
    shutil.copytree(app_src, work, ignore=shutil.ignore_patterns("_grader", "__pycache__", "*.db", "seed_backup"))
    os.environ["APP_DIR"] = work
    spec = importlib.util.spec_from_file_location("dod", os.path.join(lab, "tests", "test_dod.py"))
    dod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dod)
    for table, rows in (add or {}).items():
        getattr(dod, table).extend(tuple(r) for r in rows)
    dod.write_seed()
    target, _ = dod.find_app_target()
    logf = tempfile.TemporaryFile()
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--port", str(port)], cwd=work,
                         env=dict(os.environ, PORT=str(port), PYTHONUTF8="1"), stdout=logf, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % port
    out = []
    try:
        for _ in range(40):
            if call(base, "GET", "")[0] == 200:
                break
            time.sleep(0.5)
        st, raw = call(base, "POST", "api/carts")
        try:
            cart = json.loads(raw).get("cart_id", "none")
        except Exception:
            cart = "none"
        def fill(obj):
            """본문 속 "__이름_PLUS_분__" 을 test_dod 의 시각 상수(이름) + 분 으로 바꾼다 (2부 4편: 지연 분을 지금 기준으로 줘야 함)"""
            if isinstance(obj, dict):
                return {k: fill(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [fill(v) for v in obj]
            if isinstance(obj, str):
                m = re.fullmatch(r"__([A-Z][A-Z0-9_]*?)_PLUS_(-?\d+)__", obj)
                if m and hasattr(dod, m.group(1)):
                    return dod.plus(getattr(dod, m.group(1)), int(m.group(2))) if hasattr(dod, "plus") else getattr(dod, m.group(1))
            return obj
        for c in cases:
            st, raw = call(base, c["method"], c["path"].replace("{cart}", str(cart)), fill(c.get("body")))
            try:
                j = json.loads(raw)
                if c.get("pick") and isinstance(j, dict):        # "pick": "metrics.cancel_rate" — 응답 속 값을 점 경로로
                    v = j
                    for part in c["pick"].split("."):
                        v = v.get(part, "키 없음") if isinstance(v, dict) else v
                    detail = "%s=%s" % (c["pick"], json.dumps(v, ensure_ascii=False)[:70])
                elif c.get("find") and isinstance(j, list):
                    f = c["find"]
                    hit = [x for x in j if str(x.get(f["key"])) == f["value"]]
                    detail = "%s=%s" % (f["field"], hit[0].get(f["field"]) if hit else "없음")
                else:
                    detail = j.get("detail", "") if isinstance(j, dict) else raw[:40]
            except Exception:
                detail = raw[:40]
            out.append((c["name"], st, str(detail)[:40]))
    finally:
        p.kill()
        p.wait(timeout=10)
        logf.close()
        shutil.rmtree(os.path.dirname(work), ignore_errors=True)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = 9300
    for a in sys.argv[1:]:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    lab, cases_path, apps = os.path.abspath(args[0]), args[1], args[2:]
    spec = json.load(open(cases_path, encoding="utf-8"))
    cases, add = (spec["cases"], spec.get("add")) if isinstance(spec, dict) else (spec, None)
    for app in apps:
        print("===", os.path.basename(os.path.normpath(app)))
        for name, st, detail in probe(os.path.abspath(app), lab, cases, port, add):
            print("  %-36s %s  %s" % (name, st, detail))
        port += 1


if __name__ == "__main__":
    main()
