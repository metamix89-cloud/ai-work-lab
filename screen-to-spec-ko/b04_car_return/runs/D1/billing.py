"""반납 요금 계산 (순수 함수). 금액은 모두 원 단위 정수."""
from dataclasses import dataclass, field
from datetime import datetime

GRACE_MIN = 30
LATE_BLOCK_MIN = 60
LATE_BLOCK_FEE = 10_000
LATE_CAP = 80_000
FUEL_MAX = 8
FUEL_FEE_PER_NOTCH = 15_000

DAMAGE_PRICE = {"minor": 30_000, "major": 150_000, "severe": 500_000}
GRADE_RANK = {"minor": 1, "major": 2, "severe": 3}


def late_minutes(due_at: datetime, returned_at: datetime) -> int:
    """분 단위(초 이하 버림)로 늦은 시간. 일찍 오면 0."""
    due = due_at.replace(second=0, microsecond=0)
    ret = returned_at.replace(second=0, microsecond=0)
    return max(0, int((ret - due).total_seconds() // 60))


def late_fee(late_min: int) -> int:
    # 30분까지 유예, 31분부터 1시간 단위 블록(31~90분=1블록, 91~150분=2블록 ...)
    if late_min <= GRACE_MIN:
        return 0
    blocks = -(-(late_min - GRACE_MIN) // LATE_BLOCK_MIN)
    return min(blocks * LATE_BLOCK_FEE, LATE_CAP)


def fuel_fee(pickup_fuel: int, return_fuel: int) -> tuple[int, int]:
    """(모자란 칸, 요금). 더 채워 와도 환불 없음."""
    short = max(0, pickup_fuel - return_fuel)
    return short, short * FUEL_FEE_PER_NOTCH


@dataclass
class DamageResult:
    part: str
    grade: str
    pre_existing: bool          # 대여 전부터 있던 흠집(0원)
    matched_pickup_id: int | None
    charge: int
    note: str = ""


def assess_damages(pickup: list[dict], returned: list[dict]) -> list[DamageResult]:
    """반납 시 기록한 흠집을 대여 시점 흠집과 대조해 요금을 매긴다.

    pickup: [{id, part, grade}], returned: [{part, grade}]
    - 같은 부위에 대여 시점 흠집이 있고 등급이 같거나 더 심했으면 기존 흠집 → 0원.
    - 같은 부위인데 등급이 올라갔으면 올라간 만큼(요금 차액)만 청구.
    - 그 외는 신규 흠집 → 등급 요금 전액.
    입력 순서와 무관하게 결정되도록 심한 등급부터 짝짓는다.
    """
    results: list[DamageResult | None] = [None] * len(returned)
    used: set[int] = set()
    order = sorted(range(len(returned)), key=lambda i: -GRADE_RANK[returned[i]["grade"]])

    def find(r, ok):
        cands = [p for p in pickup if p["id"] not in used and p["part"] == r["part"] and ok(p)]
        # 가장 가까운 등급의 기존 흠집부터
        cands.sort(key=lambda p: abs(GRADE_RANK[p["grade"]] - GRADE_RANK[r["grade"]]))
        return cands[0] if cands else None

    for i in order:  # 1차: 기존과 같거나 덜한 흠집
        r = returned[i]
        p = find(r, lambda p: GRADE_RANK[p["grade"]] >= GRADE_RANK[r["grade"]])
        if p:
            used.add(p["id"])
            results[i] = DamageResult(r["part"], r["grade"], True, p["id"], 0, "대여 전부터 있던 흠집")
    for i in order:  # 2차: 기존보다 악화
        if results[i]:
            continue
        r = returned[i]
        p = find(r, lambda p: True)
        if p:
            used.add(p["id"])
            diff = DAMAGE_PRICE[r["grade"]] - DAMAGE_PRICE[p["grade"]]
            results[i] = DamageResult(r["part"], r["grade"], False, p["id"], diff,
                                      f"기존 {p['grade']} → {r['grade']} 악화분만 청구")
        else:
            results[i] = DamageResult(r["part"], r["grade"], False, None, DAMAGE_PRICE[r["grade"]], "신규 흠집")
    return results  # type: ignore[return-value]


@dataclass
class Bill:
    late_minutes: int
    late_fee: int
    fuel_short: int
    fuel_fee: int
    damages: list[DamageResult] = field(default_factory=list)
    damage_fee: int = 0
    total: int = 0


def compute_bill(due_at, returned_at, pickup_fuel, return_fuel, pickup_damages, return_damages) -> Bill:
    lm = late_minutes(due_at, returned_at)
    short, ff = fuel_fee(pickup_fuel, return_fuel)
    dmg = assess_damages(pickup_damages, return_damages)
    dfee = sum(d.charge for d in dmg)
    lf = late_fee(lm)
    return Bill(lm, lf, short, ff, dmg, dfee, lf + ff + dfee)
