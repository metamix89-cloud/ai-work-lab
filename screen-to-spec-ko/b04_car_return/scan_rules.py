# -*- coding: utf-8 -*-
"""A(한 줄) · D(한 줄 + 회사 숫자) 결과물의 코드에서 회사 숫자 · 규칙이 어떻게 정해졌나 훑는다 (사람이 코드로 확인하기 전 1차).
사용: python _scratch/s2s/b04_car_return/scan_rules.py [A1 A2 ...]  (없으면 runs/ 전부)"""
import glob
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = [
    ("유예 30분", r"grace|GRACE|유예"),
    ("시간당 10,000", r"10[_,]?000"),
    ("상한 80,000", r"80[_,]?000|cap|CAP|상한|max_late|MAX_LATE"),
    ("연료 칸당 15,000", r"15[_,]?000"),
    ("손상 30k/150k/500k", r"150[_,]?000"),
    ("대여 전 손상 제외", r"pre[_-]?exist|pre_damage|기존 손상|대여 전|preexisting|prior"),
    ("사진 필수", r"photo"),
    ("로그인", r"/api/login|password|로그인"),
    ("사진 업로드", r"UploadFile|multipart|/api/photos|/api/uploads"),
]


def src_of(run):
    out = []
    for p in glob.glob(os.path.join(run, "**", "*"), recursive=True):
        if os.path.isfile(p) and p.endswith((".py", ".html", ".js")) and "_grader" not in p and os.sep + "tests" + os.sep not in p:
            try:
                out.append(open(p, encoding="utf-8", errors="ignore").read())
            except OSError:
                pass
    return "\n".join(out)


def numbers_near(src, key, width=80):
    """키워드 주변의 숫자 — 유예 · 시간당 · 상한이 몇으로 정해졌나"""
    found = set()
    for m in re.finditer(key, src):
        seg = src[max(0, m.start() - width): m.end() + width]
        found.update(re.findall(r"(?<![\w.])\d{2,3}(?:[_,]?\d{3})*(?![\w.])", seg))
    return sorted(found, key=lambda x: int(x.replace(",", "").replace("_", "")))[:8]


runs = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "runs", "*")))
print("| 항목 | " + " | ".join(runs) + " |")
print("|---|" + "---|" * len(runs))
srcs = {r: src_of(os.path.join(HERE, "runs", r)) for r in runs}
for name, pat in CHECKS:
    print("| %s | %s |" % (name, " | ".join("○" if re.search(pat, srcs[r], re.I) else "—" for r in runs)))
print()
for r in runs:
    s = srcs[r]
    print("%s — 유예 근처 숫자 %s · 지연 요금 근처 %s · 연료 근처 %s · 손상 등급 근처 %s" % (
        r, numbers_near(s, r"grace|GRACE|유예"), numbers_near(s, r"late|LATE|지연|overdue"), numbers_near(s, r"fuel|FUEL|연료"), numbers_near(s, r"minor|MINOR|경미|severe")))
