# -*- coding: utf-8 -*-
"""ep098 랩 준비 — 01_s2s_dashboard 의 9/9 완성본(runs/C1)에서 사용자가 가진 폴더(main.py · static/ · seed/ · PRD.md)만 base/ 로 복사하고,
완료 기준 테스트를 tests/ 로 가져오고, 원본 파일 지문(sha1)을 hashes.json 에 적는다.
CLAUDE.md · tests/ 는 넣지 않는다(기획안: 폴더엔 PRD.md 가 있음).
사용: python _scratch/s2s/21_undo_ai_changes/setup_lab.py"""
import hashlib
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "01_s2s_dashboard")

base = os.path.join(HERE, "base")
if not os.path.isdir(base):
    os.makedirs(base)
    c1 = os.path.join(SRC, "runs", "C1")
    shutil.copy(os.path.join(c1, "main.py"), base)
    shutil.copy(os.path.join(c1, "PRD.md"), base)
    shutil.copytree(os.path.join(c1, "static"), os.path.join(base, "static"))
    shutil.copytree(os.path.join(c1, "seed"), os.path.join(base, "seed"))
os.makedirs(os.path.join(HERE, "tests"), exist_ok=True)
dst = os.path.join(HERE, "tests", "test_dod.py")
if not os.path.exists(dst):
    shutil.copy(os.path.join(SRC, "tests", "test_dod.py"), dst)
hashes = {}
for root, _, files in os.walk(base):
    for f in sorted(files):
        p = os.path.join(root, f)
        rel = os.path.relpath(p, base).replace(os.sep, "/")
        data = open(p, "rb").read()
        hashes[rel] = {"sha1": hashlib.sha1(data).hexdigest(), "bytes": len(data), "crlf": data.count(b"\r\n")}
        print(rel, hashes[rel])
json.dump(hashes, open(os.path.join(HERE, "hashes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
