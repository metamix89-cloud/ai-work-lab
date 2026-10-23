# -*- coding: utf-8 -*-
"""Re-grade saved runs with the current grader (no API calls). Rebuilds the file system from the stored 'changed' map."""
import copy, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
import lab
HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "results.json")
rs = json.load(open(p, encoding="utf-8"))
for r in rs:
    fs = copy.deepcopy(lab.FS0)
    fs.update(r["changed"])
    r.update(lab.grade(fs, dict(reads=r["reads"], writes=r["writes"]), r["final"]))
json.dump(rs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lab.summary(rs)
