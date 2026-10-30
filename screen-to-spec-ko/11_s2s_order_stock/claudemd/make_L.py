# -*- coding: utf-8 -*-
"""L.md(150줄) = filler_before(일반 수칙) + S.md(15줄 그대로) + filler_after(일반 수칙). 줄 수를 확인하고 쓴다.
일반 수칙은 우리가 직접 썼다(공개 템플릿 복사 아님). S 와 정면으로 부딪치는 줄은 넣지 않았다 — 완료 보고 · 요약 지시, 새 패키지 요구, API 모양 지시 없음.
사용: python _scratch/s2s/11_s2s_order_stock/claudemd/make_L.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.dirname(os.path.abspath(__file__))


def lines(name):
    return open(os.path.join(D, name), encoding="utf-8").read().splitlines()


before, s, after = lines("filler_before.md"), lines("S.md"), lines("filler_after.md")
print("앞", len(before), "· S", len(s), "· 뒤", len(after), "· 합", len(before) + len(s) + len(after), "· 일반 수칙", len(before) + len(after))
if len(s) != 15 or len(before) + len(after) != 135:
    sys.exit("줄 수가 맞지 않음 — S 15 · 일반 수칙 135")
with open(os.path.join(D, "L.md"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(before + s + after) + "\n")
print("썼음:", os.path.join(D, "L.md"), "· S 는 %d~%d줄" % (len(before) + 1, len(before) + 15))
