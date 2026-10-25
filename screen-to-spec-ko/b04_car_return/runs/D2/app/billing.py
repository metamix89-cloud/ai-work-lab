"""요금 규칙. 금액은 모두 정수(원). DB·HTTP와 무관한 순수 함수만 둔다."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))  # 한국은 DST가 없어 고정 오프셋으로 충분

LATE_GRACE_MIN = 30        # 예정 시각 + 30분까지 유예
LATE_BLOCK_MIN = 60        # 유예 이후 1시간 단위
LATE_BLOCK_FEE = 10_000
LATE_CAP = 80_000          # 한 건 상한

FUEL_MAX = 8
FUEL_FEE_PER_NOTCH = 15_000

DAMAGE_FEES = {"minor": 30_000, "major": 150_000, "severe": 500_000}
GRADE_RANK = {"minor": 1, "major": 2, "severe": 3}
GRADE_LABEL = {"minor": "경미", "major": "중간", "severe": "심각"}


def late_fee(due_at: datetime, returned_at: datetime) -> tuple[int, int]:
    """(지연 분, 요금). 분 단위로 내림 — 30분 59초 지연은 30분으로 보아 유예.

    31분째부터 첫 1시간 블록이 시작되고(10,000원), 그 뒤 60분마다 블록이 추가된다.
    일찍 반납해도 환불은 없다(음수 없음).
    """
    late_min = max(0, int((returned_at - due_at).total_seconds() // 60))
    if late_min <= LATE_GRACE_MIN:
        return late_min, 0
    over = late_min - LATE_GRACE_MIN
    blocks = -(-over // LATE_BLOCK_MIN)  # ceil
    return late_min, min(blocks * LATE_BLOCK_FEE, LATE_CAP)


def fuel_fee(start_fuel: int, end_fuel: int) -> tuple[int, int]:
    """(모자란 칸 수, 요금). 더 채워 와도 환불 없음."""
    short = max(0, start_fuel - end_fuel)
    return short, short * FUEL_FEE_PER_NOTCH


def damage_fee(grade: str, pre_existing: bool) -> int:
    return 0 if pre_existing else DAMAGE_FEES[grade]
