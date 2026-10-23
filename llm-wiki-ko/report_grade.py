# -*- coding: utf-8 -*-
"""8편 보고서 채점기(코드). 보고서 글을 report_items.json 과 맞춰 본다.
- 요소 있음: topic 낱말과 action 낱말이 같은 줄(문장)에 있음. 근거 있음: 그 줄 또는 보고서 전체에 ground 값이 있음.
- 지어낸 숫자: 보고서의 숫자(쉼표 제거, 2자리 이상 또는 % · 소수)가 원본 57개 파일 어디에도 없으면 '지어냄'. 날짜(2026-…, 10/26, 11월) · 연도 · 퍼센트 뒤 '개월' 같은 것은 뺀다.
- 심은 틀린 값 사용: planted_wrong 의 (주제, 값)이 같은 줄에 있으면 센다(홍삼 300박스 등).
사용: from report_grade import grade_report / python report_grade.py (자가 시험)"""
import glob, json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "report_items.json"), encoding="utf-8"))
ITEMS, PLANTED = CFG["items"], CFG["planted_wrong"]


def norm(t):
    t = (t or "").replace(",", "")
    t = re.sub(r"\s*[·,]\s*", "·", t)
    return re.sub(r"\s+", " ", t)


def has(text, kws):
    n = norm(text)
    return any(norm(k) in n for k in kws)


def sentences(text):
    return [s for s in re.split(r"[\n。]|(?<=[다요음임])\.\s", text or "") if s.strip()]


def numbers(text):
    """채점할 숫자: 날짜 · 연도 · 조항 번호를 뺀, 두 자리 이상 정수 · 소수 · 퍼센트."""
    t = (text or "").replace(",", "")
    t = re.sub(r"20\d\d[-./년]\s?\d{1,2}([-./월]\s?\d{1,2}일?)?", " ", t)      # 2026-10-26 · 2026년 10월
    t = re.sub(r"(?<!\d)\d{1,2}\s?/\s?\d{1,2}(?!\d)", " ", t)                  # 10/26
    t = re.sub(r"(?<!\d)\d{1,2}\s?월(\s?\d{1,2}\s?일)?", " ", t)                # 11월 20일
    t = re.sub(r"(?<!\d)\d{1,2}\s?(일|조|편|주차|개월|차)(?!\w)", " ", t)         # 55일 · 23조 · 3개월 은 숫자 사실이 아니라 단위 — 따로 본다
    out = []
    for m in re.finditer(r"\d+(?:\.\d+)?%?", t):
        s = m.group(0)
        if s.endswith("%") or "." in s or len(s.replace("%", "")) >= 2:
            out.append(s)
    return out


_SRC = None
def source_text():
    global _SRC
    if _SRC is None:
        fs = glob.glob(os.path.join(HERE, "raw", "**", "*.*"), recursive=True)
        _SRC = norm("\n".join(open(f, encoding="utf-8", errors="replace").read() for f in fs))
    return _SRC


def grade_report(text, src=None):
    src = src if src is not None else source_text()
    sents = sentences(text)
    per = []
    for it in ITEMS:
        hit = [s for s in sents if has(s, it["topic"]) and has(s, it["action"])]
        grounded = bool(hit) and (any(has(s, it["ground"]) for s in hit) or has(text, it["ground"]))
        per.append(dict(id=it["id"], found=bool(hit), grounded=grounded))
    nums = numbers(text)
    made_up = sorted({n for n in nums if n.replace("%", "") not in src and n not in src})
    wrong = [p for p in PLANTED if any(has(s, [p[0]]) and has(s, [p[1]]) for s in sents)]
    return dict(items=per, found=sum(p["found"] for p in per), grounded=sum(p["grounded"] for p in per), numbers=len(nums),
                made_up=made_up, planted_wrong=[p[1] for p in wrong])


if __name__ == "__main__":
    fake = """11월 기획 보고서
1. 밀키트 부대찌개를 주력으로 민다 — 3개월 연속 성장(7월 9.8 → 10월 13.9백만), 리뷰 4.7.
2. 떡볶이 떡 + 소스 묶음 15% 판촉(가나마트, 11/1~).
3. 홍삼 젤리(500박스, 56일분)와 견과 선물세트(330박스)는 11/20 입고를 취소한다.
4. 냉동 떡갈비는 변질(리뷰 3.1 '녹아서 왔다') 해결 전까지 판촉에서 제외.
5. 감바스는 새우 크기 구성을 재검토(리뷰 3.4, -18%).
6. 12월 매출 목표는 777백만 원으로 잡는다. (근거 없음)"""
    g = grade_report(fake)
    checks = [("요소 5개 다 찾음", g["found"] == 5), ("근거 5개", g["grounded"] == 5),
              ("지어낸 숫자 = 777 하나", g["made_up"] == ["777"]), ("심은 틀린 값 없음", g["planted_wrong"] == [])]
    fake2 = "홍삼 젤리는 재고 300박스라 추가 입고를 취소한다. 떡갈비는 11월 판촉에 넣는다. 참기름은 10% 올랐다."
    g2 = grade_report(fake2)
    checks += [("홍삼 300박스 = 심은 틀린 값 1 · 참기름 10% 2", g2["planted_wrong"] == ["300박스", "10%"]),
               ("떡갈비 '넣는다' 는 금지 요소가 아님", not [p for p in g2["items"] if p["id"] == "R4"][0]["found"]),
               ("R3 찾음(홍삼 · 취소)", [p for p in g2["items"] if p["id"] == "R3"][0]["found"]),
               ("날짜 · 단위는 숫자로 안 셈", "26" not in g["made_up"] and "56" not in g["made_up"] and "20" not in g["made_up"])]
    bad = 0
    for name, ok in checks:
        print(("OK  " if ok else "!!  ") + name); bad += not ok
    print("자가 시험:", "통과" if not bad else "실패 %d" % bad, "| 숫자:", numbers(fake), "| 지어냄:", g["made_up"])
    sys.exit(1 if bad else 0)
