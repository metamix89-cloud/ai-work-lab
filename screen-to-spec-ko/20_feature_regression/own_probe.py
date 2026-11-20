# -*- coding: utf-8 -*-
"""ep097 '자기 이름' 채점 — 문서 없이 기능을 더한 앱(M1 · M2)은 칸 이름 · 주소를 제멋대로 정한다.
PRD 이름(repeat_weeks · scope)으로 부르면 규칙을 지켰어도 떨어지므로, 회차마다 그 앱의 이름으로 같은 T10~T12 를 다시 돈다.
이름은 사람이 코드(show_diff.py)를 읽고 own_adapters.json 에 적는다. 상태 코드는 2xx / 4xx 로만 본다(느슨한 채점).
  bad_weeks 는 그 앱이 스스로 정한 범위의 바깥 값, ok_weeks 는 그 앱의 최댓값(8 보다 크면 '회사 숫자와 다름' 으로 따로 적는다).
사용: python _scratch/s2s/20_feature_regression/own_probe.py [--only=M1_1]   → summary.json 에 new_pass_own · own_detail · own_adapter 추가"""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from grade_run import grade_dir   # noqa: E402
from port_block import PortBlock   # noqa: E402

only = next((set(a.split("=", 1)[1].split(",")) for a in sys.argv[1:] if a.startswith("--only=")), None)
adapters = json.load(open(os.path.join(HERE, "own_adapters.json"), encoding="utf-8"))
sum_path = os.path.join(HERE, "summary.json")
summary = json.load(open(sum_path, encoding="utf-8"))
for name, ad in sorted(adapters.items()):
    if name.startswith("_") or (only and name not in only):
        continue
    ad = dict(ad, strict=False)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(ad, f, ensure_ascii=False)
    os.environ["RECUR_ADAPTER"] = f.name
    try:
        with PortBlock(9300) as pb:
            r = grade_dir(os.path.join(HERE, "runs", name), os.path.join(HERE, "tests"), port=pb.port)
    finally:
        os.environ.pop("RECUR_ADAPTER", None)
        os.remove(f.name)
    new = [t for t in ("T10", "T11", "T12") if r["tests"].get(t) == "pass"]
    s = summary.setdefault(name, {})
    s["new_pass_own"] = len(new)
    s["own_passed"] = new
    s["own_detail"] = {t: (r["detail"].get(t) or "")[:400] for t in ("T10", "T11", "T12") if t not in new}
    s["own_adapter"] = ad
    print("%s 자기 이름으로 새 기준 %d/3 %s" % (name, len(new), new))
    for t, d in s["own_detail"].items():
        print("    ", t, d[:260].replace("\n", " "))
    json.dump(dict(sorted(summary.items())), open(sum_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
