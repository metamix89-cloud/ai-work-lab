# -*- coding: utf-8 -*-
"""runs/*/build.json 의 마지막 답 · 턴 · 비용을 한눈에 (원고용).
사용: python _scratch/s2s/tools/show_builds.py <lab_dir> [--full]"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
lab = os.path.abspath(sys.argv[1])
full = "--full" in sys.argv
for p in sorted(glob.glob(os.path.join(lab, "runs", "*", "build.json"))):
    b = json.load(open(p, encoding="utf-8"))
    u = b.get("usage") or {}
    tok = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0))
    print("=== %s  턴 %s · %.0f초 · $%.2f · 입력 %s · 출력 %s" % (os.path.basename(os.path.dirname(p)), b.get("num_turns"), b.get("wall_s", 0),
                                                              b.get("total_cost_usd") or 0, tok[0], tok[1]))
    r = (b.get("result") or "").strip()
    print(r if full else r[-700:])
    print()
