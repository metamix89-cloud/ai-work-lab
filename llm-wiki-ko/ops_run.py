# -*- coding: utf-8 -*-
"""10편 실험: 7편 위키 위에 ops/ 4주(W44~W47) 원본을 주마다 넣고, 마지막 날(11/23) 위키가 '지금 값' 을 들고 있는지 본다(ops_grade).
조건: plain = 주마다 그냥 넣기 · routine = 주마다 넣은 뒤 코드가 '지난 예정' 줄(날짜가 지난 '예정')을 찾아 그 페이지만 모델에게 "오늘 기준으로 현재 값으로 옮기고 이력에 남겨라" 시키기(운영 루틴)
사용: python _scratch/wiki/ops_run.py [--conds=plain,routine] [--name=ep10]
결과 results/<name>.json — 조건별 주차마다 채점(최신 · 낡음 · 없음 · 지난 예정 줄 수) · 루틴이 고친 페이지 · 토큰"""
import glob, json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from ops_grade import CFG, grade_ops, overdue_lines, wiki_pages
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
CONDS = opt("conds", "plain,routine").split(","); NAME = opt("name", "ep10")
KW = dict(tally=True, auto_index=True, extract=True, amend_guard=True, require_write=True)
ROUTINE_SYS = """너는 가나다식품(가상 회사) LLM 위키의 운영 담당이다. 오늘 날짜는 {today} 다. 아래 페이지에는 시행일 · 적용일이 이미 지난 '예정' 값이 있다.
read_page 로 페이지를 읽고, 지난 예정 값을 '현재 값' 으로 옮기고(이전 값은 '이력' 에 '이전 → 새 값 (시행일, 출처)' 로), '시행 예정' 줄은 지운다. 다른 내용은 바꾸지 않는다. write_page 로 저장한 뒤 한 줄로 보고한다.
[schema]
"""


def routine(w, today):
    """지난 예정 줄이 있는 페이지마다 모델에게 현재 값으로 옮기게 한다. (고친 페이지 수, 토큰, 전 · 후 지난 예정 줄 수)"""
    od = overdue_lines(wiki_pages(w.dir), today)
    slugs = sorted({s for s, _ in od})
    tokens = 0
    for s in slugs:
        lines = "\n".join("- " + l for ss, l in od if ss == s)
        user = "페이지: %s\n지난 예정 줄:\n%s" % (s.replace("-", "/", 1), lines)
        ans, t, trace = E.run_agent(w, ROUTINE_SYS.format(today=today) + w.schema, user, E.TOOLS_RW, 8)
        tokens += t
    w.rebuild_index()
    return len(slugs), tokens, len(od), len(overdue_lines(wiki_pages(w.dir), today))


out = {}
for cond in CONDS:
    wdir = os.path.join(HERE, "wiki_%s_%s" % (NAME, cond))
    shutil.rmtree(wdir, ignore_errors=True); shutil.copytree(os.path.join(HERE, "wiki_ep7"), wdir, ignore=shutil.ignore_patterns("BUILT"))
    w = E.Wiki(wdir, schema_path=os.path.join(HERE, "schema_ep5.md"))
    weeks, t0, tok = [], time.time(), 0
    for wk, today in CFG["weeks"]:
        files = sorted(glob.glob(os.path.join(E.RAW, "ops", "2026-%s_*" % wk)))
        for f in files:
            r = E.ingest(w, f, today, **KW); tok += r["tokens"]
            print("[%s %s] %-32s pages=%s tok=%d" % (cond, wk, os.path.basename(f)[:32], r["pages_written"], r["tokens"]), flush=True)
        fixed = None
        if cond == "routine":
            fixed = routine(w, today); tok += fixed[1]
            print("[%s %s] 루틴: 페이지 %d 고침 · 지난 예정 %d → %d · 토큰 %d" % (cond, wk, fixed[0], fixed[2], fixed[3], fixed[1]), flush=True)
        g = grade_ops(wiki_pages(wdir), today)
        weeks.append(dict(week=wk, today=today, files=[os.path.basename(f) for f in files], grade=g, routine=fixed))
        print("== %s %s: 최신 %d · 낡음 %d · 없음 %d · 지난 예정 %d · 페이지 %d" % (cond, wk, g["fresh"], g["stale"], g["missing"], g["overdue"], g["pages"]), flush=True)
    final = grade_ops(wiki_pages(wdir), CFG["today_final"])
    out[cond] = dict(weeks=weeks, final=final, tokens=tok, sec=round(time.time() - t0))
    print("== %s 최종(%s): 최신 %d/%d · 낡음 %d · 없음 %d · 지난 예정 %d · 토큰 %d · %ds" % (cond, CFG["today_final"], final["fresh"], len(final["items"]), final["stale"], final["missing"], final["overdue"], tok, out[cond]["sec"]), flush=True)
    json.dump(out, open(os.path.join(HERE, "results", NAME + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
