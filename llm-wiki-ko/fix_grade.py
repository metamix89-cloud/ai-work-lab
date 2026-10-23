# -*- coding: utf-8 -*-
"""9편 재발 채점기(코드). 위키 페이지 본문(⚠ 상충 절 밖)에 memos_ep9.json 의 topic + wrong 이 같은 페이지에 있으면 '재발'.
사용: from fix_grade import recurred, body_without_conflict / python fix_grade.py (자가 시험)"""
import glob, json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
MEMOS = json.load(open(os.path.join(HERE, "memos_ep9.json"), encoding="utf-8"))["memos"]


def norm(t):
    t = (t or "").replace(",", "")
    t = re.sub(r"\s*[·,]\s*", "·", t)
    return re.sub(r"\s+", " ", t)


def body_without_conflict(text):
    """'## ⚠ …' 절(다음 '## ' 앞까지)을 뺀 본문."""
    return re.sub(r"##\s*⚠[^\n]*\n.*?(?=\n## |\Z)", "", text or "", flags=re.S)


def recurred(memo, pages):
    """pages: {slug: text}. 재발한 페이지 목록."""
    out = []
    for s, t in pages.items():
        b = norm(body_without_conflict(t))
        if any(norm(k) in b for k in memo["topic"]) and any(norm(k) in b for k in memo["wrong"]):
            out.append(s)
    return out


def wiki_pages(wdir):
    return {os.path.splitext(os.path.basename(p))[0]: open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(wdir, "pages", "*.md"))}


if __name__ == "__main__":
    m = {x["id"]: x for x in MEMOS}
    p1 = {"거래처-가나마트": "# 가나마트\n## 현재 값\n- 담당: 한 주임 (10/1~)\n- 결제: 익월 25일\n\n## ⚠ 상충 · 확인 필요\n- 영업 메모(10/30): 담당은 이 대리, 결제 익월 말"}
    p2 = {"거래처-가나마트": "# 가나마트\n## 현재 값\n- 담당은 이 대리\n- 결제: 익월 말 입금 (영업 메모 10/30)\n\n## ⚠ 상충 · 확인 필요\n- 없음"}
    p3 = {"상품-김-선물세트": "# 김 선물세트\n## 현재 값\n- 상태: 보류 (9/1 경영회의, 11월 재검토)\n## 이력\n- 단종됨 → 보류 (2026-10-26 교정)"}
    checks = [("상충 절에만 있으면 재발 아님", recurred(m["E1"], p1) == [] and recurred(m["E5"], p1) == []),
              ("본문에 있으면 재발", recurred(m["E1"], p2) == ["거래처-가나마트"] and recurred(m["E5"], p2) == ["거래처-가나마트"]),
              ("이력 줄의 '단종됨 →' 도 본문이라 재발로 셈(엄격)", recurred(m["E9"], p3) == ["상품-김-선물세트"]),
              ("주제 없는 페이지는 무시", recurred(m["E10"], p2) == [])]
    bad = 0
    for name, ok in checks:
        print(("OK  " if ok else "!!  ") + name); bad += not ok
    print("자가 시험:", "통과" if not bad else "실패 %d" % bad)
    sys.exit(1 if bad else 0)
