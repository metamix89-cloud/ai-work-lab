# -*- coding: utf-8 -*-
"""Hand judgment of all 30 sequence tables (python show.py A / B / C): is the customer SMS send placed AFTER the intake-screen (system) change,
by the table's 'must finish first' column? Stored as sms_after_system_manual in results.json.
Notes: A8 has no dependency from the SMS to the deploy, but its tasks carry dates (deploy 10/31, SMS from 11/3) - counted as after.
C7 sends the SMS at item 6 (depends only on the template) and 'launches' it again at item 7 (after the deploy) - counted as not after.
'Prepare and send' written on one line (A4, A7, B1, C2) counts as the send."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "results.json")
YES = {"A": {0, 1, 2, 3, 8, 9}, "B": {2}, "C": {0, 1, 3, 8}}
rs = json.load(open(p, encoding="utf-8"))
for r in rs:
    r["sms_after_system_manual"] = r["i"] in YES[r["cond"]]
json.dump(rs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for c in "ABC":
    x = [r for r in rs if r["cond"] == c]
    print(c, "SMS after system - code %d · by hand %d / %d" % (sum(1 for r in x if r["sms_after_system"] is True), sum(1 for r in x if r["sms_after_system_manual"]), len(x)),
          "| items avg %.1f · waves %.1f" % (sum(r["n_rows"] for r in x) / len(x), sum(r["waves"] for r in x) / len(x)))
