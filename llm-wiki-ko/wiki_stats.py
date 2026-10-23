# -*- coding: utf-8 -*-
"""위키 폴더 상태: 페이지 수 · 글자 수 · 분류별 수 · 목차에 없는 페이지(고아) · 목차 중복 절 · 상충 섹션이 채워진 페이지 수.
사용: python _scratch/wiki/wiki_stats.py wiki_full"""
import glob, os, re, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
wdir = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "wiki_full")
index = open(os.path.join(wdir, "index.md"), encoding="utf-8").read()
pages = sorted(glob.glob(os.path.join(wdir, "pages", "*.md")))
slugs = [os.path.splitext(os.path.basename(p))[0] for p in pages]
texts = {s: open(p, encoding="utf-8").read() for s, p in zip(slugs, pages)}
cat = Counter(s.split("-")[0] for s in slugs)
orphans = [s for s in slugs if s not in index and s.replace("-", "/", 1) not in index]
secs = Counter(re.findall(r"^## (.+)$", index, re.M))
dup = [k for k, v in secs.items() if v > 1]
conflict = [s for s, t in texts.items() if re.search(r"상충[^\n]*\n(?:(?!\n## ).)*\S", t.split("## ⚠")[-1] if "## ⚠" in t else "", re.S) and "## ⚠" in t and len(t.split("## ⚠")[-1].strip().splitlines()) > 1]
print("페이지 %d · 글자 %s · 분류 %s" % (len(slugs), format(sum(len(t) for t in texts.values()), ","), dict(cat)))
print("목차에 없는 페이지(고아) %d개: %s" % (len(orphans), ", ".join(orphans)))
print("목차 중복 절: %s" % (dup or "없음"))
print("상충 섹션이 채워진 페이지 %d개" % len(conflict))
