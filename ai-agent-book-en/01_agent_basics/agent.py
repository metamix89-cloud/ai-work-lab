# -*- coding: utf-8 -*-
"""EN ep01 lab — Yummy Tummy Foods (fictional) customer-support agent. Core loop written by hand, no framework.
Same design as the Korean ep034 lab (book ch.2 'core loop'), data and tools rewritten in English."""
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
MODEL = "gpt-4.1-mini"

# US grocery items for the English series (the first run used Korean-style items — dumplings, sesame oil — see NOTES.md)
ORDERS = {"YT-2417": {"product": "Yummy Tummy Pepperoni Pizza 2-pack", "category": "frozen", "delivered": "2026-10-14", "status": "delivered"},
          "YT-2433": {"product": "Yummy Tummy Cola 12-pack", "category": "pantry", "delivered": "2026-09-30", "status": "delivered"}}
POLICY = {"frozen": "Returnable within 7 days of delivery if unopened. A photo showing the item is still frozen is required.",
          "pantry": "Returnable within 14 days of delivery if unopened."}

SYSTEM = "You are a customer support agent at Yummy Tummy Foods. Today is 2026-10-19. Answer briefly, using only facts confirmed by your tools."

TOOLS = [
    {"type": "function", "function": {
        "name": "get_order", "description": "Look up an order by order ID: product, category, delivery date, status.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string", "description": "e.g. YT-2417"}},
                       "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "get_return_policy", "description": "Look up the return policy for a product category.",
        "parameters": {"type": "object", "properties": {"category": {"type": "string", "description": "frozen or pantry"}},
                       "required": ["category"]}}},
]


def run_tool(name, args):
    if name == "get_order":
        return ORDERS.get(args.get("order_id"), {"error": "order not found"})
    if name == "get_return_policy":
        return POLICY.get(args.get("category"), "no policy for this category")
    return {"error": "unknown tool"}


def agent(messages, tools=TOOLS, show_results=True, max_turns=8, log=print):
    for turn in range(1, max_turns + 1):
        kw = {"tools": tools} if tools else {}
        msg = client.chat.completions.create(model=MODEL, messages=messages, **kw).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content, turn
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            result = run_tool(tc.function.name, args)
            log("⚡ %s(%s) → %s" % (tc.function.name, args, json.dumps(result)))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result) if show_results else ""})
    return "(stopped: max turns %d)" % max_turns, max_turns


if __name__ == "__main__":
    q = "Can I return order YT-2417?"
    ans, n = agent([{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}])
    print("Answer:", ans, "| model calls: %d" % n)
