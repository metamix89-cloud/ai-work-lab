# -*- coding: utf-8 -*-
"""AI 에게 PRD 를 쓰게 한다 — ep088 「PRD, AI 한테 쓰게 하면」 실측용.

단계 (lab/prd_prompts.json 에 프롬프트):
  P1  빈 폴더 + 한 줄 요청 + ep009 의 10칸 목차 → AI 가 PRD.md 를 쓴다
  P2  P1 의 PRD.md 를 넣은 폴더 + 점검표 5문항 → AI 가 PRD.md 를 고쳐 쓴다
사용: python _scratch/s2s/tools/write_ai_prd.py <lab_dir> --stage=P1|P2 [--trials=3] [--model=sonnet] [--start=1]
  → lab/ai_prd/<stage>_<n>.md (+ <stage>_<n>.json 비용 · 턴 · 마지막 답)
작업 폴더는 lab 밖 임시 폴더(run_build.neutral_root) — 상위 CLAUDE.md · PRD.md 를 읽어 오염되지 않게."""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_build import NO_WINDOW, find_claude, neutral_root  # noqa: E402


def main():
    lab = os.path.abspath(sys.argv[1])
    stage, trials, model, start = None, 3, "sonnet", 1
    for a in sys.argv[2:]:
        if a.startswith("--stage="):
            stage = a.split("=", 1)[1]
        elif a.startswith("--trials="):
            trials = int(a.split("=", 1)[1])
        elif a.startswith("--model="):
            model = a.split("=", 1)[1]
        elif a.startswith("--start="):
            start = int(a.split("=", 1)[1])
    if stage not in ("P1", "P2"):
        sys.exit("--stage=P1 또는 P2")
    prompts = json.load(open(os.path.join(lab, "prd_prompts.json"), encoding="utf-8"))
    prompt = prompts[stage]
    out_dir = os.path.join(lab, "ai_prd")
    os.makedirs(out_dir, exist_ok=True)
    claude = find_claude()
    root = os.path.join(neutral_root(), os.path.basename(lab) + "_prd")
    env = dict(os.environ, PYTHONUTF8="1")
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    for k in range(start, start + trials):
        name = "%s_%d" % (stage, k)
        work = os.path.join(root, "%s_%d" % (name, int(time.time())))   # 앞 실행이 죽어 남긴 폴더가 잠겨 있어도 겹치지 않게
        os.makedirs(work)
        if stage == "P2":
            src = os.path.join(out_dir, "P1_%d.md" % k)
            if not os.path.exists(src):
                sys.exit("P1 PRD 없음: " + src)
            shutil.copy(src, os.path.join(work, "PRD.md"))
        cmd = [claude, "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions",
               "--model", model, "--max-turns", "12"]
        t0 = time.time()
        info = {"model": model, "prompt": prompt}
        print(name, "쓰는 중 ...", end=" ", flush=True)
        pr = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                            timeout=900, creationflags=NO_WINDOW)
        info["rc"] = pr.returncode
        try:
            j = json.loads(pr.stdout)
            info.update({x: j.get(x) for x in ("num_turns", "total_cost_usd", "is_error")})
            info["usage"] = j.get("usage")
            info["result"] = (j.get("result") or "")[-2000:]
        except ValueError:
            info["stdout_tail"] = (pr.stdout or "")[-2000:]
        info["wall_s"] = round(time.time() - t0, 1)
        files = sorted(f for f in os.listdir(work))
        info["files"] = files
        prd = os.path.join(work, "PRD.md")
        if os.path.exists(prd):
            shutil.copy(prd, os.path.join(out_dir, name + ".md"))
            info["prd_chars"] = len(open(prd, encoding="utf-8", errors="ignore").read())
        else:
            info["prd_chars"] = 0
        json.dump(info, open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("rc=%s 턴=%s %.0f초 $%.2f PRD %d자 파일 %s" % (info["rc"], info.get("num_turns"), info["wall_s"],
                                                       info.get("total_cost_usd") or 0, info["prd_chars"], files))
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
