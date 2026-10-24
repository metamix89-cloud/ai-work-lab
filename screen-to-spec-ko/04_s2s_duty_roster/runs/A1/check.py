"""서버가 떠 있는 상태에서: python check.py YYYY-MM  -> 배정 검증"""
import json, sys, urllib.request

ym = sys.argv[1] if len(sys.argv) > 1 else "2026-10"
d = json.load(urllib.request.urlopen(f"http://localhost:8000/api/schedule/{ym}"))
duty = d["duty"]
lv = {(l["nurse_id"], l["day"]) for l in d["leaves"]}
ds = sorted(duty)
print("배정 일수:", len(ds))
print("휴가 충돌:", [k for k, v in duty.items() if (v, k) in lv])
print("연속 당직:", sum(duty[a] == duty[b] for a, b in zip(ds, ds[1:])))
for s in d["stats"]:
    print(s["name"], "당직", s["duties"], "휴가", s["leave_days"])
