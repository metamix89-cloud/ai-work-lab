# -*- coding: utf-8 -*-
"""ep089 — seed 의 줄 하나가 상품을 못 찾을 때 서버가 뜨는지 본다(결과를 보고 나서 추가한 검사, 미리 정한 K 규칙 아님).
첫 탐침에서 L 셋만 서버가 안 떴다 → 무엇 때문인지 데이터를 하나씩 바꿔 가며 확인한다.
고정 데이터(test_dod.write_seed) + 경우별 추가 줄로, 앱 사본을 임시 폴더에서 띄운다. 원본 runs/ 는 건드리지 않는다.
사용: python _scratch/s2s/tools/ep089_start_probe.py <lab_dir> <run> [<run> ...] → <lab_dir>/start_probe.json + 표"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
lab = os.path.abspath(sys.argv[1])
runs = sys.argv[2:]
CASES = {"그대로": {}, "같은 상품 두 줄": {"ORDERS": [("O-2001", "같은 상품 두 줄", "placed", "2026-10-24 11:00")], "LINES": [("O-2001", "P04", 2), ("O-2001", "P04", 2)]},
         "없는 상품 줄": {"ORDERS": [("O-2003", "없는 상품 줄", "placed", "2026-10-24 11:10")], "LINES": [("O-2003", "P99", 1)]}}


def get(base, path):
    try:
        return urllib.request.urlopen(base + path, timeout=3).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def trial(run, add, port):
    work = os.path.join(tempfile.mkdtemp(), "app")
    shutil.copytree(os.path.join(lab, "runs", run), work, ignore=shutil.ignore_patterns("_grader", "__pycache__", "*.db", "seed_backup"))
    os.environ["APP_DIR"] = work
    spec = importlib.util.spec_from_file_location("dod", os.path.join(lab, "tests", "test_dod.py"))
    dod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dod)
    for table, rows in add.items():
        getattr(dod, table).extend(rows)
    dod.write_seed()
    target, _ = dod.find_app_target()
    log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--port", str(port)], cwd=work, env=dict(os.environ, PYTHONUTF8="1"),
                         stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % port
    up, confirm = False, None
    for _ in range(24):
        if p.poll() is not None:
            break
        if get(base, "/") == 200:
            up = True
            break
        time.sleep(0.5)
    if up and add:
        confirm = post(base, "/api/orders/%s/confirm" % add["ORDERS"][0][0], {"user": "u1"})
    if p.poll() is None:
        p.kill()
    p.wait(timeout=10)
    log.close()
    tail = open(log.name, encoding="utf-8", errors="ignore").read().strip().splitlines()
    os.unlink(log.name)
    shutil.rmtree(os.path.dirname(work), ignore_errors=True)
    err = next((l for l in reversed(tail) if "Error" in l), "") if not up else ""
    return {"up": up, "confirm": confirm, "error": err[:160]}


out, port = {}, 9400
for run in runs:
    out[run] = {}
    for name, add in CASES.items():
        out[run][name] = trial(run, add, port)
        port += 1
        r = out[run][name]
        print("%-3s %-14s 서버 %s · 확정 %s %s" % (run, name, "뜸" if r["up"] else "안 뜸", r["confirm"], r["error"]), flush=True)
json.dump(out, open(os.path.join(lab, "start_probe.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("→ start_probe.json")
