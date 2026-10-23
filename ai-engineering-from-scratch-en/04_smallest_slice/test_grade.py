# -*- coding: utf-8 -*-
import lab
print("S3 expected:", lab.pick("Choice: S3\nReasons..."), lab.pick("**Choice: S2**"), "S2 expected")
good = "Re-judge 400 photos from the last 6 months (frozen and spoilage included), and 2 reps handle real returns for one week using the AI call as a reference only, recording handling time. No automatic refunds - a person makes the final call. Stop rule: if agreement is below 85%, stop."
print("frozen real staff stop True · auto False expected:", lab.proposal_checks(good))
bad = "Test on 300 past photos of shelf-stable box damage only (frozen / spoilage in phase 2). If it works, apply automatic refunds when 'damage confirmed'."
print("frozen False · auto True expected:", lab.proposal_checks(bad))
p2 = "1. What\n- Pilot limited to the 'shelf-stable box damage' type\n2. With which data\n- 300 photos\n3. Who\n- The reps\nLater, expand to frozen / refrigerated spoilage"
print("box-damage-only -> frozen False expected:", lab.covers_frozen(p2))
