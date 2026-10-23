# -*- coding: utf-8 -*-
"""Read es06 results by hand.
Usage: python show.py <cond> decide [i ...]     the decision and its reasons
       python show.py C plan [i ...]            lines of C's own plan that set guardrail / refund / health thresholds, and the failure lines
       python show.py C full <i>                the whole plan"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond, mode = sys.argv[1], sys.argv[2]
idx = [int(a) for a in sys.argv[3:]]
G = re.compile(r"guardrail|out-of-policy|refund|health|allerg|hand-?off|escalat", re.I)
F = re.compile(r"\bfail|inconclusive|if .* (broken|violated|exceed)|pass:|pass ", re.I)
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    print("=" * 16, cond, r["i"], "| decision", r["choice"], "| mentions refund %s health %s recontact %s staff %s" % (r["refund"], r["health"], r["recontact"], r["staff"]))
    if mode == "decide":
        print("   ", r["answer"][:900].replace("\n", " / "))
    elif mode == "plan":
        for l in (r.get("plan") or "").splitlines():
            if G.search(l) and re.search(r"\d|zero|none|no ", l, re.I):
                print("   G:", l.strip()[:200])
        for l in (r.get("plan") or "").splitlines():
            if F.search(l):
                print("   F:", l.strip()[:200])
    else:
        print(r.get("plan") or "")
