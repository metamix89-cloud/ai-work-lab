"""야간 당직 자동 배정: 휴가자 제외 + 가용일 대비 부담률 균등 + 연속 당직 회피."""
import calendar
from datetime import date


def generate(year, month, nurses, leaves):
    """nurses: [id,...], leaves: {id: set(date)} -> {date: nurse_id}"""
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    avail = {n: sum(1 for d in days if d not in leaves.get(n, ())) for n in nurses}
    count = {n: 0 for n in nurses}
    result = {}
    # 후보가 적은 날부터 먼저 배정해야 휴가가 몰린 날에도 공평하게 채워짐
    order = sorted(days, key=lambda d: (sum(d not in leaves.get(n, ()) for n in nurses), d))
    for d in order:
        cands = [n for n in nurses if d not in leaves.get(n, ())]
        if not cands:
            continue

        def adjacent(n):  # 전날/다음날 이미 당직이면 연속 당직
            return any(result.get(date.fromordinal(d.toordinal() + k)) == n for k in (-1, 1))

        pool = [n for n in cands if not adjacent(n)] or cands
        pick = min(pool, key=lambda n: ((count[n] + 1) / avail[n], count[n], n))
        result[d] = pick
        count[pick] += 1
    return result
