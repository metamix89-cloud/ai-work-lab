# -*- coding: utf-8 -*-
"""A(한 줄) · D(한 줄 + 현장 규칙 4줄) 결과물의 코드에서 허가 규칙이 어떻게 정해졌나 훑는다 (사람이 코드로 확인하기 전 1차).
사용: python _scratch/s2s/b06_work_permit/scan_rules.py [A1 A2 ...]  (없으면 runs/ 전부)"""
import glob
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = [
    ("만료 · 유효 시각(expire · valid_until)", r"expir|valid_until|valid_to|만료|유효"),
    ("8시간", r"hours\s*=\s*8\b|timedelta\(hours=8\)|8\s*\*\s*60\s*\*\s*60|8시간|VALID_HOURS"),
    ("당일 23:59 상한", r"23:59|replace\(hour=23|end_of_day|당일|자정"),
    ("본인 승인 금지(requester == approver)", r"requester(_id)?\s*==\s*|\bself[-_ ]?approv|자기 허가|본인|own (permit|request)"),
    ("검토 → 승인 순서(reviewed 상태)", r"[\"']reviewed[\"']|REVIEWED"),
    ("상충(conflict · overlap)", r"conflict|overlap|상충|겹치"),
    ("필수 점검 항목(checklist)", r"check_?items?|checklist|점검 항목|required_items"),
    ("작업 종류 3(고소 · 화기 · 밀폐)", r"confined|밀폐"),
    ("로그인 · 토큰", r"/api/login|/login|password|비밀번호|Bearer|token"),
    ("반려(reject)", r"/reject|reject|반려"),
    ("연장(extend)", r"/extend|extend|연장"),
    ("첨부(UploadFile)", r"UploadFile|multipart"),
]


def src_of(run):
    out = []
    for p in glob.glob(os.path.join(run, "**", "*"), recursive=True):
        if os.path.isfile(p) and p.endswith((".py", ".html", ".js")) and "_grader" not in p and os.sep + "tests" + os.sep not in p:
            try:
                out.append((os.path.relpath(p, run), open(p, encoding="utf-8", errors="ignore").read()))
            except OSError:
                pass
    return out


def main():
    names = sys.argv[1:] or sorted(os.path.basename(d) for d in glob.glob(os.path.join(HERE, "runs", "*")) if os.path.isdir(d))
    for n in names:
        files = src_of(os.path.join(HERE, "runs", n))
        print("=== %s (%d 파일)" % (n, len(files)))
        for label, pat in CHECKS:
            hits = []
            for rel, s in files:
                for m in re.finditer(pat, s, re.I):
                    line = s[: m.start()].count("\n") + 1
                    hits.append("%s:%d" % (rel, line))
            print("  %-36s %s" % (label, (", ".join(hits[:4]) + (" … +%d" % (len(hits) - 4) if len(hits) > 4 else "")) if hits else "—"))
        print()


if __name__ == "__main__":
    main()
