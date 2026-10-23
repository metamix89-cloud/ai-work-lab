import json, lab
rs = json.load(open("results.json", encoding="utf-8"))
for r in rs:
    r["pick"] = lab.pick(r["report"])
    if r["cond"] in "PQ":
        r.update(lab.proposal_checks(r["report"]))
json.dump(rs, open("results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lab.summary(rs)
