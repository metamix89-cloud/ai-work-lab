# -*- coding: utf-8 -*-
"""ep034 실습 — 가나다식품 고객 문의 에이전트. 핵심 루프를 프레임워크 없이 직접 짠다.
원서 2장 '에이전트 핵심 루프' 구조를 따르되 데이터 · 도구는 가나다식품(가상)으로 바꿈."""
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"

# ── 가상 데이터 ──
ORDERS = {"GND-2417": {"상품": "가나다 냉동만두 1kg", "분류": "냉동식품", "받은 날": "2026-10-14", "상태": "배송 완료"},
          "GND-2433": {"상품": "가나다 참기름 350ml", "분류": "상온식품", "받은 날": "2026-09-30", "상태": "배송 완료"}}
POLICY = {"냉동식품": "개봉 전, 받은 날부터 7일 이내 반품 가능. 냉동 상태 확인 사진 필요.",
          "상온식품": "개봉 전, 받은 날부터 14일 이내 반품 가능."}

SYSTEM = "당신은 가나다식품 고객센터 상담원입니다. 오늘은 2026-10-19입니다. 도구로 확인한 사실로만 짧게 답하세요."

# ── 도구 정의: 이름 · 설명 · 파라미터 ──
TOOLS = [
    {"type": "function", "function": {
        "name": "get_order", "description": "주문번호로 주문 상품 · 분류 · 받은 날 · 상태를 조회합니다.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string", "description": "예: GND-2417"}},
                       "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "get_return_policy", "description": "상품 분류별 반품 규정을 조회합니다.",
        "parameters": {"type": "object", "properties": {"category": {"type": "string", "description": "냉동식품 · 상온식품"}},
                       "required": ["category"]}}},
]


def run_tool(name, args):
    if name == "get_order":
        return ORDERS.get(args.get("order_id"), {"오류": "없는 주문번호"})
    if name == "get_return_policy":
        return POLICY.get(args.get("category"), "해당 분류 규정 없음")
    return {"오류": "없는 도구"}


# ── 핵심 루프: 생각 → 행동 → 관찰 ──
def agent(messages, tools=TOOLS, show_results=True, max_turns=8, log=print):
    for turn in range(1, max_turns + 1):
        kw = {"tools": tools} if tools else {}
        msg = client.chat.completions.create(model=MODEL, messages=messages, **kw).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:                       # 도구를 안 부르면 = 최종 답
            return msg.content, turn
        for tc in msg.tool_calls:                    # 행동: 도구 실행
            args = json.loads(tc.function.arguments)
            result = run_tool(tc.function.name, args)
            log("⚡ %s(%s) → %s" % (tc.function.name, args, json.dumps(result, ensure_ascii=False)))
            content = json.dumps(result, ensure_ascii=False) if show_results else ""
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})   # 관찰
    return "(최대 반복 %d회에 닿아 멈춤)" % max_turns, max_turns


if __name__ == "__main__":
    q = "주문번호 GND-2417 반품되나요?"
    ans, n = agent([{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}])
    print("답:", ans, "| 모델 호출 %d회" % n)
