# -*- coding: utf-8 -*-
"""곁다리 손상: 원본에도, 정답에도 없는 줄이 최종 문서에 생겼나 (남의 칸을 통째로 다시 쓰다 생긴 오타 · 기호 빠짐).
사용: python side_damage.py"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
good = lab.DOC.replace("73,400원", "79,270원").replace("46,200원", "47,500원").replace("견과 선물세트: 땅콩", "견과 선물세트: 땅콩, 호두, 아몬드") \
    .replace("김자반 50g: 대두", "김자반 50g: 대두, 참깨").replace("오후 3시", "오후 2시").replace("7일 이내", "14일 이내")
ok_lines = {l.strip() for l in (lab.DOC + good).splitlines() if l.strip()}
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
for c in ["A", "C", "B", "S"]:
    x = [r for r in rs if r["cond"] == c]
    bad = []
    for r in x:
        odd = [l.strip() for l in r["final"].splitlines() if l.strip() and l.strip() not in ok_lines]
        if odd:
            bad.append((r["i"], odd))
    print(c, "곁다리 손상 %d/%d" % (len(bad), len(x)))
    for i, odd in bad[:4]:
        print("   ", i, odd[:3])
