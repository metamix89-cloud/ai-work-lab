# -*- coding: utf-8 -*-
"""빌더 기록(jsonl)에서 도구 호출과 글을 차례로 짧게 보여 준다 — 무엇을 읽고 무엇을 돌렸나.
사용: python _scratch/s2s/20_feature_regression/show_session.py <run 이름 | session_id> [--full]"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
arg = sys.argv[1]
full = "--full" in sys.argv
b = os.path.join(HERE, "runs", arg, "build.json")
sid = json.load(open(b, encoding="utf-8")).get("session_id") if os.path.exists(b) else arg
found = glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", sid + ".jsonl"))
if not found:
    sys.exit("기록 없음: %s" % sid)
n = 400 if full else 160
for line in open(found[0], encoding="utf-8", errors="ignore"):
    try:
        j = json.loads(line)
    except ValueError:
        continue
    msg = j.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        print("[%s] %s" % (j.get("type"), content[:n].replace("\n", " ")))
        continue
    for c in content or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            print("[글] " + c["text"][:n].replace("\n", " "))
        elif c.get("type") == "tool_use":
            inp = c.get("input") or {}
            print("[도구 %s] %s" % (c.get("name"), json.dumps(inp, ensure_ascii=False)[:n]))
        elif c.get("type") == "tool_result" and full:
            body = c.get("content")
            text = body if isinstance(body, str) else " ".join(x.get("text", "") for x in body or [] if isinstance(x, dict))
            print("   [결과] " + text[:200].replace("\n", " "))
