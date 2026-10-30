# -*- coding: utf-8 -*-
"""목업 HTML 의 상태 3개(ok · empty · error)를 PNG 로 찍는다 (영상 image 장면 · 썸네일 바탕).
사용: python _scratch/s2s/tools/shot_mockup.py <lab_dir> <out_dir> [--w=1450 --h=560]
  → <out_dir>/mockup_ok.png · mockup_empty.png · mockup_error.png"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

lab = os.path.abspath(sys.argv[1])
out = os.path.abspath(sys.argv[2])
w = h = None
states = ("ok", "empty", "error")
for a in sys.argv[3:]:
    if a.startswith("--w="):
        w = int(a[4:])
    if a.startswith("--h="):
        h = int(a[4:])
    if a.startswith("--states="):     # 화면이 셋 넘는 편(ep090: ok,board,manager,error)
        states = tuple(a[9:].split(","))
w, h = w or 1450, h or 560
os.makedirs(out, exist_ok=True)
src = "file:///" + os.path.join(lab, "mockup.html").replace("\\", "/")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
    for st in states:
        pg.goto(src + "?state=" + st)
        pg.wait_for_timeout(400)
        path = os.path.join(out, "mockup_%s.png" % st)
        pg.screenshot(path=path)
        print(path)
    b.close()
