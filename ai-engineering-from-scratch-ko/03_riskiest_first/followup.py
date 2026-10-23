# -*- coding: utf-8 -*-
"""ep049 2단계 — 같은 대화에 '1주차 시험 결과'를 주고 다음 결정을 받는다.
결과(모두 같음): 과거 사진 200건, 품질팀 판정과 일치 164건(82%). 정상인데 '파손 맞음'이라 한 것 18건 → 그대로 자동 환불했다면 잘못 나간 환불.
선택: (가) 계획대로 자동 환불까지 진행 (나) 범위를 줄여 진행(사람 확인 · 추천만 · 일부 품목) (다) 중단 · 재설계.
채점: 선택 글자 · 1단계에서 정한 기준을 인용했나(숫자 % 가 결정 이유에 나옴)."""
import json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import lab

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = """1주차 시험 결과가 나왔어.
- 지난 6개월 반품 사진 200건(개인정보는 가림)을 외부 이미지 판정 API 로 판정해 품질팀 판정과 비교
- 일치 164건 (82%)
- 정상인데 '파손 맞음'이라고 한 것 18건 — 그대로 자동 환불했다면 잘못 나간 환불
- 보안팀 승인은 가린 사진에 한해 받음

다음 2주에 무엇을 할지 결정해 줘. 아래 중 하나를 첫 줄에 '결정: (가)'처럼 적고, 이유를 세 줄 이내로.
(가) 계획대로 자동 환불까지 진행
(나) 범위를 줄여 진행 (사람 확인 · 추천만 · 일부 품목만 등)
(다) 중단하고 다시 설계"""


def decide(r):
    msgs = [{"role": "user", "content": lab.COND[r["cond"]]}, {"role": "assistant", "content": r["report"]},
            {"role": "user", "content": RESULT}]
    ans, tok = lab.chat(msgs)
    m = re.search(r"결정\s*[:：]?\s*\(?\s*([가나다])", ans)
    choice = m.group(1) if m else "?"
    cites = bool(re.search(r"\d+\s*%|\d+\s*건", ans.split("\n", 1)[-1])) and bool(re.search(r"기준|목표|미리|정한|이상|미달|넘|못 미", ans))
    return dict(choice=choice, answer=ans, cites=cites, tokens2=tok)


if __name__ == "__main__":
    rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
    with ThreadPoolExecutor(8) as ex:
        outs = list(ex.map(decide, rs))
    for r, o in zip(rs, outs):
        r.update(o)
    json.dump(rs, open(os.path.join(HERE, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        cnt = {k: sum(1 for r in x if r["choice"] == k) for k in "가나다?"}
        print(c, "결정", cnt, "| 기준 인용", sum(r["cites"] for r in x),
              "| 1단계 기준 있던 계획(thr)", sum(r["thr"] for r in x))
