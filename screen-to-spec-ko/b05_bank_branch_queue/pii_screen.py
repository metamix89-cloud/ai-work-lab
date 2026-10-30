# -*- coding: utf-8 -*-
"""대기 화면 글자에 업무 종류가 실제로 보였나 · 호출까지 갔나 · 어느 API 를 읽었나. 사용: python _scratch/s2s/b05_bank_branch_queue/pii_screen.py"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "pii_probe_results.json"), encoding="utf-8"))
for n in sorted(R):
    r = R[n]
    print(n, "화면 업무", r.get("screen_service"), "| 응답 업무", r.get("response_service"), "| 호출", r.get("q_called"), "| 화면", r.get("display", {}).get("path"), r.get("display", {}).get("status"),
          "| API", r.get("display_api"), "| 익명 GET 열림", r.get("crawl", {}).get("open_200"))
