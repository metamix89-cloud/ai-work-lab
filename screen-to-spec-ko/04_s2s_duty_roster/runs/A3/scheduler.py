"""야간 당직 자동 배정: 휴가 제외 + 연속 근무 금지 + 공평 분배(가용일 대비 횟수 → 주말/공휴일 횟수 → 근무 간격)."""
import calendar
from datetime import date

# 2026년 공휴일 (필요 시 추가)
HOLIDAYS = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01", "2026-03-02",
    "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-03", "2026-08-15",
    "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-05",
    "2026-10-09", "2026-12-25",
}


def month_days(month: str) -> list[date]:
    y, m = map(int, month.split("-"))
    return [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def is_heavy(d: date) -> bool:
    """주말·공휴일 여부 (당직 부담이 큰 날)"""
    return d.weekday() >= 5 or d.isoformat() in HOLIDAYS


def generate(month: str, nurse_ids: list[int], leaves: dict[int, set[str]]) -> dict[str, int | None]:
    days = month_days(month)
    avail = {n: sum(1 for d in days if d.isoformat() not in leaves.get(n, set())) for n in nurse_ids}
    count = {n: 0 for n in nurse_ids}
    heavy = {n: 0 for n in nurse_ids}
    assigned: dict[int, int] = {}

    # 후보가 적은 날(휴가자가 많은 날)부터 먼저 배정하면 막히는 날이 줄어든다.
    order = sorted(range(len(days)), key=lambda i: sum(
        1 for n in nurse_ids if days[i].isoformat() not in leaves.get(n, set())))
    for i in order:
        d = days[i]
        cands = [n for n in nurse_ids if d.isoformat() not in leaves.get(n, set())]
        # 연속 근무 금지. 후보가 없으면 완화.
        pool = [n for n in cands if assigned.get(i - 1) != n and assigned.get(i + 1) != n] or cands
        if not pool:
            continue
        h = is_heavy(d)

        def key(n):
            gap = min((abs(i - j) for j, m in assigned.items() if m == n), default=99)
            # 가용일 대비 비율 → 휴가가 많은 사람은 적게 배정
            return (count[n] / max(avail[n], 1), heavy[n] if h else 0, -gap, n)

        pick = min(pool, key=key)
        assigned[i] = pick
        count[pick] += 1
        heavy[pick] += h
    return {d.isoformat(): assigned.get(i) for i, d in enumerate(days)}
