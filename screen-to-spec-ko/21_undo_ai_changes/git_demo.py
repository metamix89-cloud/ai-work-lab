# -*- coding: utf-8 -*-
"""영상의 '깃 명령 4개' 를 사람이 직접 칠 때를 재 본다 — AI 없이.
임시 폴더에 원본(base/)을 놓고 git init → git add -A → git commit → (broken/ 으로 덮어씀) → git diff --stat → git restore .
되돌린 뒤 원본 6개 파일과 지문(sha1)을 비교하고 restore 에 걸린 시간을 잰다. 새로 생긴 파일(추적 안 됨)이 restore 뒤에 남는지도 본다.
이 PC 의 git 기본 설정 그대로(mode=default)와 줄 끝 변환을 끈 설정(mode=noautocrlf) 두 번.
사용: python _scratch/s2s/21_undo_ai_changes/git_demo.py  → git_demo.json"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_undo import clear, put   # noqa: E402


def git(work, *args):
    t0 = time.time()
    r = subprocess.run(["git", "-c", "user.name=lab", "-c", "user.email=lab@example.com"] + list(args), cwd=work,
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return (r.stdout + r.stderr).strip(), round(time.time() - t0, 3)


def sha_all(d):
    out = {}
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            if f.endswith(".db"):   # 서버가 켤 때마다 새로 만드는 파일 — 비교에서 뺀다
                continue
            p = os.path.join(root, f)
            out[os.path.relpath(p, d).replace(os.sep, "/")] = hashlib.sha1(open(p, "rb").read()).hexdigest()
    return out


def main():
    base = os.path.join(HERE, "base")
    want = sha_all(base)
    result = {"git_version": git(HERE, "--version")[0], "autocrlf_default": git(tempfile.gettempdir(), "config", "--get", "core.autocrlf")[0]}
    for mode in ("default", "noautocrlf"):
        work = tempfile.mkdtemp(prefix="ep098_git_")
        try:
            put(base, work)
            log = {}
            log["init"] = git(work, "init", "-q")
            if mode == "noautocrlf":
                git(work, "config", "core.autocrlf", "false")
            log["add"] = git(work, "add", "-A")
            log["commit"] = git(work, "commit", "-q", "-m", "AI 시키기 전")
            clear(work)
            put(os.path.join(HERE, "broken"), work)
            open(os.path.join(work, "new_by_ai.txt"), "w", encoding="utf-8").write("AI 가 새로 만든 파일\n")
            log["diff_stat"] = git(work, "diff", "--stat")
            log["restore"] = git(work, "restore", ".")
            log["status_after"] = git(work, "status", "--short")
            got = sha_all(work)
            same = sum(got.get(f) == h for f, h in want.items())
            result[mode] = {"same_files": same, "of": len(want), "restore_seconds": log["restore"][1],
                            "new_file_left": "new_by_ai.txt" in got, "log": {k: v[0] for k, v in log.items()}}
            print(mode, "| 원본과 같은 파일 %d/%d | restore %.3f초 | 새 파일 남음 %s" % (same, len(want), log["restore"][1], "new_by_ai.txt" in got))
            print("  diff --stat:", log["diff_stat"][0].replace("\n", " / "))
            print("  add:", log["add"][0][:300].replace("\n", " / "))
            print("  status 뒤:", log["status_after"][0])
        finally:
            shutil.rmtree(work, ignore_errors=True)
    json.dump(result, open(os.path.join(HERE, "git_demo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
