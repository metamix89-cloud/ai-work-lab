# -*- coding: utf-8 -*-
"""10편 채점기(코드). 4주 운영 뒤 위키의 '지금 값' 상태.
- 항목(T1~T7): topic 낱말이 든 페이지들의 '현재 값' 절(없으면 본문에서 이력 · 상충 절을 뺀 것)에 now 가 있고 old 가 없으면 '최신'. now 가 어디에도 없으면 '없음', old 만 있으면 '낡음'.
- 지난 예정: 페이지 본문(이력 · 상충 절 밖)에서 '예정' 이 있는 줄 중 날짜가 오늘보다 이전인 줄 수 (코드).
사용: from ops_grade import grade_ops / python ops_grade.py (자가 시험)"""
import glob, json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "ops_items.json"), encoding="utf-8"))
ITEMS = CFG["items"]


def norm(t):
    t = (t or "").replace(",", "")
    t = re.sub(r"\s*[·,]\s*", "·", t)
    return re.sub(r"\s+", " ", t)


def has(text, kws):
    n = norm(text)
    return any(norm(k) in n for k in kws)


def current_section(text):
    """'지금 값' 으로 보는 부분: 본문에서 이력 · ⚠ 상충 · 시행 예정 절을 뺀 나머지(현재 값 · 단가 현황 · 상태 줄 등). (2026-10-23: '현재 값' 절만 보니 단가 현황 표의 79,270 을 못 봄)"""
    return re.sub(r"##\s*(이력|⚠|시행 예정)[^\n]*\n.*?(?=\n## |\Z)", "", text or "", flags=re.S)


def body_no_history(text):
    return re.sub(r"##\s*(이력|⚠)[^\n]*\n.*?(?=\n## |\Z)", "", text or "", flags=re.S)


def line_dates(line, year=2026):
    out = []
    for m in re.finditer(r"(20\d\d)[-./년]\s?(\d{1,2})[-./월]\s?(\d{1,2})", line):
        out.append("%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"(?<![\d-])(\d{1,2})\s?/\s?(\d{1,2})(?![\d/])", line):
        out.append("%d-%02d-%02d" % (year, int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s?월\s?(\d{1,2})\s?일", line):
        out.append("%d-%02d-%02d" % (year, int(m.group(1)), int(m.group(2))))
    return out


def overdue_lines(pages, today):
    """[(slug, 줄)] — '예정' 이 있고 날짜가 전부 오늘 이전인 줄."""
    out = []
    for s, t in pages.items():
        for l in body_no_history(t).split("\n"):
            if "예정" in l and not l.strip().startswith("#"):
                ds = line_dates(l)
                if ds and max(ds) < today:
                    out.append((s, l.strip()))
    return out


def grade_ops(pages, today):
    per = []
    for it in ITEMS:
        hit = {s: current_section(t) for s, t in pages.items() if has(s, it["topic"]) or has(t, it["topic"])}
        now_ok = any(has(sec, it["now"]) for sec in hit.values())
        old_in = [s for s, sec in hit.items() if it["old"] and has(sec, it["old"])]
        state = "최신" if now_ok and not old_in else ("섞임" if now_ok else ("낡음" if old_in else "없음"))
        per.append(dict(id=it["id"], state=state, old_pages=old_in))
    od = overdue_lines(pages, today)
    return dict(items=per, fresh=sum(p["state"] == "최신" for p in per), stale=sum(p["state"] in ("낡음", "섞임") for p in per),
                missing=sum(p["state"] == "없음" for p in per), overdue=len(od), overdue_lines=od[:20], pages=len(pages))


def wiki_pages(wdir):
    return {os.path.splitext(os.path.basename(p))[0]: open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(wdir, "pages", "*.md"))}


if __name__ == "__main__":
    pages = {"거래처-다온팩": "# 다온팩\n## 현재 값\n- 보냉재: 아이스팩 2개 (11/1 원복)\n## 이력\n- 젤팩 1개 → 아이스팩 2개",
             "규정-23-반품-판정-기준": "# 23\n## 현재 값\n- 냉동 7일 이내\n## 시행 예정\n- 냉동 7일 → 14일 (2026-11-03 시행 예정)\n",
             "결정-판촉": "# 판촉\n- 상태: 시행 예정 (11/1 시작 예정)\n## 이력\n- 결정됨",
             "거래처-한빛물류": "# 한빛물류\n## 현재 값\n- 냉동 4,500원 (2026-11-16~)\n- 제주 추가 1,500원 인상 예정 (2027-01-01)",
             "거래처-가나공급": "# 가나공급\n## 현재 값 / 요약\n- 결제 익월 15일\n\n## 단가 현황\n| 품목 | 단가 | 적용일 |\n| 떡볶이 소스 2kg | 73,400원 | 2026-07-01 |\n| 떡볶이 소스 2kg | 79,270원 | 2026-11-01 |\n\n## 이력\n- 73,400 → 79,270"}
    g = grade_ops(pages, "2026-11-23")
    st = {p["id"]: p["state"] for p in g["items"]}
    checks = [("T1 최신(이력의 옛 값은 안 봄)", st["T1"] == "최신"), ("T2 낡음(현재 값에 7일, 14일은 예정 절)", st["T2"] == "낡음"),
              ("T3 낡음(시행 예정)", st["T3"] == "낡음"), ("T5 최신", st["T5"] == "최신"), ("T6 없음", st["T6"] == "없음"),
              ("T4 최신(단가 현황 표의 79,270 도 지금 값)", st["T4"] == "최신"),
              ("지난 예정 2줄(반품 11/3 · 판촉 11/1), 2027 은 아님", g["overdue"] == 2)]
    bad = 0
    for name, ok in checks:
        print(("OK  " if ok else "!!  ") + name); bad += not ok
    print("자가 시험:", "통과" if not bad else "실패 %d" % bad, "|", g["overdue_lines"])
    sys.exit(1 if bad else 0)
