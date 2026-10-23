"""seed/*.csv 를 '오늘' 기준 날짜로 다시 쓴다. 날짜가 오래돼 숫자가 0 으로 보일 때: python make_seed.py"""
import csv
import datetime as dt
import os

T = dt.date.today()


def D(n):
    return (T - dt.timedelta(days=n)).isoformat()


orders = [
    ("O-1001", D(0) + " 08:10", "행복마트", 184000, "접수"),
    ("O-1002", D(0) + " 09:35", "두리상회", 96000, "출고"),
    ("O-1003", D(0) + " 11:02", "그린식자재", 412000, "접수"),
    ("O-1004", D(0) + " 13:20", "행복마트", 57000, "취소"),
    ("O-1005", D(0) + " 15:48", "미소급식", 230000, "접수"),
    ("O-0991", D(1) + " 17:50", "두리상회", 88000, "출고"),
    ("O-0992", D(1) + " 19:55", "행복마트", 120000, "출고"),
    ("O-0981", D(2) + " 10:00", "미소급식", 75000, "출고"),
    ("O-0982", D(2) + " 14:30", "그린식자재", 310000, "출고"),
    ("O-0971", D(4) + " 09:00", "두리상회", 66000, "출고"),
    ("O-0972", D(4) + " 17:10", "미소급식", 98000, "출고"),
    ("O-0961", D(5) + " 12:00", "행복마트", 150000, "출고"),
    ("O-0962", D(5) + " 15:30", "두리상회", 52000, "출고"),
    ("O-0951", D(8) + " 10:00", "그린식자재", 200000, "출고"),
]
stock = [
    ("F101", "냉동만두 1kg", 12, 40),
    ("F102", "냉동 김말이 1kg", 80, 40),
    ("C201", "두부 300g", 60, 60),
    ("C204", "떡볶이 떡 1kg", 5, 30),
    ("D301", "고추장 500g", 300, 50),
    ("M401", "밀키트 부대찌개", 44, 20),
]
inquiries = [
    ("Q-301", D(0) + " 09:00", "전화", "접수"),
    ("Q-302", D(0) + " 10:30", "이메일", "처리중"),
    ("Q-303", D(1) + " 15:00", "전화", "완료"),
    ("Q-304", D(1) + " 16:20", "채팅", "접수"),
    ("Q-305", D(2) + " 11:00", "이메일", "완료"),
    ("Q-306", D(3) + " 14:00", "전화", "완료"),
]

seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")
os.makedirs(seed, exist_ok=True)
for name, header, rows in [
    ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"], orders),
    ("stock.csv", ["sku", "name", "qty", "safety_qty"], stock),
    ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"], inquiries),
]:
    with open(os.path.join(seed, name), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
