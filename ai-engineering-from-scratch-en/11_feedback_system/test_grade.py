# -*- coding: utf-8 -*-
import lab
t = lab.TASKS[2]   # 2026-10-25 Lakeside: pizza 5 (old 73.40), bbq 5 (old 46.20)
good = "| Pizza Sauce 1 gal | 5 | $73.40 | $367.00 |\n| BBQ Sauce 18 oz | 5 | $46.20 | $231.00 |\nTotal: $598.00 (tax included)\nValid until: 2026-11-08"
print("all ok expected:", lab.check(t, good))
symptom = "| Pizza Sauce 1 gal | 5 | $79.30 | $396.50 |\n| BBQ Sauce 18 oz | 5 | $46.20 | $231.00 |\nTotal $627.50\nQuote valid for 30 days: 2026-11-24"
print("pizza wrong · tax wording fail · validity fail expected:", lab.check(t, symptom))
mixed = "| Pizza Sauce 1 gal | 5 | $73.40 (was $79.30) | $367.00 |\nTotal (tax included)\nValid until: November 8, 2026"
print("pizza mixed values -> not ok; validity ok (Month d, Y):", lab.check(t, mixed)["fails"], lab.check(t, mixed)["valid"])
plus = "| Pizza Sauce 1 gal | 5 | $73.40 | $367.00 |\n| BBQ Sauce 18 oz | 5 | $46.20 | $231.00 |\nSubtotal $598.00 plus tax\nValid until 11/08/2026"
print("'plus tax' -> tax wording fail expected:", lab.check(t, plus)["fails"])
