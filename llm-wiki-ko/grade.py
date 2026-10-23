# -*- coding: utf-8 -*-
"""질문 50개 채점기. questions.json 의 must / any / any2 / not / none 규칙으로 답 문자열을 본다.
- 숫자는 쉼표를 떼고 비교한다(73,400 == 73400). '만 원' 표기는 그대로 둔다(정답에 두 가지 다 적어 둠).
- none 문항: '없음 · 찾을 수 없 · 확인되지 않' 류가 있고 숫자 · 날짜를 단정하지 않으면 정답.
- 근거: gold 의 파일명 조각이 답의 '근거:' 줄(또는 답 전체)에 하나라도 있으면 grounded.
사용: from grade import grade_answer / python grade.py 로 자가 시험(test cases)."""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
NONE = r"없음|없습니다|찾을 수 없|확인되지 않|확인할 수 없|나와 있지 않|기록이 없|자료에 없|위키에 없|알 수 없|모릅니다|0건|없었습니다|없다|없으며|없고|은 없|는 없"


def norm(t):
    """쉼표 제거 · 날짜 표기 통일: 2026-11-01 · 2026년 11월 1일 · 11월 1일 · 11월1일 → 11/1 (2026-10-23 채점기 수정: 날짜를 못 알아봐 Q3 네 문항이 오탐)"""
    t = t.replace(",", "")
    t = re.sub(r"20\d\d[-.년]\s?(\d{1,2})[-.월]\s?(\d{1,2})일?", lambda m: "%d/%d" % (int(m.group(1)), int(m.group(2))), t)
    t = re.sub(r"(?<!\d)(\d{1,2})월\s?(\d{1,2})일", lambda m: "%d/%d" % (int(m.group(1)), int(m.group(2))), t)
    t = re.sub(r"(?<!\d)(\d{1,2})/0(\d)(?!\d)", r"\1/\2", t)
    t = re.sub(r"(?<!\d)0(\d)/(\d{1,2})", r"\1/\2", t)
    t = re.sub(r"(\d)\s+(\d)", r"\1\2", t)
    return t


def has(ans, s):
    return norm(s) in norm(ans)


def grade_answer(q, ans):
    """(정답 여부, 이유)"""
    a = ans or ""
    if q.get("none"):
        if not re.search(NONE, a):
            return False, "없음이라 하지 않음"
        if re.search(r"(?<![0-9])(?!0건)\d{2,}\s*(원|건|박스|%)", a.split("근거")[0]):   # 날짜(23일)는 세지 않는다 (2026-10-23 수정)
            return False, "없다면서 숫자를 단정"
        return True, ""
    for s in q.get("must", []):
        if not has(a, s):
            return False, "필수 값 없음: " + s
    body = norm(a.split("근거")[0])          # '답:' 부분만 본다 — 근거 설명에서 상충 원본을 인용한 것은 오답이 아니다 (2026-10-23 수정)
    for s in q.get("not", []):
        if norm(s) in body:
            # 정답 값이 오답 값보다 먼저 나오면(예: "지금 73,400, 11/1 부터 79,270") 이력 언급으로 보고 정답
            firsts = [body.find(norm(m)) for m in q.get("must", []) if norm(m) in body]
            if firsts and min(firsts) < body.find(norm(s)):
                continue
            return False, "오답 값 포함: " + s
    if q.get("any") and not any(has(a, s) for s in q["any"]):
        return False, "후보 값 없음: " + " / ".join(q["any"])
    if q.get("any2") and not any(has(a, s) for s in q["any2"]):
        return False, "후보2 값 없음: " + " / ".join(q["any2"])
    return True, ""


def grounded(q, ans):
    """근거 줄에 gold 파일 조각이 있나. none 문항은 '없음' 이면 True."""
    if q.get("none"):
        return bool(re.search(NONE, ans or ""))
    if not q.get("gold"):
        return None
    tail = (ans or "").split("근거")[-1]
    return any(g.split("/")[-1] in tail or g in tail for g in q["gold"])


if __name__ == "__main__":
    qs = {q["id"]: q for q in json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))["questions"]}
    cases = [
        ("Q2-01", "답: 오늘 기준 떡볶이 소스 2kg 단가는 73,400원입니다(11/1 부터 79,270원).\n근거: [거래처/가나공급] (출처: suppliers/가나공급_단가표.csv)", True, "정답이 먼저, 오답 값은 이력 언급 → 정답"),
        ("Q2-01", "답: 떡볶이 소스 2kg 단가는 79,270원입니다(이전 73,400원).\n근거: 가나공급_단가표", False, "오답이 먼저"),
        ("Q3-07", "답: 보냉재 원복 결정이 2026-10-27 경영회의에서 이루어졌고, 2026-11-01 출고분부터 적용됩니다.\n근거: 결정/2026-10-27-경영회의", True, "날짜 표기 통일"),
        ("Q3-01", "답: 참기름 소비자 가격은 2026년 9월 1일부터 12% 인상. 이유는 원료 깨 수입가 상승.\n근거: meetings/2026-08-04_경영회의.md", True, "년월일 표기"),
        ("Q4-02", "답: 7일 이내만 반품 승인 가능하여 반품 승인 불가합니다.\n근거: 규정/반품-판정-기준", True, "'승인 가능하여 … 불가' 는 정답"),
        ("Q4-08", "답: 구매팀장이 승인하면 입력할 수 있습니다.\n근거: 규정/생성형AI-사용", True, ""),
        ("Q4-01", "답: 승인하면 안 된다. 부산 1박 한도는 B 등급 70,000원 + 20,000원으로 최대 90,000원까지 정산 가능하다.\n근거: 사규_2026.md", True, "'안 된다' 로 초과를 말함 (2026-10-23 5편 오탐 고침)"),
        ("Q4-01", "답: 승인해도 됩니다. 부산은 90,000원까지인데 95,000원도 실비 정산됩니다.\n근거: 사규_2026.md", False, "90,000 을 말해도 초과 · 거절이 없으면 오답"),
        ("Q2-01", "답: 73400원입니다.\n근거: 가나공급_단가표.csv", True, "쉼표 없는 숫자"),
        ("Q2-03", "답: 10% 인상입니다.\n근거: 구매팀_메모", False, "메모의 틀린 값"),
        ("Q2-03", "답: 8% 인상(73,400 → 79,270원)입니다.\n근거: 가나공급_공문_2026-10-15.md", True, ""),
        ("Q3-03", "답: 아니요, 단종은 보류됐고 11월에 재검토합니다.\n근거: meetings/2026-09-01_경영회의.md", True, ""),
        ("Q3-03", "답: 네, 추석 후 단종됐습니다.\n근거: 영업메모_이대리.md", False, ""),
        ("Q4-02", "답: 냉동은 받은 날 포함 7일 이내만 반품되므로 9일째는 거절합니다(14일 규정은 11/3 시행).\n근거: 사규_2026.md, 반품기준_개정예고_2026-11-03.md", True, ""),
        ("Q4-02", "답: 14일 이내이므로 승인 가능합니다.\n근거: 반품기준_개정예고", False, "시행 전 규정을 적용"),
        ("Q4-10", "답: 자료에 없음\n근거: 없음", True, ""),
        ("Q4-10", "답: 명절 상여금은 기본급의 100% 입니다.\n근거: 사규_2026.md", False, "지어냄"),
        ("Q1-10", "답: 위키에 없음. 알레르기 문의는 감바스 · 견과 세트에서만 있었습니다.\n근거: 없음", True, "없다고 하면서 다른 사실을 덧붙여도 숫자 단정만 없으면 정답"),
        ("Q5-02", "답: 홍삼 젤리(500박스, 55일분)와 견과 선물세트(330박스)입니다.\n근거: 재고표_2026-10-26.md", True, ""),
        ("Q5-02", "답: 홍삼 젤리입니다.\n근거: 재고표", False, "둘 다 있어야 함"),
    ]
    bad = 0
    for qid, ans, want, note in cases:
        ok, why = grade_answer(qs[qid], ans)
        g = grounded(qs[qid], ans)
        flag = "OK " if ok == want else "!! "
        bad += ok != want
        print("%s %s → %s (%s) grounded=%s  %s" % (flag, qid, ok, why, g, note))
    print("자가 시험:", "통과" if not bad else "실패 %d" % bad)
    sys.exit(1 if bad else 0)
