# -*- coding: utf-8 -*-
"""6편 lint 채점기. engine.lint 가 낸 JSON({"conflicts":[..],"stale":[..],"orphans":[..],"missing":[..]})을 lint_items.json(심은 모순)과 맞춰 본다.
- 찾음: conflicts · stale 항목 하나(글로 편 것)에 topic 낱말과 심은 wrong 값이 같이 있음 (right 값만 있는 항목은 그 모순을 찾은 게 아니다)
- 판단 맞음: 그 항목의 likely_right 에 right 값이 있고, wrong 값이 없거나 '300,000 → 500,000' 처럼 right 가 뒤에 옴 (값이 없으면 basis 로; stale 은 what 으로)
- 범위: 위키에 든 묶음(groups)에 두 원본이 다 있는 모순만 센다 (wiki_ep5c 에는 sales 가 없어 C11 · C14 제외)
- 위키 안에 두 값이 다 있는지(both_in_wiki)는 코드가 전문에서 본다 — 한쪽 값만 있으면 lint 가 찾을 수 없는 게 당연
- 고아: 코드가 센 고아(목차에 없는 페이지)와 lint 의 orphans 를 집합으로 비교 (맞춤 · 빠짐 · 오탐)
- 오탐 후보: 심은 모순과 안 맞는 conflicts 항목 수 (사람이 훑어본다 — 진짜 상충일 수도 있다)
사용: from lint_grade import grade_lint / python lint_grade.py (자가 시험)"""
import glob, json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = json.load(open(os.path.join(HERE, "lint_items.json"), encoding="utf-8"))["items"]


def norm(t):
    t = (t or "").replace(",", "")
    t = re.sub(r"\s*[·,]\s*", "·", t)        # '화 · 목' · '화, 목' → '화·목'
    t = re.sub(r"\s+", " ", t)
    return t


def has(text, kws):
    n = norm(text)
    return any(norm(k) in n for k in kws)


def pos(text, kws):
    """글에서 값 후보 중 가장 먼저 나오는 자리(없으면 -1)."""
    n = norm(text); ps = [n.find(norm(k)) for k in kws if norm(k) in n]
    return min(ps) if ps else -1


def picks_right(text, item):
    """판정 글(likely_right)이 맞는 값을 골랐나: 맞는 값이 있고, 틀린 값이 없거나 '틀린 값 → 맞는 값' 처럼 맞는 값이 뒤에 온다."""
    pr, pw = pos(text, item["right"]), pos(text, item["wrong"])
    return pr >= 0 and (pw < 0 or pr > pw)


def entry_text(e):
    return json.dumps(e, ensure_ascii=False) if not isinstance(e, str) else e


def in_scope(item, groups):
    return groups is None or all(g in groups for g in item["groups"])


def code_orphans(wdir):
    idx = open(os.path.join(wdir, "index.md"), encoding="utf-8").read()
    slugs = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(wdir, "pages", "*.md"))]
    return sorted(s for s in slugs if s not in idx and s.replace("-", "/", 1) not in idx)


def grade_lint(result, wiki_text, groups=None, wdir=None):
    """result: engine.lint 의 result(dict). wiki_text: 위키 전문. groups: 위키에 든 raw 묶음 목록(None 이면 전부)."""
    conflicts = result.get("conflicts", []) or []
    stale = result.get("stale", []) or []
    entries = [("conflict", e) for e in conflicts] + [("stale", e) for e in stale]
    per, matched_idx = [], set()
    for it in ITEMS:
        if not in_scope(it, groups):
            continue
        both = has(wiki_text, it["wrong"]) and has(wiki_text, it["right"])
        found, judged = False, None
        for k, (kind, e) in enumerate(entries):
            t = entry_text(e)
            if has(t, it["topic"]) and has(t, it["wrong"]):      # 심은 '틀린 값' 을 입에 올려야 찾은 것 (right 만 있는 항목은 다른 얘기 — 2026-10-23 C1 오탐으로 고침)
                found = True; matched_idx.add(k)
                if kind == "conflict" and isinstance(e, dict):
                    lr = entry_text(e.get("likely_right", ""))
                    if pos(lr, it["right"]) < 0 and pos(lr, it["wrong"]) < 0:      # likely_right 에 값이 없으면 basis 로
                        lr = entry_text(e.get("basis", ""))
                    judged = picks_right(lr, it)
                else:
                    judged = picks_right(entry_text(e.get("what", "") if isinstance(e, dict) else e), it)
                break
        per.append(dict(id=it["id"], both_in_wiki=both, found=found, judged_right=judged))
    unmatched = [entry_text(e)[:160] for k, (kind, e) in enumerate(entries) if k not in matched_idx and kind == "conflict"]
    out = dict(items=per, n=len(per), both=sum(p["both_in_wiki"] for p in per), found=sum(p["found"] for p in per),
               found_of_both=sum(p["found"] for p in per if p["both_in_wiki"]), judged=sum(1 for p in per if p["judged_right"]),
               reported=len(conflicts), unmatched=unmatched)
    if wdir:
        co = set(code_orphans(wdir)); lo = {re.sub(r"\.md$", "", str(s)).replace("/", "-", 1) for s in (result.get("orphans") or [])}
        out["orphans"] = dict(code=len(co), lint=len(lo), hit=len(co & lo), miss=len(co - lo), false=len(lo - co))
    return out


if __name__ == "__main__":
    wiki_text = "참기름 소비자가 12% 인상. 영업 메모: 10% 인상. 바사푸드 배송 화 · 금. 메모: 화 · 목. 홍삼 젤리 500박스. 다나유통 할인 2%. 견적 2.5%"
    fake = {"conflicts": [
        {"topic": "참기름 인상률", "pages": ["상품/참기름", "거래처/가나마트"], "values": ["12%", "10%"], "likely_right": "12%", "basis": "회의록 8/4 가 메모보다 1차 자료"},
        {"topic": "바사푸드 배송 요일", "pages": ["거래처/바사푸드"], "values": ["화, 금", "화, 목"], "likely_right": "화, 목", "basis": "최신 메모"},
        {"topic": "다나유통 선결제 할인", "pages": ["거래처/다나유통"], "values": ["2%", "2.5%"], "likely_right": "2%(계약 조건)", "basis": "계약 > 견적"},
        {"topic": "두부 300g 재고", "pages": ["상품/두부"], "values": ["120", "130"], "likely_right": "130", "basis": "최신"},
        {"topic": "참기름 인상 단계", "pages": ["상품/참기름"], "values": ["12% (9/1)", "소비자가만"], "likely_right": "둘 다 맞음", "basis": "같은 결정"},
        {"topic": "법인카드 사전 승인", "pages": ["규정/법인카드"], "values": ["300,000", "500,000"], "likely_right": "300,000원 → 500,000원 (10/1 상향)", "basis": "개정 공지"},
        {"topic": "김 선물세트 상태", "pages": ["상품/김-선물세트"], "values": ["단종", "보류"], "likely_right": "보류, 11월 재검토", "basis": "상품 페이지의 '단종' 은 영업 메모 근거"}],
        "stale": [{"page": "규정/14-재택근무", "what": "주 1일은 9/1 개정 전 값, 현재 주 2일"}],
        "orphans": ["상품/두부-300g", "결정/없는-페이지"], "missing": []}
    g = grade_lint(fake, wiki_text, groups=["cs", "customers", "meetings", "policies", "sales"], wdir=None)
    byid = {p["id"]: p for p in g["items"]}
    checks = [("C6 찾음 · 판단 맞음", byid["C6"]["found"] and byid["C6"]["judged_right"] is True),
              ("C13 찾음 · 판단 틀림", byid["C13"]["found"] and byid["C13"]["judged_right"] is False),
              ("C16 찾음 · 판단 맞음(2.5% 가 값 목록에만)", byid["C16"]["found"] and byid["C16"]["judged_right"] is True),
              ("C9 stale 로 찾음 · 판단 맞음", byid["C9"]["found"] and byid["C9"]["judged_right"] is True),
              ("C17 못 찾음(위키엔 500 만)", not byid["C17"]["found"] and not byid["C17"]["both_in_wiki"]),
              ("C1 범위 밖(suppliers 없음)", "C1" not in byid),
              ("미매칭 2(두부 재고 · 참기름 12% 만 — 틀린 값 없는 항목은 찾은 게 아님)", g["unmatched"] == [entry_text(fake["conflicts"][3])[:160], entry_text(fake["conflicts"][4])[:160]]),
              ("C15 '300,000 → 500,000' 은 판단 맞음", byid["C15"]["found"] and byid["C15"]["judged_right"] is True),
              ("C7 basis 에 '단종' 이 있어도 likely_right 가 보류면 맞음", byid["C7"]["found"] and byid["C7"]["judged_right"] is True),
              ("찾음 6 · 판단 5", g["found"] == 6 and g["judged"] == 5)]
    bad = 0
    for name, ok in checks:
        print(("OK  " if ok else "!!  ") + name); bad += not ok
    print("자가 시험:", "통과" if not bad else "실패 %d" % bad)
    sys.exit(1 if bad else 0)
