# -*- coding: utf-8 -*-
import lab
print("C expected:", lab.choice("Decision: (C)\nReasons"), "| B expected:", lab.choice("**Decision: (B) Expand while fixing**"))
print("refund · health · recontact · staff all True expected:", lab.mentions("2 out-of-policy refunds and a missed allergy handoff; re-contacts rose to 14%; agents spend 1 h 40 min fixing answers"))
print("all False expected:", lab.mentions("Response time fell to 3 minutes and satisfaction rose"))
print("plan all True expected:", lab.plan_has("| Out-of-policy refunds | guardrail | 0 |\n| Allergy handoff missed | guardrail | 0 |\n| Re-contact rate | counter-metric | 10% or less |\nFail: if a guardrail is broken, do not expand; re-run the pilot"))
