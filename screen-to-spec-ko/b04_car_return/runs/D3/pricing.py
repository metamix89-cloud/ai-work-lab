"""반납 요금 계산 (순수 함수 — DB/HTTP 의존 없음). 금액은 모두 정수 원."""
from dataclasses import dataclass, field
from datetime import datetime
from math import ceil

GRACE_SECONDS = 30 * 60          # 30분까지 유예
LATE_BLOCK_SECONDS = 60 * 60     # 유예 이후 1시간 단위
LATE_BLOCK_FEE = 10_000
LATE_CAP = 80_000
FUEL_MAX = 8
FUEL_FEE_PER_TICK = 15_000
DAMAGE_FEE = {"minor": 30_000, "major": 150_000, "severe": 500_000}
GRADE_RANK = {"minor": 1, "major": 2, "severe": 3}
PARTS = {
    "front_bumper": "앞 범퍼", "rear_bumper": "뒤 범퍼", "hood": "보닛", "roof": "지붕",
    "trunk": "트렁크", "door_fl": "앞 왼쪽 문", "door_fr": "앞 오른쪽 문",
    "door_rl": "뒤 왼쪽 문", "door_rr": "뒤 오른쪽 문", "fender_l": "왼쪽 펜더",
    "fender_r": "오른쪽 펜더", "windshield": "앞 유리", "rear_window": "뒤 유리",
    "wheel": "휠/타이어", "mirror": "사이드미러", "interior": "실내",
}


def late_fee(due: datetime, returned: datetime) -> tuple[int, int]:
    """(지연 분, 요금). 유예 30분 초과분부터 시작된 1시간마다 1만원, 상한 8만원. 조기 반납 환불 없음."""
    late_s = (returned - due).total_seconds()
    if late_s <= GRACE_SECONDS:
        return max(0, int(late_s // 60)), 0
    blocks = ceil((late_s - GRACE_SECONDS) / LATE_BLOCK_SECONDS)
    return int(late_s // 60), min(blocks * LATE_BLOCK_FEE, LATE_CAP)


def fuel_fee(start_fuel: int, return_fuel: int) -> tuple[int, int]:
    """(부족 칸수, 요금). 더 채워 와도 환불 없음."""
    for v in (start_fuel, return_fuel):
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= FUEL_MAX:
            raise ValueError(f"연료는 0~{FUEL_MAX} 정수여야 합니다")
    short = max(0, start_fuel - return_fuel)
    return short, short * FUEL_FEE_PER_TICK


@dataclass
class DamageLine:
    part: str
    grade: str
    pre_existing: bool
    fee: int
    note: str = ""
    photo_id: int | None = None


def damage_lines(pre_existing: list[dict], found: list[dict]) -> list[DamageLine]:
    """found: 반납 시 확인된 흠집 [{part, grade, photo_id}], pre_existing: 대여 전 기록 [{part, grade}].

    같은 부위의 대여 전 흠집 1건은 반납 흠집 1건을 상쇄(0원, 기록만 유지).
    대여 전보다 등급이 악화됐으면 악화분(새 등급 요금 − 기존 등급 요금)만 청구.
    """
    pool = list(pre_existing)
    lines = []
    # 심각한 것부터 매칭해야 같은 부위 다건일 때 결과가 입력 순서에 좌우되지 않음
    for d in sorted(found, key=lambda x: -GRADE_RANK[x["grade"]]):
        if d["grade"] not in DAMAGE_FEE or d["part"] not in PARTS:
            raise ValueError("알 수 없는 부위/등급")
        if not d.get("photo_id"):
            raise ValueError(f"{PARTS[d['part']]} 흠집: 사진이 없는 흠집은 받을 수 없습니다")
        match = next((p for p in pool if p["part"] == d["part"]), None)
        if match is None:
            lines.append(DamageLine(d["part"], d["grade"], False, DAMAGE_FEE[d["grade"]], photo_id=d["photo_id"]))
            continue
        pool.remove(match)
        extra = max(0, DAMAGE_FEE[d["grade"]] - DAMAGE_FEE.get(match["grade"], 0))
        note = "대여 전부터 있던 흠집" if extra == 0 else f"대여 전 {match['grade']} → 악화, 차액만 청구"
        lines.append(DamageLine(d["part"], d["grade"], True, extra, note, d["photo_id"]))
    return lines


def compute(due, returned, start_fuel, return_fuel, pre_existing, found) -> dict:
    late_min, late = late_fee(due, returned)
    short, fuel = fuel_fee(start_fuel, return_fuel)
    lines = damage_lines(pre_existing, found)
    damage = sum(l.fee for l in lines)
    return {
        "late_minutes": late_min, "late_fee": late,
        "fuel_short": short, "fuel_fee": fuel,
        "damage_fee": damage, "damages": [l.__dict__ for l in lines],
        "total": late + fuel + damage,
    }
