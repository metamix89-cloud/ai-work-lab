# -*- coding: utf-8 -*-
"""Print the sequence tables for reading by hand. Usage: python show.py <cond> [i ...]   (each row: number · kind the grader assigned · task · depends on)"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
idx = [int(a) for a in sys.argv[2:]]
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    rows = lab.parse_table(r["report"])
    print("=" * 12, cond, r["i"], "| sms after legal", r["sms_after_legal"], "· after system", r["sms_after_system"], "| web after legal", r["web_after_legal"], "| waves", r["waves"])
    for n in sorted(rows):
        t, deps = rows[n]
        print("   %2d [%-7s] %-90s <- %s" % (n, lab.kind_of(t), t[:90], deps))
