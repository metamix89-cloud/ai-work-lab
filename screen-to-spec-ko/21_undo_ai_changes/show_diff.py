# -*- coding: utf-8 -*-
"""원본(base/)과 실행 폴더의 바뀐 줄 목록을 보여 준다.
사용: python _scratch/s2s/21_undo_ai_changes/show_diff.py broken U2_1 ... [--file=main.py]"""
import difflib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
only = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--file=")]
for n in [a for a in sys.argv[1:] if not a.startswith("--")]:
    d = os.path.join(HERE, n if n == "broken" else os.path.join("runs", n))
    for rel in only or ["main.py", "static/index.html", "PRD.md"]:
        a = open(os.path.join(HERE, "base", rel), encoding="utf-8").read().replace("\r\n", "\n").split("\n")
        b = open(os.path.join(d, rel), encoding="utf-8").read().replace("\r\n", "\n").split("\n")
        out = [l for l in difflib.unified_diff(a, b, "base/" + rel, n + "/" + rel, lineterm="", n=0)]
        print("\n".join(out) if out else "== %s/%s 같음" % (n, rel))
