# -*- coding: utf-8 -*-
"""Context ablation (book experiment 1-1, Yummy Tummy version). Each condition run N times → results.json
A all parts / B no tool definitions / C no tool results / D no prior conversation (+D0 control with history)
Usage: python ablation.py [N]   — answers are graded by a person reading every one (see NOTES.md)."""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
from agent import agent, SYSTEM

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
Q = "Can I return order YT-2417?"
T1, T2 = "What's the delivery status of order YT-2417?", "Okay, can I return it?"


def run(cond, k):
    log = []
    sysm = {"role": "system", "content": SYSTEM}
    if cond == "A":
        a, n = agent([sysm, {"role": "user", "content": Q}], log=log.append)
    elif cond == "B":
        a, n = agent([sysm, {"role": "user", "content": Q}], tools=None, log=log.append)
    elif cond == "C":
        a, n = agent([sysm, {"role": "user", "content": Q}], show_results=False, log=log.append)
    else:
        msgs = [sysm, {"role": "user", "content": T1}]
        agent(msgs, log=log.append)
        hist = msgs if cond == "D0" else [sysm]
        a, n = agent(hist + [{"role": "user", "content": T2}], log=log.append)
    return dict(cond=cond, k=k, answer=a, model_calls=n, log=log)


if __name__ == "__main__":
    jobs = [(c, k) for c in ("A", "B", "C", "D0", "D") for k in range(N)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: run(*j), jobs))
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for r in res:
        print(r["cond"], r["k"], r["model_calls"], "|", r["answer"].replace("\n", " ")[:200])
