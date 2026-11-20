# -*- coding: utf-8 -*-
"""ep097 영상용 그림 — 우리가 그린 그림(실제 서비스 화면 아님). 글자와 숫자는 실측 파일에서 읽는다.
  mockup_ok.png   회의실 예약 목업(ep072 랩의 그림을 그대로 복사)
  diff_date.png   채팅 한 줄 1번째 실행(runs/M1_1)의 main.py 에서 실제로 더해진 줄 + 같은 요청의 고치기 전 · 뒤 응답(behavior.json) + AI 보고의 그 문장(build.json)
영상 카드 1450×560 의 2배(2900×1120).
사용: python _scratch/s2s/20_feature_regression/make_images.py"""
import json
import os
import shutil
import sys

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from ep093_images import AMBER, BG, CARD, EMERALD, INDIGO, LINE, MUTE, RED, TEXT, font   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OUT = os.path.join(ROOT, "import", "ep097_feature_regression", "images")
RUN = "M1_1"
W, H = 2900, 1120
CASE = "날짜 형식 다름(2026/11/03)"


def main():
    os.makedirs(OUT, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "import", "ep072_s2s_meeting_room", "images", "mockup_ok.png"), os.path.join(OUT, "mockup_ok.png"))
    src = open(os.path.join(HERE, "runs", RUN, "main.py"), encoding="utf-8").read().splitlines()
    import difflib
    old = open(os.path.join(HERE, "base", "main.py"), encoding="utf-8").read().splitlines()
    added = set()   # 더해진 줄의 번호(0부터) — 같은 글자의 줄이 다른 곳에 있어도 헷갈리지 않게 diff 로 센다
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, old, src, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            added.update(range(j1, j2))
    lo = next(i for i, l in enumerate(src) if "최대 2시간까지" in l) - 1
    hi = next(i for i, l in enumerate(src) if "날짜 형식이 올바르지" in l)
    beh = json.load(open(os.path.join(HERE, "behavior.json"), encoding="utf-8"))
    before, after = beh["base"][CASE], beh[RUN][CASE]
    report = json.load(open(os.path.join(HERE, "runs", RUN, "build.json"), encoding="utf-8"))["result"]
    quote = next(l.strip("- ").strip() for l in report.splitlines() if "예전에는" in l)

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    title, head, body, small = font("Pretendard-Bold.otf", 56), font("Pretendard-Bold.otf", 46), font("Pretendard-Regular.otf", 42), font("Pretendard-Regular.otf", 40)
    mono = font("consola.ttf", 40)
    # 왼쪽: 바뀐 줄 목록
    d.rounded_rectangle((30, 30, 1790, 760), 28, fill=CARD, outline=LINE, width=3)
    d.text((80, 62), "바뀐 줄 목록 — main.py (예약 만들기)", font=title, fill=INDIGO)
    y = 150
    for i in range(lo, hi + 1):
        line = src[i]
        new = i in added
        indent = len(line) - len(line.lstrip())
        date_line = new and ("fromisoformat" in line or "ValueError" in line or "날짜 형식" in line or line.strip() == "try:")
        if date_line:
            d.rounded_rectangle((70, y - 6, 1750, y + 50), 8, fill="#1F3A2E")
        d.text((90, y), "+" if new else " ", font=mono, fill=EMERALD if new else MUTE)
        txt = line.strip()
        while txt and d.textlength(txt, font=body) > 1600 - indent * 12:
            txt = txt[:-2] + "…"
        d.text((150 + indent * 12, y - 2), txt, font=body, fill="#D8FBE8" if date_line else (TEXT if new else MUTE))
        y += 56
    d.text((90, 692), "+ 는 AI 가 더한 줄 · 초록 4줄은 반복과 상관없이 모든 예약에 걸린다", font=small, fill=MUTE)
    # 오른쪽: 같은 요청, 다른 답
    d.rounded_rectangle((1820, 30, 2870, 760), 28, fill=CARD, outline=LINE, width=3)
    d.text((1870, 62), "같은 요청, 다른 답", font=title, fill=INDIGO)
    d.text((1870, 170), "한 번짜리 예약", font=head, fill=TEXT)
    d.text((1870, 240), "날짜를 2026/11/03 으로 보냄", font=body, fill=MUTE)
    for k, (label, v, color, word) in enumerate((("고치기 전", before, EMERALD, "예약됨"), ("고친 뒤", after, RED, "거절"))):
        top = 340 + k * 200
        d.rounded_rectangle((1870, top, 2820, top + 170), 18, fill="#20242E", outline=LINE, width=2)
        d.text((1910, top + 28), label, font=body, fill=MUTE)
        d.text((1910, top + 86), "%d  %s" % (v["status"], word), font=head, fill=color)
    # 아래: AI 의 보고
    d.rounded_rectangle((30, 790, 2870, 1090), 28, fill=CARD, outline=LINE, width=3)
    d.text((80, 822), "AI 의 보고에는 적혀 있었다", font=title, fill=AMBER)
    d.text((80, 930), "“" + quote + "”", font=head, fill=TEXT)
    d.text((80, 1010), "기존 테스트 9개는 이 요청을 보내 보지 않는다 — 그래서 9개 다 통과", font=small, fill=MUTE)
    out = os.path.join(OUT, "diff_date.png")
    im.save(out)
    print("썼음:", out, im.size, "|", before["status"], "→", after["status"], "|", quote)


if __name__ == "__main__":
    main()
