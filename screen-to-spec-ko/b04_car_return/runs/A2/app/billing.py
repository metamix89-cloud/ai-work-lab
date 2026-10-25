"""반납 요금 계산 (순수 함수 — DB/HTTP 와 무관)."""
import math
from datetime import datetime

GRACE_MIN = 30            # 반납 유예 30분
LATE_HOURLY_RATE = 0.10   # 초과 1시간당 일 요금의 10% (24시간분은 일 요금 1일치로 상한)
FUEL_PRICE = 1800         # 원/L
FUEL_MARKUP = 1.5         # 부족분 연료는 시중가의 1.5배로 청구
DAMAGE_FEE = {1: 30_000, 2: 120_000, 3: 400_000}
GRADE_LABEL = {1: "1등급 (미세 스크래치)", 2: "2등급 (깊은 긁힘·소형 찍힘)", 3: "3등급 (큰 찍힘·파손)"}
PARTS = [
    "앞 범퍼", "뒤 범퍼", "본넷", "트렁크", "지붕",
    "운전석 앞문", "운전석 뒷문", "조수석 앞문", "조수석 뒷문",
    "좌측 앞 펜더", "우측 앞 펜더", "좌측 뒤 펜더", "우측 뒤 펜더",
    "앞 유리", "뒤 유리", "휠/타이어",
]


def _won(x: float) -> int:
    return int(round(x, -2))  # 100원 단위 반올림


def late_line(due: datetime, returned: datetime, daily_rate: int):
    over_min = (returned - due).total_seconds() / 60
    if over_min <= GRACE_MIN:
        return None
    hours = math.ceil(over_min / 60)
    days, rem = divmod(hours, 24)
    fee = days * daily_rate + min(rem * daily_rate * LATE_HOURLY_RATE, daily_rate)
    return {"type": "late", "description": f"반납 지연 {hours}시간 (유예 {GRACE_MIN}분 초과)", "amount": _won(fee)}


def fuel_line(start_eighths: int, end_eighths: int, tank_l: int):
    short = start_eighths - end_eighths
    if short <= 0:
        return None
    liters = tank_l * short / 8
    fee = liters * FUEL_PRICE * FUEL_MARKUP
    return {"type": "fuel", "description": f"연료 {short}/8 부족 (약 {liters:.1f}L × {FUEL_PRICE:,}원 × {FUEL_MARKUP})",
            "amount": _won(fee)}


def damage_lines(reported: list[dict], pre_existing: list[dict]):
    """reported/pre_existing: [{part, grade}]. 같은 부위의 기존 흠집과 1:1 로 짝지어
    기존 등급 이하이면 0원, 더 심해졌으면 등급 차액만 청구한다."""
    pre_by_part: dict[str, list[int]] = {}
    for p in pre_existing:
        pre_by_part.setdefault(p["part"], []).append(p["grade"])
    for v in pre_by_part.values():
        v.sort(reverse=True)
    lines = []
    for d in sorted(reported, key=lambda x: -x["grade"]):
        pre = pre_by_part.get(d["part"], [])
        base = pre.pop(0) if pre else 0
        fee = max(0, DAMAGE_FEE[d["grade"]] - (DAMAGE_FEE[base] if base else 0))
        if base == 0:
            desc, note = f"{d['part']} 신규 흠집 {d['grade']}등급", None
        elif d["grade"] <= base:
            desc, note = f"{d['part']} {d['grade']}등급 — 대여 전부터 있던 흠집 (청구 제외)", "기존"
        else:
            desc, note = f"{d['part']} 기존 {base}등급 → {d['grade']}등급 악화 (차액 청구)", "악화"
        lines.append({"type": "damage", "description": desc, "amount": fee, "part": d["part"],
                      "grade": d["grade"], "note": note, "photo_id": d.get("photo_id")})
    return lines
