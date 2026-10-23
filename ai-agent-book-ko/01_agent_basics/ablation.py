# -*- coding: utf-8 -*-
"""컨텍스트 빼기 실험 (원서 실험 1-1 방식, 가나다식품 문의로 각색). 조건마다 N번 실제 실행 → results.json
A 전부 있음 / B 도구 정의 없음 / C 도구 결과 없음 / D 이전 대화 기록 없음 (+D0 기록 있음 대조)"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from agent import agent, SYSTEM

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
Q = "주문번호 GND-2417 반품되나요?"
T1, T2 = "주문번호 GND-2417 배송 상태 알려 주세요.", "그럼 그거 반품돼요?"


def correct(a):          # 정답: 반품 가능 + 7일(10/21까지) + 사진
    return ("가능" in a) and ("사진" in a) and ("7일" in a or "21" in a)


def invented(a):         # 확인 없이 기간 · 가능 여부를 단정
    return bool(re.search(r"\d+\s*일\s*(이내|안에|까지)", a)) or bool(re.search(r"반품(이)?\s*가능합니다", a))


def run(cond, k):
    log = []
    sysm = {"role": "system", "content": SYSTEM}
    if cond == "A":
        a, n = agent([sysm, {"role": "user", "content": Q}], log=log.append)
    elif cond == "B":
        a, n = agent([sysm, {"role": "user", "content": Q}], tools=None, log=log.append)
    elif cond == "C":
        a, n = agent([sysm, {"role": "user", "content": Q}], show_results=False, log=log.append)
    elif cond in ("D", "D0"):
        msgs = [sysm, {"role": "user", "content": T1}]
        a1, _ = agent(msgs, log=log.append)
        hist = msgs if cond == "D0" else [sysm]          # D: 앞 대화를 버리고 새 질문만
        a, n = agent(hist + [{"role": "user", "content": T2}], log=log.append)
    calls = [l for l in log]
    return dict(cond=cond, k=k, answer=a, model_calls=n, tool_calls=len(calls), log=calls,
                correct=correct(a), invented=(not correct(a)) and invented(a))


if __name__ == "__main__":
    jobs = [(c, k) for c in ("A", "B", "C", "D0", "D") for k in range(N)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: run(*j), jobs))
    json.dump(res, open("results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in ("A", "B", "C", "D0", "D"):
        rs = [r for r in res if r["cond"] == c]
        print("%-3s 정답 %d/%d · 지어냄 %d · 평균 모델 호출 %.1f · 최대반복 도달 %d" % (
            c, sum(r["correct"] for r in rs), len(rs), sum(r["invented"] for r in rs),
            sum(r["model_calls"] for r in rs) / len(rs), sum("최대 반복" in r["answer"] for r in rs)))
