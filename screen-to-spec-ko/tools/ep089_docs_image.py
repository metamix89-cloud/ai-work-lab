# -*- coding: utf-8 -*-
"""ep089 영상용 그림 — 왼쪽 15줄 문서(실제 글자), 오른쪽 150줄 문서(줄 길이 그대로의 축소판 · 묻힌 15줄만 색).
영상 카드 1450×560 의 2배(2900×1120)로 그린다.
사용: python _scratch/s2s/tools/ep089_docs_image.py → import/ep089_claudemd_length/images/docs_compare.png"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DOCS = os.path.join(os.path.dirname(HERE), "11_s2s_order_stock", "claudemd")
OUT = os.path.join(ROOT, "import", "ep089_claudemd_length", "images", "docs_compare.png")
FONT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")

BG, CARD, LINE = "#111318", "#1B1E26", "#2A2E39"
TEXT, MUTE, INDIGO, EMERALD = "#E8EAF0", "#8A90A0", "#818CF8", "#10B981"
W, H = 2900, 1120


def font(name, size):
    for d in (FONT_DIR, r"C:\Windows\Fonts"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    sys.exit("글꼴 없음: " + name)


def fit(draw, text, f, width):
    if draw.textlength(text, font=f) <= width:
        return text
    while text and draw.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text + "…"


s_lines = open(os.path.join(DOCS, "S.md"), encoding="utf-8").read().splitlines()
l_lines = open(os.path.join(DOCS, "L.md"), encoding="utf-8").read().splitlines()
assert len(s_lines) == 15 and len(l_lines) == 150
assert l_lines[67:82] == s_lines   # 묻힌 15줄이 S 와 글자까지 같다

im = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(im)
title = font("Pretendard-Bold.otf", 64)
body = font("Pretendard-Regular.otf", 42)
small = font("Pretendard-Regular.otf", 44)

# 왼쪽: 15줄
d.rounded_rectangle((30, 30, 1990, 1090), 28, fill=CARD, outline=LINE, width=3)
d.text((80, 58), "15줄", font=title, fill=EMERALD)
d.text((270, 76), "핵심만, 전부", font=small, fill=MUTE)
y = 164
for i, line in enumerate(s_lines, 1):
    d.text((80, y), "%2d" % i, font=body, fill=MUTE)
    d.text((160, y), fit(d, line.replace("`", ""), body, 1790), font=body, fill=TEXT)
    y += 60

# 오른쪽: 150줄 축소판
d.rounded_rectangle((2020, 30, 2870, 1090), 28, fill=CARD, outline=LINE, width=3)
d.text((2070, 58), "150줄", font=title, fill=INDIGO)
d.text((2290, 76), "일반 수칙 135줄", font=small, fill=MUTE)
top, step = 166, 6.0
for i, line in enumerate(l_lines):
    yy = top + i * step
    buried = 67 <= i < 82
    w = min(480, 50 + d.textlength(line, font=small) * 0.42)
    d.rectangle((2070, yy, 2070 + w, yy + 3.6), fill=EMERALD if buried else "#555B6B")
mid = top + 67 * step
d.text((2570, mid - 26), "68~82줄", font=small, fill=EMERALD)
d.text((2570, mid + 30), "같은 15줄", font=small, fill=EMERALD)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
im.save(OUT)
print("썼음:", OUT, im.size)
