# -*- coding: utf-8 -*-
"""6편: 넣기 때 모델이 페이지의 '⚠ 상충' 절에 적어 둔 것만으로 심은 모순이 몇 개 잡히는지(코드로 셈, API 없음).
규칙 위키는 넣을 때 메모 · 초안의 다른 값을 '상충' 에 적게 돼 있다 → 점검(lint)을 따로 돌리기 전에 이미 기록된 모순 수.
사용: python _scratch/wiki/conflict_sections.py wiki_ep5c [wiki_full ...]"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from lint_grade import ITEMS, has, in_scope
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))


def groups_of(wiki):
    gs, b = [], wiki.replace("wiki_", "")
    while b:
        bj = os.path.join(HERE, "results", "build_%s.json" % b)
        if not os.path.exists(bj):
            return gs or None
        d = json.load(open(bj, encoding="utf-8")); gs = d.get("groups", []) + gs; b = (d.get("base") or "").replace("wiki_", "")
    return gs or None


for name in sys.argv[1:] or ["wiki_ep5c"]:
    w = E.Wiki(os.path.join(HERE, name)); groups = groups_of(name)
    sections = []                                   # (slug, 상충 절 글)
    for s in w.slugs():
        t = w.read_page(s) or ""
        m = re.search(r"##\s*⚠[^\n]*\n(.*?)(?=\n## |\Z)", t, re.S)
        if m and re.search(r"^\s*-\s*\S", m.group(1), re.M) and "없음" != m.group(1).strip("- \n"):
            sections.append((s, m.group(1)))
    hits, rows = 0, []
    for it in ITEMS:
        if not in_scope(it, groups):
            continue
        where = [s for s, sec in sections if has(sec, it["topic"] + [s]) and has(sec, it["wrong"])] or \
                [s for s, sec in sections if has(sec, it["wrong"]) and has(s, it["topic"])]
        hits += bool(where); rows.append("%s:%s" % (it["id"], ("있음(" + where[0] + ")") if where else "없음"))
    n = sum(1 for it in ITEMS if in_scope(it, groups))
    print("== %s: 상충 절이 찬 페이지 %d개 · 범위 %d개 중 상충 절에 심은 틀린 값이 적힌 모순 %d개" % (name, len(sections), n, hits))
    print("   " + "  ".join(rows))
