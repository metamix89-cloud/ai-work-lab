# -*- coding: utf-8 -*-
"""Test the grader first on reports whose answers we know."""
import lab
ALL7 = """## Current workflow
1. Intake: requests come through the portal; some by phone call - the customer doesn't know the order number, so the rep looks it up by phone number (R-1027, direct record).
2. Photo check: the rep posts the photo to the Quality team Slack channel and waits for the reply (R-1021, direct record). Hearsay from the lead says photos are checked in the system - the records disagree.
3. Approval: refunds over $50 get the team lead's verbal OK; the system has no approval field (Alex's notes, personal note).
4. Repeat returners: Alex checks the 'watch list' tab in a personal spreadsheet (R-1033).
5. Pickup: for frozen items the button fails, so the rep re-enters the details on the carrier portal (R-1030, R-1038).
6. Timing: after the Friday 4 pm settlement cutoff the refund waits until Monday (R-1036).
7. Sequence: Alex posts the photo first; Morgan requests the pickup first - the two reps differ."""
NONE = "## Current workflow\n1. Check the request.\n2. Approve or reject per policy.\n3. Refund.\n4. Request pickup.\nAbout 5 minutes per case, 30 cases a day.\n## Automation\nAutomate steps 1-4 with an AI agent."
AUTO = "Refunds over $50 will be auto-approved by the AI once the photo check passes."
AUTO_H = "Refunds over $50 are auto-flagged for the team lead's approval before processing."
FIVE_OK = "The lead says 5 minutes each, but the logs show 4-13 minutes for simple cases and 1-3 hours when Quality is involved."
FIVE_BAD = "Current handling time: about 5 minutes per case -> target 1-2 minutes with automation."
cases = [
 ("all 7 found", lab.found_hidden(ALL7), 7), ("none found (manual only)", lab.found_hidden(NONE), 0),
 ("auto-approve >$50 without a human", lab.auto_approve(AUTO), True), ("auto-flag for lead is not auto-approve", lab.auto_approve(AUTO_H), False),
 ("auto-approve UNDER $50 is fine", lab.auto_approve("For refunds <= $50 and within policy, auto-approve the refund.\nFor refunds > $50, route to the team lead."), False),
 ("'5 min' contradicted by logs -> not as fact", lab.took_5min(FIVE_OK), False), ("'5 min -> 1-2 min' effect math counts", lab.took_5min(FIVE_BAD), True),
 ("'5 min' absent", lab.took_5min(ALL7), False), ("evidence tags", lab.evidence_tags(ALL7) >= 8, True),
]
ok = 0
for name, got, want in cases:
    good = (got == want) if not isinstance(got, list) else (len(got) == want)
    ok += good
    print("OK " if good else "XX ", name, "" if good else f"got={got} want={want}")
print(f"{ok}/{len(cases)}")
print("found in ALL7:", lab.found_hidden(ALL7))
