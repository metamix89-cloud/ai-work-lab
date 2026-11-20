# -*- coding: utf-8 -*-
"""own_adapters.json 을 쓴다 — M1 · M2 아홉 앱이 스스로 정한 이름(사람이 show_diff.py 로 코드를 읽고 옮김, 2026-11-15).
반복 횟수 칸 이름 · 묶음 취소 방법(없으면 None). 아홉 앱 모두 횟수는 '첫 회 포함 전체 횟수', 범위 1~12 였다.
사용: python _scratch/s2s/20_feature_regression/make_adapters.py"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ONE = "/api/reservations/{res_id}?user={user}"
SERIES = "/api/reservations/{res_id}?user={user}&series=true"
#        이름      횟수 칸          묶음 취소
APPS = [("M1_1", "weekly_count", SERIES), ("M1_2", "weeks", None), ("M1_3", "repeat_weeks", SERIES),
        ("M1_4", "weeks", SERIES), ("M1_5", "repeat_weeks", None), ("M1_6", "repeat_weeks", None),
        ("M2_1", "weeks", None), ("M2_2", "weeks", SERIES), ("M2_3", "repeat_weeks", None)]
out = {"_note": "M1 · M2 가 스스로 정한 이름. 범위는 아홉 앱 모두 1~12 — bad_weeks 는 그 바깥, ok_weeks 는 그 앱의 최댓값."}
for name, field, series in APPS:
    out[name] = {"weeks_field": field, "weeks_mode": "count", "cancel_one": ONE, "cancel_following": series,
                 "following_is_all": False, "bad_weeks": [0, 13, "abc"], "ok_weeks": 12}
json.dump(out, open(os.path.join(HERE, "own_adapters.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("썼음: own_adapters.json", len(APPS))
