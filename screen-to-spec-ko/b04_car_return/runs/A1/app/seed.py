"""가상 데이터. DB가 비어 있을 때만 채운다."""
import secrets
import struct
import zlib
from datetime import datetime, timedelta

from . import service
from .db import UPLOAD_DIR, hash_pw

DEMO_PASSWORD = "demo1234"
USERS = [  # username, 이름, 역할
    ("staff", "김직원", "staff"),
    ("minsu", "박민수", "customer"),
    ("jiyeon", "이지연", "customer"),
    ("hyunwoo", "최현우", "customer"),
]
VEHICLES = [  # 번호판, 모델, 탱크(L), 일 요금, 주행거리
    ("12가 3456", "현대 아반떼", 47, 60000, 32450),
    ("34나 7890", "기아 K5", 60, 80000, 18200),
    ("56다 1122", "현대 쏘나타", 60, 85000, 41300),
    ("78라 3344", "기아 쏘렌토", 67, 120000, 27800),
    ("90마 5566", "현대 팰리세이드", 71, 150000, 12900),
    ("23바 7788", "기아 레이", 35, 50000, 56100),
]


def _png(rgb, stripe) -> bytes:
    """외부 파일 없이 만든 작은 PNG(가상 흠집 사진 자리표시)."""
    w, h = 240, 150
    rows = b""
    for y in range(h):
        row = b"\x00"
        for x in range(w):
            on = abs((x - 60) - (y * 1.4)) < 5 or abs((x - 120) - (y * 1.4)) < 2
            row += bytes(stripe if on else rgb)
        rows += row

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _photo(rgb, stripe) -> str:
    name = f"{secrets.token_hex(16)}.png"
    (UPLOAD_DIR / name).write_bytes(_png(rgb, stripe))
    return name


def seed_if_empty(db):
    if db.execute("SELECT 1 FROM users").fetchone():
        return
    for username, name, role in USERS:
        salt, h = hash_pw(DEMO_PASSWORD)
        db.execute("INSERT INTO users (username, name, role, pw_salt, pw_hash) VALUES (?,?,?,?,?)",
                   (username, name, role, salt, h))
    for v in VEHICLES:
        db.execute("INSERT INTO vehicles (plate, model, tank_liters, daily_rate, odometer) VALUES (?,?,?,?,?)", v)
    uid = {r["username"]: r["id"] for r in db.execute("SELECT id, username FROM users")}
    vid = {r["plate"]: r["id"] for r in db.execute("SELECT id, plate FROM vehicles")}

    # 차량이 원래 갖고 있던 흠집(대여 전 흠집 → 청구 제외 대상)
    old = [
        ("34나 7890", "앞범퍼", 2, "우측 하단 긁힘", _photo((200, 205, 215), (120, 60, 60))),
        ("34나 7890", "운전석 앞문", 1, "작은 덴트", _photo((190, 200, 210), (90, 90, 140))),
        ("56다 1122", "뒷범퍼", 1, "스크래치", _photo((205, 200, 195), (150, 90, 40))),
        ("78라 3344", "휠/타이어", 1, "휠 스크래치", None),
    ]
    for plate, part, grade, note, photo in old:
        db.execute("INSERT INTO vehicle_damage VALUES (?,?,?,?,?)", (vid[plate], part, grade, note, photo))

    fmt = lambda dt: dt.strftime(service.TIME_FMT)
    now = datetime.now().replace(second=0, microsecond=0)
    sid = uid["staff"]

    # (A) 완료된 대여: 지연 + 연료 부족 + 신규 흠집 + 기존 흠집(청구 제외) → 청구서 확인용
    t0 = now - timedelta(days=9)
    r1 = service.start_rental(db, uid["minsu"], vid["34나 7890"], fmt(t0 + timedelta(days=3)), 8, [], fmt(t0))
    service.finish_return(db, r1, {
        "returned_at": fmt(t0 + timedelta(days=3, hours=2, minutes=20)), "fuel": 5, "odometer": 18200 + 640,
        "damages": [
            {"part": "앞범퍼", "grade": 2, "note": "기존 긁힘 (대여 전부터 있었음)", "photo": None},
            {"part": "조수석 뒷문", "grade": 2, "note": "주차 중 문콕 추정", "photo": _photo((200, 205, 215), (160, 40, 40))},
        ]}, sid)

    # (B) 완료된 대여: 깔끔한 반납 (청구 0원)
    t1 = now - timedelta(days=5)
    r2 = service.start_rental(db, uid["jiyeon"], vid["12가 3456"], fmt(t1 + timedelta(days=2)), 8, [], fmt(t1))
    service.finish_return(db, r2, {
        "returned_at": fmt(t1 + timedelta(days=2, minutes=-15)), "fuel": 8, "odometer": 32450 + 310, "damages": []}, sid)

    # (C) 진행 중 대여 — 반납 처리 데모용
    service.start_rental(db, uid["minsu"], vid["34나 7890"], fmt(now - timedelta(hours=3)), 8, [],
                         fmt(now - timedelta(days=2)))                 # 이미 3시간 지연 상태
    service.start_rental(db, uid["jiyeon"], vid["56다 1122"], fmt(now + timedelta(days=1)), 6, [],
                         fmt(now - timedelta(days=1)))
    service.start_rental(db, uid["hyunwoo"], vid["78라 3344"], fmt(now + timedelta(days=2)), 8, [],
                         fmt(now - timedelta(hours=6)))
