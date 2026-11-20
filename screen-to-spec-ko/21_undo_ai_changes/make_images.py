# -*- coding: utf-8 -*-
"""ep098 영상용 그림 — 우리가 그린 그림(실제 서비스 화면 아님). 글자는 실측 파일에서 읽는다.
  mockup_ok.png     현황판 목업(ep071 랩의 그림을 그대로 복사)
  restore_diff.png  새 대화 1번째 실행(runs/U2_1)가 되돌린 결과와 원본(base/)의 다른 줄 — 문서의 R1 줄에서 시각만, 코드의 취소 조건 줄,
                    그리고 AI 보고(build.json)의 첫 문장
영상 카드 1450×560 의 2배(2900×1120).
사용: python _scratch/s2s/21_undo_ai_changes/make_images.py"""
import json
import os
import re
import shutil
import sys

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from ep093_images import AMBER, BG, CARD, EMERALD, INDIGO, LINE, MUTE, RED, TEXT, font   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OUT = os.path.join(ROOT, "import", "ep098_undo_ai_changes", "images")
RUN = "U2_1"
W, H = 2900, 1120


def read(*parts):
    return open(os.path.join(HERE, *parts), encoding="utf-8").read()


def main():
    os.makedirs(OUT, exist_ok=True)
    shutil.copy(os.path.join(ROOT, "import", "ep071_s2s_dashboard", "images", "mockup_ok.png"), os.path.join(OUT, "mockup_ok.png"))
    t_old = re.search(r"어제 (\d\d:\d\d)", read("base", "PRD.md")).group(1)
    t_new = re.search(r"어제 (\d\d:\d\d)", read("runs", RUN, "PRD.md")).group(1)
    c_old = re.search(r"WHERE status \S+ '취소'", read("base", "main.py")).group(0)
    c_new = re.search(r"WHERE status \S+ '취소'", read("runs", RUN, "main.py")).group(0)
    report = json.load(open(os.path.join(HERE, "runs", RUN, "build.json"), encoding="utf-8"))["result"]
    quote = report.strip().splitlines()[0].strip()
    assert t_old != t_new and c_old != c_new and "원본이 없어서" in quote, (t_old, t_new, c_old, c_new, quote)

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    title, head, body, small = font("Pretendard-Bold.otf", 56), font("Pretendard-Bold.otf", 50), font("Pretendard-Regular.otf", 44), font("Pretendard-Regular.otf", 40)
    mono = font("consola.ttf", 46)
    # 왼쪽 위: 문서의 규칙 한 줄
    d.rounded_rectangle((30, 30, 1430, 760), 28, fill=CARD, outline=LINE, width=3)
    d.text((80, 62), "문서의 규칙 한 줄", font=title, fill=INDIGO)
    d.text((80, 150), "오늘 주문 수를 세는 규칙의 끝 문장", font=small, fill=MUTE)
    for k, (label, t, color) in enumerate((("원본", t_old, EMERALD), ("AI 가 되돌린 뒤", t_new, RED))):
        top = 240 + k * 250
        d.rounded_rectangle((80, top, 1380, top + 210), 18, fill="#20242E", outline=LINE, width=2)
        d.text((120, top + 26), label, font=body, fill=MUTE)
        x = 120
        for word, c in (("어제 ", TEXT), (t, color), (" 은 오늘이 아니다", TEXT)):
            d.text((x, top + 104), word, font=head, fill=c)
            x += d.textlength(word, font=head)
    # 오른쪽 위: 코드 한 줄
    d.rounded_rectangle((1460, 30, 2870, 760), 28, fill=CARD, outline=LINE, width=3)
    d.text((1510, 62), "코드의 한 줄", font=title, fill=INDIGO)
    d.text((1510, 150), "취소된 주문을 빼는 조건 — 뜻은 같고 글자가 다르다", font=small, fill=MUTE)
    for k, (label, c, color) in enumerate((("원본", c_old, EMERALD), ("AI 가 되돌린 뒤", c_new, RED))):
        top = 240 + k * 250
        d.rounded_rectangle((1510, top, 2820, top + 210), 18, fill="#20242E", outline=LINE, width=2)
        d.text((1550, top + 26), label, font=body, fill=MUTE)
        op = c.split()[2]
        x = 1550
        # 한글('취소')은 Consolas 에 없어 네모로 나온다 — 그 조각만 Pretendard 로
        for word, col, f in ((c.split(op)[0], TEXT, mono), (op + " ", color, mono), (c.split(op)[1].strip(), TEXT, body)):
            d.text((x, top + (106 if f is body else 110)), word, font=f, fill=col)
            x += d.textlength(word, font=f)
    # 아래: AI 의 보고
    d.rounded_rectangle((30, 790, 2870, 1090), 28, fill=CARD, outline=LINE, width=3)
    d.text((80, 822), "AI 의 보고 첫 문장", font=title, fill=AMBER)
    cut = quote.index("복원한 것입니다.") + len("복원한 것입니다.")
    d.text((80, 925), "“" + quote[:cut] + "”", font=body, fill=TEXT)
    d.text((80, 1012), "완료 기준 9개는 다 통과 — 그런데 원본과 같은 파일은 6개 중 4개", font=small, fill=MUTE)
    out = os.path.join(OUT, "restore_diff.png")
    im.save(out)
    print("썼음:", out, im.size, "|", t_old, "→", t_new, "|", c_old, "→", c_new, "|", quote[:cut])


if __name__ == "__main__":
    main()
