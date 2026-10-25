"""반납 요금 계산 규칙. DB·HTTP에 의존하지 않는 순수 함수만 둔다. 금액 단위는 원(정수)."""
import math
from datetime import datetime

GRACE_MINUTES = 30          # 이 시간까지는 지연 요금 없음
LATE_HOURLY_RATE = 0.10     # 1시간(올림)당 1일 요금의 10%, 하루치(100%) 상한
FUEL_PRICE_PER_L = 2000     # 부족 연료 리터당 단가
FUEL_SERVICE_FEE = 10000    # 연료 부족 시 주유 대행 수수료(고정)
FUEL_LEVELS = 8             # 연료 게이지: 0(빈 탱크) ~ 8(만땅), 1칸 = 1/8

PARTS = [
    "앞범퍼", "뒷범퍼", "본넷", "트렁크", "지붕",
    "운전석 앞문", "운전석 뒷문", "조수석 앞문", "조수석 뒷문",
    "좌측 앞펜더", "우측 앞펜더", "좌측 뒷펜더", "우측 뒷펜더",
    "앞유리", "뒷유리", "휠/타이어", "실내",
]
GRADES = {1: "경미", 2: "보통", 3: "심각"}
DAMAGE_FEE = {0: 0, 1: 50000, 2: 150000, 3: 400000}


def late_fee(due: datetime, returned: datetime, daily_rate: int):
    late_min = max(0, math.ceil((returned - due).total_seconds() / 60))
    if late_min <= GRACE_MINUTES:
        return late_min, 0
    hours = math.ceil(late_min / 60)
    days, rem = divmod(hours, 24)
    hourly = round(daily_rate * LATE_HOURLY_RATE)
    return late_min, days * daily_rate + min(rem * hourly, daily_rate)


def fuel_fee(start_level: int, return_level: int, tank_l: int):
    short = max(0, start_level - return_level)
    if short == 0:
        return 0, 0
    liters = short / FUEL_LEVELS * tank_l
    return short, round(liters * FUEL_PRICE_PER_L / 100) * 100 + FUEL_SERVICE_FEE


def damage_line(baseline_grade: int, found_grade: int):
    """대여 전부터 있던 흠집(baseline)은 청구하지 않고, 등급이 악화된 경우 차액만 청구한다."""
    fee = max(0, DAMAGE_FEE[found_grade] - DAMAGE_FEE[baseline_grade])
    if baseline_grade == 0:
        status = "new"
    elif found_grade > baseline_grade:
        status = "worse"
    else:
        status = "existing"
    return fee, status
