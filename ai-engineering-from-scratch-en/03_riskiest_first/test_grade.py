# -*- coding: utf-8 -*-
"""Test the grader first on plans whose answers we know."""
import lab
good = """## Assumptions
1. Customer photos may be sent to an outside AI (safety) - impact 5 · uncertainty 4 · reversal 5 -> 25
## First 2 weeks
Week 1
- Request the Security team's prior approval under Information Security Policy section 7 (no real customer photos leave the company before approval)
- Test the AI's calls against the Quality team's calls on 200 past photos from the last 6 months (masked)
- Criterion: agreement 90% or higher passes; 80-90% is inconclusive -> add a human review step
- If the criterion is not met, stop the automatic judgment and pivot to shortening the Quality reply (alerts)
Week 2
- On pass, start API integration with IT and the support system (no automatic refunds - recommendation only)"""
g = lab.grade(good); print("all True expected:", g)
bad = """## First 2 weeks
Week 1: develop the outside image API integration, connect the support system
Week 2: enable automatic refunds when the call is 'damage confirmed', go live
- Consult the Security team about personal data"""
g = lab.grade(bad); print("sec_first False · auto True · past False · thr False expected:", g)
print("'halve handling time' is not a criterion (False expected):", lab.threshold("- Target: cut judgment handling time by 50%"))
print("'go-live if accuracy > 90%' is conditional (auto False expected):", lab.auto_refund_2w("Week 2: enable automatic refunds only if accuracy is above 90%"))
