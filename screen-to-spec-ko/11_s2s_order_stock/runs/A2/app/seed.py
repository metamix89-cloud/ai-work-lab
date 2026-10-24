"""가상 데이터. 주문 상태는 실제 서비스 함수를 거쳐 만들어 재고 정합성이 항상 맞는다."""
import hashlib
import secrets

from . import service
from .db import connect, init_schema

USERS = [
    ("staff", "김직원", "staff", "staff123"),
    ("admin", "박관리", "admin", "admin123"),
]

PRODUCTS = [
    ("GN-001", "가나다 김치 1kg", 12900, 120, 20),
    ("GN-002", "가나다 된장 500g", 6500, 80, 15),
    ("GN-003", "가나다 고추장 500g", 7200, 64, 15),
    ("GN-004", "국산 참기름 320ml", 15800, 45, 10),
    ("GN-005", "수제 만두 1.2kg", 11900, 90, 20),
    ("GN-006", "한우 사골곰탕 500g x 6", 29800, 30, 10),
    ("GN-007", "해물 부침가루 1kg", 4900, 150, 30),
    ("GN-008", "유기농 쌀 10kg", 38900, 25, 10),
    ("GN-009", "조미김 5봉 세트", 5900, 200, 40),
    ("GN-010", "매실청 1L", 13500, 18, 10),
    ("GN-011", "명란젓 250g", 16900, 8, 10),
    ("GN-012", "국산 들깨가루 200g", 8800, 5, 10),
]

CUSTOMERS = [
    ("이서준", "010-0000-2831", "서울 강남구 테헤란로 12"),
    ("최지우", "010-0000-2643", "경기 성남시 분당구 판교로 45"),
    ("정하윤", "010-0000-4839", "부산 해운대구 해운대로 301"),
    ("한도윤", "010-0000-2640", "대구 수성구 달구벌대로 88"),
    ("오서연", "010-0000-5334", "인천 연수구 송도과학로 17"),
    ("윤민재", "010-0000-9540", "광주 서구 상무중앙로 9"),
    ("강예린", "010-0000-5467", "대전 유성구 대학로 99"),
    ("송지호", "010-0000-1100", "서울 마포구 월드컵북로 21"),
]


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def seed_if_empty():
    init_schema()
    conn = connect()
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        for username, name, role, pw in USERS:
            salt = secrets.token_hex(16)
            conn.execute(
                "INSERT INTO users (username, name, role, pw_salt, pw_hash) VALUES (?,?,?,?,?)",
                (username, name, role, salt, hash_pw(pw, salt)),
            )
        for sku, name, price, stock, safety in PRODUCTS:
            conn.execute(
                "INSERT INTO products (sku, name, price, stock, safety_stock) VALUES (?,?,?,?,?)",
                (sku, name, price, stock, safety),
            )
    finally:
        conn.close()

    # (고객 idx, [(상품 id, 수량)], 최종 처리)
    plan = [
        (0, [(1, 2), (5, 1)], "ship"),
        (1, [(4, 1), (9, 3)], "ship"),
        (2, [(8, 1)], "refund"),
        (3, [(6, 1), (2, 2)], "cancel_confirmed"),
        (4, [(3, 2), (7, 4)], "confirm"),
        (5, [(1, 1), (10, 1)], "confirm"),
        (6, [(5, 2)], "confirm"),
        (7, [(9, 5), (4, 2)], "pending"),
        (0, [(11, 3)], "pending"),
        (1, [(12, 2), (2, 1)], "pending"),
        (2, [(6, 2), (8, 1)], "pending"),
        (3, [(7, 2)], "cancel_pending"),
        (4, [(1, 3)], "ship"),
    ]
    for ci, items, final in plan:
        c = CUSTOMERS[ci]
        oid = service.create_order(c[0], c[1], c[2], items, "seed")
        if final in ("confirm", "ship", "refund", "cancel_confirmed"):
            service.confirm_order(oid, "staff")
        if final in ("ship", "refund"):
            service.ship_order(oid, "staff")
        if final == "refund":
            service.refund_order(oid, "admin", True, "고객 변심 환불")
        if final in ("cancel_confirmed", "cancel_pending"):
            service.cancel_order(oid, "staff", "고객 요청 취소")
