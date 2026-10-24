# -*- coding: utf-8 -*-
"""빌더(Claude Code) 기록 jsonl 에서 도구 호출(명령)만 순서대로 보여 준다 — 빌드가 이유 없이 끊겼을 때 마지막에 뭘 했는지 보려고.
사용: python _scratch/s2s/tools/show_transcript_cmds.py <transcript.jsonl> [--last=N]"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main():
    path = sys.argv[1]
    last = 0
    for a in sys.argv[2:]:
        if a.startswith("--last="):
            last = int(a.split("=", 1)[1])
    rows = []
    for line in open(path, encoding="utf-8", errors="ignore"):
        try:
            j = json.loads(line)
        except Exception:
            continue
        msg = j.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if c.get("type") == "tool_use":
                inp = c.get("input") or {}
                what = inp.get("command") or inp.get("file_path") or inp.get("pattern") or json.dumps(inp, ensure_ascii=False)
                rows.append("[%s] %s" % (c.get("name"), str(what)[:400]))
            elif c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                rows.append("   -> %s" % str(body or "")[:300].replace("\n", " | "))
    for r in rows[-last:] if last else rows:
        print(r)


if __name__ == "__main__":
    main()
