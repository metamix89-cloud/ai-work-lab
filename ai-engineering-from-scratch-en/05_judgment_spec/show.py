# -*- coding: utf-8 -*-
"""Read es05 runs by hand. Usage: python show.py <spec U|O|S> [case ...] [fails]   - prints tool calls, messages and the grade per run"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
spec = sys.argv[1]
cases = [int(a) for a in sys.argv[2:] if a.isdigit()]
only_fails = "fails" in sys.argv[2:]
for r in sorted(rs, key=lambda r: (r["case"], r["trial"])):
    if r["spec"] != spec or (cases and r["case"] not in cases) or (only_fails and r["ok"]):
        continue
    st = r["state"]
    print("=" * 16, spec, "case", r["case"], "trial", r["trial"], "| ok", r["ok"], "| viol", r["viol"], "| miss", r["miss"], "| extra", r["extra"])
    print("   Q:", lab.CASES[r["case"]][0][:140])
    print("   looked", st["looked"], "| refund", st["refund"], "| coupon", st["issue_coupon"], "| escalate", [e[:80] for e in st["esc"]])
    for m in st["msgs"]:
        print("   MSG:", m[:300].replace("\n", " / "))
    if st.get("final"):
        print("   FINAL:", st["final"][:300].replace("\n", " / "))
