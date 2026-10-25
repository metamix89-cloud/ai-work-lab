from datetime import datetime, timedelta

import pytest

from app.billing import KST, damage_fee, fuel_fee, late_fee

DUE = datetime(2026, 10, 25, 12, 0, tzinfo=KST)


@pytest.mark.parametrize("late_min,expected", [
    (-120, 0),      # 일찍 반납: 환불 없음
    (0, 0), (30, 0),            # 유예
    (31, 10_000), (90, 10_000),  # 첫 블록
    (91, 20_000), (150, 20_000),
    (151, 30_000),
    (30 + 60 * 8, 80_000),      # 8블록 = 상한
    (30 + 60 * 8 + 1, 80_000),  # 9블록째도 상한
    (60 * 24 * 5, 80_000),
])
def test_late_fee(late_min, expected):
    assert late_fee(DUE, DUE + timedelta(minutes=late_min))[1] == expected


def test_late_seconds_truncate_to_minutes():
    assert late_fee(DUE, DUE + timedelta(minutes=30, seconds=59))[1] == 0


@pytest.mark.parametrize("start,end,fee", [(8, 8, 0), (8, 5, 45_000), (3, 0, 45_000), (4, 7, 0), (0, 8, 0)])
def test_fuel_fee(start, end, fee):
    assert fuel_fee(start, end)[1] == fee


def test_damage_fee():
    assert [damage_fee(g, False) for g in ("minor", "major", "severe")] == [30_000, 150_000, 500_000]
    assert damage_fee("severe", True) == 0
