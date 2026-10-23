# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
import lab
good = lab.DOC.replace("73,400원", "79,270원").replace("46,200원", "47,500원").replace("견과 선물세트: 땅콩", "견과 선물세트: 땅콩, 호두, 아몬드") \
    .replace("김자반 50g: 대두", "김자반 50g: 대두, 참깨").replace("오후 3시", "오후 2시").replace("7일 이내", "14일 이내")
g = lab.grade(good); print("정답 7/3 ok 기대:", g["n_survived"], g["kept"], g["ok"])
g = lab.grade(lab.DOC); print("원본 0/3 기대:", g["n_survived"], g["kept"])
only_ship = lab.DOC.replace("오후 3시", "오후 2시").replace("7일 이내", "14일 이내")
g = lab.grade(only_ship); print("배송만(마지막 저장이 이김) 2 기대:", g["n_survived"], g["survived"])
