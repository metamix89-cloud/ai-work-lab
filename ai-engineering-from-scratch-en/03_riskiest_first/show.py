# -*- coding: utf-8 -*-
"""Read es03 results by hand.
Usage: python show.py <cond> [i ...]            full plans (+ stage-2 decision if present)
       python show.py <cond> secfirst            the security line and the first build line in each plan part (why sec_first passed/failed)
       python show.py <cond> thr                 lines with a number + % or N of M (criterion candidates)
       python show.py <cond> auto                lines that matched the automatic-refund rule
       python show.py <cond> decide              stage-2 decisions only"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
mode = next((a for a in sys.argv[2:] if not a.isdigit()), "")
idx = [int(a) for a in sys.argv[2:] if a.isdigit()]
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    head = "=" * 20 + " %s %d | sec %s first %s past %s thr %s fail %s auto %s all %s" % (cond, r["i"], r["sec"], r["sec_first"], r["past"], r["thr"], r["fail"], r["auto"], r["all"])
    if mode == "secfirst":
        p = lab.lines(lab.plan_part(r["report"]))
        si = next((i for i, l in enumerate(p) if lab.SEC.search(l) and lab.SEC_OK.search(l)), None)
        bi = next((i for i, l in enumerate(p) if lab.BUILD.search(l) and not lab.SEC.search(l) and not lab.NOT_BUILD.search(l)), None)
        print(head)
        print("   plan starts:", p[0][:100] if p else "-")
        print("   SEC  line %s: %s" % (si, p[si][:160] if si is not None else "-"))
        print("   BUILD line %s: %s" % (bi, p[bi][:160] if bi is not None else "-"))
    elif mode == "thr":
        print(head)
        for l in lab.lines(r["report"]):
            if lab.THR_NUM.search(l):
                print("   %s%s" % ("* " if lab.THR_WORD.search(l) and not lab.THR_NOT.search(l) else "  ", l.strip()[:170]))
    elif mode == "auto":
        print(head)
        for l in lab.lines(lab.plan_part(r["report"])):
            if lab.AUTO_R.search(l) and lab.AUTO_GO.search(l) and not lab.AUTO_NOT.search(l):
                print("   >>", l.strip()[:200])
    elif mode == "decide":
        print(head, "| choice", r.get("choice"), "| cites", r.get("cites"))
        print("   ", (r.get("answer") or "")[:600].replace("\n", " / "))
    else:
        print(head)
        print(r["report"][:7000])
        if r.get("answer"):
            print("--- DECISION:", r.get("choice"), "\n", r["answer"][:1200])
