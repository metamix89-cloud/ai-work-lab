# -*- coding: utf-8 -*-
import lab
good = lab.DOC.replace("$73.40", "$79.30").replace("$46.20", "$47.50").replace("Snack Gift Box: peanuts", "Snack Gift Box: peanuts, walnuts, almonds") \
    .replace("Sesame Burger Buns 8-pack: soy", "Sesame Burger Buns 8-pack: soy, sesame").replace("by 3 pm", "by 2 pm").replace("within 7 days", "within 14 days")
print("answer 7/3 ok True expected:", lab.grade(good))
print("original 0/3 expected:", lab.grade(lab.DOC)["n_survived"], lab.grade(lab.DOC)["kept"])
last_only = lab.DOC.replace("Snack Gift Box: peanuts", "Snack Gift Box: peanuts, walnuts, almonds").replace("Sesame Burger Buns 8-pack: soy", "Sesame Burger Buns 8-pack: soy, sesame")
print("'last save wins' (allergens only) 3 expected:", lab.grade(last_only)["n_survived"])
