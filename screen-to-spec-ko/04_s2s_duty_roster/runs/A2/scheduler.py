"""야간 당직 자동 배정 로직.

규칙
- 휴가인 간호사는 해당 날짜에 배정하지 않음
- 전날 당직자는 다음 날 배정하지 않음 (연속 야간 금지, 불가피할 때만 허용)
- 총 당직 횟수 차이를 최소화하고, 주말(토·일) 당직도 균등하게 분배
- 무작위 시작을 여러 번 시도해 가장 공평한 결과를 채택 (seed 고정 → 재현 가능)
"""
import calendar
import random
from datetime import date


def _try(nurses, days, on_leave, rng):
    count = {n: 0 for n in nurses}
    weekend = {n: 0 for n in nurses}
    last = {n: -99 for n in nurses}
    result = {}
    violations = 0
    for idx, d in enumerate(days):
        avail = [n for n in nurses if (n, d) not in on_leave]
        if not avail:
            result[d] = None
            violations += 100
            continue
        rested = [n for n in avail if last[n] != idx - 1]
        pool = rested or avail
        if not rested:
            violations += 1
        is_we = d.weekday() >= 5
        pick = min(
            pool,
            key=lambda n: (
                count[n],
                weekend[n] if is_we else 0,
                -(idx - last[n]),
                rng.random(),
            ),
        )
        result[d] = pick
        count[pick] += 1
        weekend[pick] += is_we
        last[pick] = idx
    spread = max(count.values()) - min(count.values())
    wspread = max(weekend.values()) - min(weekend.values())
    return result, (violations, spread, wspread)


def generate(nurse_ids, year, month, leaves, tries=300):
    """leaves: set of (nurse_id, date). 반환: {date: nurse_id|None}"""
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    rng = random.Random(year * 100 + month)
    best, best_score = None, None
    for _ in range(tries):
        res, score = _try(nurse_ids, days, leaves, rng)
        if best_score is None or score < best_score:
            best, best_score = res, score
    return best
