# -*- coding: utf-8 -*-
"""AI 가 쓴 테스트를 심은 실수 6개에 붙이고(규칙 + 사람 덮어쓰기), 조건별로 센다 — ep093.
  M1 붙여 예약 거절(<=)   M2 30분 단위 검사 없음   M3 2시간 상한 없음
  M4 누구나 취소          M5 칸 상태 표시 없음(data-state)   M6 취소 버튼 없음
입력: <lab>/ai_tests_results.json (grade_ai_tests.py) · <lab>/ai_tests_labels.json (사람이 덮어쓴 라벨, 없어도 됨)
출력: <lab>/ai_tests_summary.json + 표 출력. 자동 라벨은 이름 · 소스의 글자로 붙인 것이라 사람이 덤프를 읽고 확인한다.
사용: python _scratch/s2s/tools/label_ai_tests.py <lab> [--list]"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
MIS = {"M1": "붙여 예약 거절", "M2": "30분 단위 없음", "M3": "2시간 상한 없음", "M4": "누구나 취소", "M5": "칸 상태 없음", "M6": "취소 버튼 없음"}
NON30 = re.compile(r"\d\d:(?:0[1-9]|1\d|2\d|3[1-9]|4\d|5\d)\b")


def guess(name, src):
    n, s = name.lower(), src or ""
    if "cancel-btn" in s or "cancel_button" in n or "cancel_btn" in n:
        return "M6"
    if re.search(r"non_owner|other_user|others_403|other_users|forbidden|cannot_cancel|delete_others|delete_other|by_other|not_owner|cannot_delete", n) \
            or ("403" in s and re.search(r"delete|cancel", n)):
        return "M4"
    if re.search(r"adjacent|back_to_back|next_to|contiguous|touching", n) or "붙" in s and "201" in s and "data-state" not in s:
        return "M1"
    if re.search(r"two_hours|2h|over_2|2_hours|max_dur|over_two|two_hour", n) or ("11:30" in s and "09:00" in s and "400" in s) or "2시간" in s and "400" in s:
        return "M3"
    if re.search(r"30min|30_min|non_30|not_30|minute_unit|unit", n) or (NON30.search(s) and "400" in s):
        return "M2"
    if "data-state" in s or re.search(r"booked|mine|slot_state|seed_reservations_show|switching_user|changing_user|cover_", n):
        return "M5"
    return "other"


def main():
    lab = os.path.abspath(sys.argv[1])
    show = "--list" in sys.argv
    res = json.load(open(os.path.join(lab, "ai_tests_results.json"), encoding="utf-8"))
    lp = os.path.join(lab, "ai_tests_labels.json")
    manual = json.load(open(lp, encoding="utf-8")) if os.path.exists(lp) else {}
    summary = {}
    for run, r in sorted(res.items()):
        names = sorted(set(r["ref_app"]["tests"]) | set(r["trap_app"]["tests"]))
        funcs = r.get("functions", {})
        caught, codified, false_alarm, setup, other_diff, labels = {}, [], [], [], [], {}
        for n in names:
            base = re.sub(r"\[.*\]$", "", n)
            src = funcs.get(n) or funcs.get(base) or ""
            lab_ = (manual.get(run, {}).get(n) or manual.get(run, {}).get(base) or guess(base, src))
            labels[n] = lab_
            a = r["ref_app"]["tests"].get(n, {}).get("status", "-")
            b = r["trap_app"]["tests"].get(n, {}).get("status", "-")
            amsg = (r["ref_app"]["tests"].get(n, {}).get("msg") or "")
            bmsg = (r["trap_app"]["tests"].get(n, {}).get("msg") or "")
            if a == "error" and b == "error" or ("ModuleNotFound" in amsg + bmsg or "ImportError" in amsg + bmsg or "fixture" in (amsg + bmsg)[:120]):
                setup.append(n)
                continue
            if a != "pass":
                false_alarm.append(n)
                if b == "pass":
                    codified.append(n)
                continue
            if b != "pass":
                if lab_ in MIS:
                    caught.setdefault(lab_, []).append(n)
                else:
                    other_diff.append(n)
        summary[run] = {"cond": (r.get("info") or {}).get("cond"), "n": len(names), "caught": sorted(caught), "caught_tests": caught,
                        "false_alarm": false_alarm, "codified": codified, "setup_error": setup, "other_diff": other_diff,
                        "cost": (r.get("info") or {}).get("total_cost_usd"), "turns": (r.get("info") or {}).get("num_turns"),
                        "conftest_modified": (r.get("info") or {}).get("conftest_modified"), "labels": labels}
        print("%-8s 테스트 %3d · 잡은 실수 %d/6 %s · 오판 %d(굳힘 %d) · 설정 오류 %d · 심은 것 밖 차이 %d · $%.2f" % (
            run, len(names), len(caught), "".join(k[1] for k in sorted(caught)), len(false_alarm), len(codified), len(setup), len(other_diff),
            (r.get("info") or {}).get("total_cost_usd") or 0))
        if show:
            for n in names:
                a = r["ref_app"]["tests"].get(n, {}).get("status", "-")
                b = r["trap_app"]["tests"].get(n, {}).get("status", "-")
                print("   %-5s 정답 %-5s 함정 %-5s %s" % (labels[n], a, b, n))
    json.dump(summary, open(os.path.join(lab, "ai_tests_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→ ai_tests_summary.json")


if __name__ == "__main__":
    main()
