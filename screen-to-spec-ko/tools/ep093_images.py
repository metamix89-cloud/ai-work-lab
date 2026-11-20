# -*- coding: utf-8 -*-
"""ep093 영상용 그림 — 우리가 그린 가상 화면(실제 서비스 화면 아님).
  tests_pass.png     pytest 결과 창 흉내 — 테스트 9개 초록 통과 (PART 1 질문 장면)
  codified_test.png  AI 가 쓴 테스트 중 '실수를 정상으로 굳힌' 문장 — ai_tests/<이름>/test_app.py 의 실제 줄 (PART 5)
영상 카드 1450×560 의 2배(2900×1120)로 그린다.
사용: python _scratch/s2s/tools/ep093_images.py pass
      python _scratch/s2s/tools/ep093_images.py code      (보여 줄 함수는 CODIFIED 목록)"""
import ast
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
LAB = os.path.join(os.path.dirname(HERE), "02_s2s_meeting_room")
OUT_DIR = os.path.join(ROOT, "import", "ep093_ai_written_tests", "images")
FONT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")

BG, CARD, LINE = "#111318", "#1B1E26", "#2A2E39"
TEXT, MUTE, INDIGO, EMERALD, RED, AMBER = "#E8EAF0", "#8A90A0", "#818CF8", "#10B981", "#F87171", "#FBBF24"
W, H = 2900, 1120


def font(name, size):
    for d in (FONT_DIR, r"C:\Windows\Fonts"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    sys.exit("글꼴 없음: " + name)


def check(d, x, y, s=22, color=EMERALD, w=7):
    d.line((x, y + s * 0.55, x + s * 0.4, y + s), fill=color, width=w)
    d.line((x + s * 0.4, y + s, x + s * 1.1, y + s * 0.1), fill=color, width=w)


def draw_pass():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    mono = font("consola.ttf", 46)
    mono_b = font("consolab.ttf", 46)
    big = font("Pretendard-Bold.otf", 150)
    body = font("Pretendard-Regular.otf", 46)
    title = font("Pretendard-Bold.otf", 56)
    # 왼쪽: 터미널
    d.rounded_rectangle((30, 30, 1990, 1090), 28, fill=CARD, outline=LINE, width=3)
    for i, c in enumerate((RED, AMBER, EMERALD)):
        d.ellipse((80 + i * 46, 70, 108 + i * 46, 98), fill=c)
    d.text((240, 62), "터미널 — 회의실 예약 앱", font=body, fill=MUTE)
    d.text((80, 150), "> python -m pytest tests -q", font=mono_b, fill=TEXT)
    names = ["T1 화면이 열린다", "T2 칸이 54개", "T3 예약이 칸에 보인다", "T4 겹치면 거절", "T5 붙여 예약 허용",
             "T6 30분 단위 · 시간대", "T7 최대 2시간", "T8 본인만 취소", "T9 내 칸에만 취소 버튼"]
    y = 240
    for n in names:
        check(d, 86, y + 8)
        tag, label = n.split(" ", 1)
        d.text((150, y), tag, font=mono, fill=TEXT)          # 영문 · 숫자는 Consolas
        d.text((240, y - 2), label, font=body, fill=TEXT)    # 한글은 Pretendard(Consolas 에 한글 글꼴이 없다)
        d.text((1500, y), "PASSED", font=mono_b, fill=EMERALD)
        y += 76
    d.rectangle((80, y + 14, 1940, y + 18), fill=LINE)
    d.text((80, y + 40), "========== 9 passed in 12.4s ==========", font=mono_b, fill=EMERALD)
    # 오른쪽: 큰 숫자
    d.rounded_rectangle((2020, 30, 2870, 1090), 28, fill=CARD, outline=LINE, width=3)
    d.text((2445, 330), "9 / 9", font=big, fill=EMERALD, anchor="mm")
    d.text((2445, 500), "테스트 통과", font=title, fill=TEXT, anchor="mm")
    d.text((2445, 760), "이 테스트는", font=title, fill=MUTE, anchor="mm")
    d.text((2445, 840), "누가 썼나요?", font=title, fill=AMBER, anchor="mm")
    out = os.path.join(OUT_DIR, "tests_pass.png")
    os.makedirs(OUT_DIR, exist_ok=True)
    im.save(out)
    print("썼음:", out, im.size)


def snippet(run, func):
    for f in sorted(os.listdir(os.path.join(LAB, "ai_tests", run))):
        if f.startswith("test_") and f.endswith(".py"):
            src = open(os.path.join(LAB, "ai_tests", run, f), encoding="utf-8").read()
            node = next((n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == func), None)
            if node:
                lines = src.splitlines()
                start = min([x.lineno for x in node.decorator_list] + [node.lineno])
                return start, lines[start - 1:node.end_lineno]
    sys.exit("함수 없음: %s/%s" % (run, func))


# 영상에 보여 줄 '실수를 정상으로 굳힌' 테스트 두 개 — (실행 이름, 함수, 강조 줄 오프셋, 머리말, 정답 앱 결과, 함정 앱 결과)
CODIFIED = [
    ("code_1", "test_create_full_day_boundaries_allowed", (1, 2), "코드만 받은 AI — 09:00~18:00 종일 예약이 '된다' 고 적었다",
     "정답 앱: 400 거절 → 테스트 실패", "함정 앱: 201 통과 → 테스트 통과"),
    ("both_1", "open_page", (3,), "PRD + 코드 받은 AI — 날짜 없이 열면 코드의 고정 날짜가 나온다고 봤다",
     "정답 앱: 오늘 날짜 → 화면 테스트 5개 실패", "함정 앱: 2026-11-03 고정 → 그 부분은 통과"),
]


def draw_code():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    mono = font("consola.ttf", 40)
    body = font("Pretendard-Regular.otf", 40)
    head = font("Pretendard-Bold.otf", 44)
    title = font("Pretendard-Bold.otf", 56)
    d.rounded_rectangle((30, 30, 2870, 1090), 28, fill=CARD, outline=LINE, width=3)
    d.text((80, 58), "AI 가 쓴 테스트 — 코드의 실수가 '정상' 이 됐다", font=title, fill=INDIGO)
    y = 160
    for run, func, hl, caption, ref, trap in CODIFIED:
        start, block = snippet(run, func)
        d.text((80, y), caption, font=head, fill=TEXT)
        y += 70
        for k, line in enumerate(block):
            txt = line.replace("\t", "    ")
            while txt and d.textlength(txt, font=mono) > 1900:
                txt = txt[:-1]
            is_hl = k in hl
            if is_hl:
                d.rounded_rectangle((70, y - 4, 2040, y + 48), 8, fill="#3B2A2A")
                d.rectangle((70, y - 4, 80, y + 48), fill=RED)
            d.text((100, y), "%3d" % (start + k), font=mono, fill=MUTE)
            d.text((200, y), txt, font=mono, fill="#FFD7D7" if is_hl else TEXT)
            y += 52
        # 오른쪽 판정
        top = y - 52 * len(block) - 10
        d.rounded_rectangle((2090, top, 2820, top + 60 + 52 * max(2, len(block)) - 20), 14, fill="#20242E", outline=LINE, width=2)
        d.text((2120, top + 16), ref, font=body, fill=RED)
        d.text((2120, top + 76), trap, font=body, fill=EMERALD)
        y += 60
    out = os.path.join(OUT_DIR, "codified_test.png")
    im.save(out)
    print("썼음:", out, im.size)


if __name__ == "__main__":
    if sys.argv[1] == "pass":
        draw_pass()
    else:
        draw_code()
