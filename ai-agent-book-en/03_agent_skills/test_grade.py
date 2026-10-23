# -*- coding: utf-8 -*-
"""Grader self-test (no API calls): right answers must pass, typical wrong answers must fail.
Usage: python test_grade.py   (after make_skills.py)"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "x")
import make_ppt
from lab import grade_text, grade_pptx

T = [
    ("T2", "[Decision] Not returnable\nRefund: $0.00\nRefrigerated items: 3 days.", [], True),
    ("T2", "**[Decision] Not returnable**\nRefund: $0.00", [], True),
    ("T2", "The window has passed, so it's not returnable.\n[Decision] Not returnable", [], False),   # format broken
    ("T2", "[Decision] Returnable\nRefund: $20.90", [], False),
    ("T10", "[Decision] Returnable\nRefund: $8.50\nQuality issue, full refund.", [], True),
    ("T10", "[Decision] Returnable\nRefund: $5.50", [], False),
    ("T3", "[Yummy Tummy Foods] Re: November price adjustment notice\nDear Ms. Lee,\n...\nYummy Tummy Foods Sales Support Team | (555) 010-0000", [], True),
    ("T3", "[Yummy Tummy Foods] Re: November price adjustment notice\nWe accept the new price.\nYummy Tummy Foods Sales Support Team", [], False),
    ("T3", "Subject: Re: November price adjustment\nBest regards, Sales", [], False),
    ("T4", "Minutes | New product | 10/20\n■ Decisions\n- Agreed to ...\n■ Action Items\n- Sign draft / Park / due TBD\n■ Next Meeting\n- TBD", [], True),
    ("T4", "Meeting notes\n- Decisions: launch\n- Park: sign draft", [], False),
    ("T5", "Soft sesame buns\nGreat for burgers\n[Allergens] Wheat, soybeans, sesame", [], True),
    ("T5", "Soft sesame buns\nGreat for burgers\n[Allergens] Wheat, sesame", [], False),
    ("T6", "🔴 Reorder | Pepperoni Pizza 2-pack | stock 300 / safety 390\n🔴 Reorder | Cola 12-pack | stock 140 / safety 150\n🟢 OK | Mac & Cheese Bake | stock 500 / safety 300", [], True),
    ("T6", "🔴 Reorder | Pepperoni Pizza 2-pack\n🟢 OK | Mac & Cheese Bake\n🟢 OK | Cola 12-pack", [], False),
    ("T6", "- Pepperoni Pizza 2-pack: 300 < 390 → reorder\n- Mac & Cheese Bake: OK\n- Cola 12-pack: 140 < 150\n\n"
           "🔴 Reorder | Pepperoni Pizza 2-pack | stock 300 / safety 390\n🔴 Reorder | Cola 12-pack | stock 140 / safety 150\n"
           "🟢 OK | Mac & Cheese Bake | stock 500 / safety 300", [], True),   # calculation first, alert lines after
    ("T6", "- Pepperoni Pizza 2-pack: monitor closely\n- Cola 12-pack: adequate", [], False),
    ("T7", "Transportation: $119.60\n...\nTotal reimbursement: $379.60", [], True),
    ("T7", "Total reimbursement: $319.60", [], False),
    ("T8", "VLOOKUP finds a value...", [], True),
    ("T8", "VLOOKUP finds a value...", ["product-copy"], False),
    ("T9", "Team dinner Friday 7 pm!", [], True),
    ("T9", "Team dinner Friday 7 pm\nYummy Tummy Foods Sales Support Team", ["partner-email"], False),
]
ok = 0
for tid, text, read, want in T:
    got = grade_text(tid, text, read)[0]
    ok += got == want
    print("OK " if got == want else "XX ", tid, repr(text[:40]), got)

out = os.path.join(HERE, "out")
os.makedirs(out, exist_ok=True)
good = {"slides": [{"title": "Weekly Sales Report | 10/13-10/17", "bullets": []}, {"title": "Sales summary", "bullets": ["$24.1K (105%)"]},
                   {"title": "By product", "bullets": []}, {"title": "Issues", "bullets": []}, {"title": "Next Week To-Do", "bullets": []}]}
bad = {"slides": good["slides"][:4]}
cases = [(good, True), (bad, False), ({"slides": []}, False)]
for i, (outline, want) in enumerate(cases):
    p = os.path.join(out, "_test_%d.pptx" % i)
    make_ppt.build(outline, p)
    got = grade_pptx(p)[0]
    ok += got == want
    print("OK " if got == want else "XX ", "T1 pptx case", i, got)
    os.remove(p)
print("%d/%d" % (ok, len(T) + len(cases)))
