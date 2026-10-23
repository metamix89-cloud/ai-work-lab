# -*- coding: utf-8 -*-
"""rebuild_index 자가 시험: 위키 스냅샷을 임시 폴더에 복사해 목차를 코드로 다시 만들고, 고아 페이지가 0인지 본다(원본 스냅샷은 손대지 않음).
사용: python _scratch/wiki/index_test.py wiki_ep2b"""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "wiki_ep2b")
tmp = tempfile.mkdtemp(prefix="wiki_idx_")
shutil.copytree(src, tmp, dirs_exist_ok=True)
w = E.Wiki(tmp)
w.rebuild_index()
idx = w.index()
orphans = [s for s in w.slugs() if s.replace("-", "/", 1) not in idx]
print(idx)
print("페이지 %d · 고아 %d" % (len(w.slugs()), len(orphans)))
shutil.rmtree(tmp, ignore_errors=True)
