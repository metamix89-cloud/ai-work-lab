# -*- coding: utf-8 -*-
"""6편 v2 묶음 자가 시험(API 없음): engine.lint_clusters 가 위키에서 대상별 페이지 묶음을 어떻게 만드는지 보여 준다.
사용: python _scratch/wiki/cluster_test.py wiki_full [wiki_ep5c ...]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
for name in sys.argv[1:] or ["wiki_full"]:
    w = E.Wiki(os.path.join(E.HERE, name))
    cl = E.lint_clusters(w)
    chars = sum(len(w.read_page(s) or "") for _, ms in cl for s in ms)
    print("== %s: 묶음 %d개, 페이지 합 %d(중복 포함), 글자 %s" % (name, len(cl), sum(len(ms) for _, ms in cl), format(chars, ",")))
    for key, ms in cl:
        print("  %-12s %d: %s" % (key, len(ms), ", ".join(ms)[:150]))
