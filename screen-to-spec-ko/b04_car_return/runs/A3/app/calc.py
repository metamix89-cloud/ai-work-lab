"""요금 계산 로직 (순수 함수 — DB/HTTP 와 분리해 단위 테스트 가능).

금액은 모두 원(KRW) 정수. 시각은 naive datetime(한국 현지시각 기준).
"""
import math
from datetime import datetime

GRACE_MINUTES = 30            # 반납 유예 시간. 이내면 지연 요금 없음
LATE_HOURLY_RATE = 0.10       # 지연 1시간당 일 대여료의 10 %
FUEL_PRICE_PER_LITER = 3000   # 부족 연료 청구 단가(주유 서비스료 포함)
FUEL_UNITS = 8                # 연료 게이지: 0(빈) ~ 8(만)

GRADES = {1: "경미", 2: "보통", 3: "심각"}
GRADE_FEE = {1: 50_000, 2: 150_000, 3: 400_000}

# 부위별 수리비 계수 (유리/범퍼/휠은 수리비가 더 비쌈)
PARTS = {
    "front_bumper": ("앞 범퍼", 1.2),
    "rear_bumper": ("뒤 범퍼", 1.2),
    "hood": ("본넷", 1.0),
    "trunk": ("트렁크", 1.0),
    "roof": ("루프", 1.3),
    "door_fl": ("앞 좌측 도어", 1.0),
    "door_fr": ("앞 우측 도어", 1.0),
    "door_rl": ("뒤 좌측 도어", 1.0),
    "door_rr": ("뒤 우측 도어", 1.0),
    "windshield": ("앞 유리", 1.5),
    "wheel": ("휠/타이어", 1.1),
    "mirror": ("사이드미러", 0.8),
}


def _round10(x: float) -> int:
    return int(round(x / 10.0)) * 10


def damage_fee(part: str, grade: int) -> int:
    return _round10(GRADE_FEE[grade] * PARTS[part][1])


def late_fee(due_at: datetime, returned_at: datetime, daily_rate: int) -> tuple[int, int]:
    """(요금, 지연 분). 유예 시간 초과 시 due 시점부터 시간 단위 올림,
    24시간 블록마다 일 대여료를 상한으로 한다."""
    late_min = (returned_at - due_at).total_seconds() / 60
    if late_min <= GRACE_MINUTES:
        return 0, max(0, math.ceil(late_min))
    hours = math.ceil(late_min / 60)
    days, rem = divmod(hours, 24)
    fee = days * daily_rate + min(rem * LATE_HOURLY_RATE * daily_rate, daily_rate)
    return _round10(fee), math.ceil(late_min)


def fuel_fee(start_fuel: int, return_fuel: int, tank_liters: float) -> tuple[int, int]:
    """(요금, 부족 게이지 칸수). 더 채워서 반납해도 환급 없음."""
    short = max(0, start_fuel - return_fuel)
    return _round10(short * tank_liters / FUEL_UNITS * FUEL_PRICE_PER_LITER), short


def damage_items(pickup: list[dict], found: list[dict]) -> list[dict]:
    """반납 시 발견된 흠집별 청구 항목.

    pickup: 대여 시작 시 이미 기록돼 있던 흠집 [{part, grade}]
    found : 반납 점검에서 기록한 흠집 [{part, grade}]
    같은 부위에 대여 전 흠집이 있으면 '등급이 올라간 만큼의 차액'만 청구한다.
    (같거나 낮은 등급이면 0원 = 기존 흠집.)
    """
    base = {}
    for d in pickup:
        base[d["part"]] = max(base.get(d["part"], 0), d["grade"])
    items = []
    for d in found:
        prior = base.get(d["part"], 0)
        full = damage_fee(d["part"], d["grade"])
        if d["grade"] <= prior:
            fee, status = 0, "pre_existing"
        elif prior:
            fee, status = full - damage_fee(d["part"], prior), "worsened"
        else:
            fee, status = full, "new"
        items.append({**d, "prior_grade": prior, "fee": fee, "status": status})
    return items


def compute(*, daily_rate, tank_liters, due_at, start_fuel, returned_at, return_fuel,
            pickup_damages, found_damages) -> dict:
    late, late_min = late_fee(due_at, returned_at, daily_rate)
    fuel, short = fuel_fee(start_fuel, return_fuel, tank_liters)
    items = damage_items(pickup_damages, found_damages)
    dmg = sum(i["fee"] for i in items)
    return {
        "late_minutes": late_min, "late_fee": late,
        "fuel_short_units": short, "fuel_fee": fuel,
        "damage_items": items, "damage_fee": dmg,
        "total": late + fuel + dmg,
    }
