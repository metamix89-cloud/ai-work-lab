# -*- coding: utf-8 -*-
"""Owner column analysis: one person (a name or a role) or several teams?"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
for c, col in (("A", 2), ("B", 4)):
    tot = one = multi = 0
    for r in [x for x in rs if x["cond"] == c]:
        for row in lab.parse(r["report"]):
            if len(row["cells"]) <= col:
                continue
            o = row["cells"][col]
            tot += 1
            if re.search(r"[,/&+]|\band\b|\bwith\b", o, re.I):
                multi += 1
            elif re.search(r"\b(lead|manager|engineer|owner|analyst|head|director|specialist|admin|developer|officer|coordinator)\b|^[A-Z][a-z]+( [A-Z]\.?[a-z]*)?$", o) and not re.search(r"team$|department$|group$", o, re.I):
                one += 1
    print(c, "rows %d · several owners %d (%.0f%%) · one person or role %d (%.0f%%)" % (tot, multi, 100 * multi / max(tot, 1), one, 100 * one / max(tot, 1)))
