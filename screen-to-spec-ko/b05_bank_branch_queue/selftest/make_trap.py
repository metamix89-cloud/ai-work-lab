# -*- coding: utf-8 -*-
"""정답 앱에서 흔한 실수만 넣어 함정 앱을 만든다. 사용: python _scratch/s2s/b05_bank_branch_queue/selftest/make_trap.py
실수: 대기 화면 응답에 행 전체(이름 · 전화번호 · 계좌)를 싣고 화면(JS)에서 가림 · 10분 경계 미만 · 3분 안 기다림 · 상세 권한 없음."""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ref, trap = os.path.join(HERE, "ref_app"), os.path.join(HERE, "trap_app")
shutil.rmtree(trap, ignore_errors=True)
shutil.copytree(ref, trap, ignore=shutil.ignore_patterns("*.db", "__pycache__", "seed", "seed_backup"))
p = os.path.join(trap, "main.py")
s = open(p, encoding="utf-8").read()
for old, new in [
    ('{"number": t["number"], "masked_name": mask(t["name"]), "counter_id": t["counter_id"]}', '{**dict(t), "masked_name": mask(t["name"])}'),
    ('{"number": t["number"], "masked_name": mask(t["name"])} for t', '{**dict(t), "masked_name": mask(t["name"])} for t'),
    ("<= WINDOW_MIN", "< WINDOW_MIN"),
    ('if minutes(now, cur["called_at"]) < HOLD_MIN:', "if False:"),
    ('        own_ticket(u, t)\n        digits', "        digits"),
]:
    assert old in s, old
    s = s.replace(old, new)
open(p, "w", encoding="utf-8").write(s)
print("trap_app 만듦")
