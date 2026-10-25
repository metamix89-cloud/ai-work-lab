from datetime import datetime, timedelta

import pytest

from billing import assess_damages, compute_bill, fuel_fee, late_fee, late_minutes

DUE = datetime(2026, 10, 25, 12, 0)


@pytest.mark.parametrize("m,fee", [
    (-60, 0), (0, 0), (30, 0), (31, 10_000), (90, 10_000), (91, 20_000), (150, 20_000), (151, 30_000),
    (30 + 8 * 60, 80_000), (30 + 8 * 60 + 1, 80_000), (5000, 80_000)])
def test_late_fee(m, fee):
    assert late_fee(max(0, m)) == fee


def test_late_minutes_and_early():
    assert late_minutes(DUE, DUE + timedelta(minutes=31, seconds=59)) == 31
    assert late_minutes(DUE, DUE - timedelta(hours=3)) == 0


def test_fuel():
    assert fuel_fee(8, 5) == (3, 45_000)
    assert fuel_fee(5, 8) == (0, 0)
    assert fuel_fee(6, 6) == (0, 0)


def test_preexisting_free_and_new_charged():
    pickup = [{"id": 1, "part": "hood", "grade": "major"}]
    r = assess_damages(pickup, [{"part": "hood", "grade": "minor"}, {"part": "roof", "grade": "severe"}])
    assert [(d.pre_existing, d.charge) for d in r] == [(True, 0), (False, 500_000)]


def test_same_part_twice_only_one_preexisting():
    pickup = [{"id": 1, "part": "hood", "grade": "minor"}]
    r = assess_damages(pickup, [{"part": "hood", "grade": "minor"}, {"part": "hood", "grade": "minor"}])
    assert sorted(d.charge for d in r) == [0, 30_000]


def test_worsened_charges_difference():
    pickup = [{"id": 1, "part": "hood", "grade": "minor"}]
    r = assess_damages(pickup, [{"part": "hood", "grade": "major"}])
    assert r[0].charge == 120_000 and not r[0].pre_existing


def test_total():
    b = compute_bill(DUE, DUE + timedelta(minutes=100), 8, 6, [], [{"part": "roof", "grade": "minor"}])
    assert (b.late_fee, b.fuel_fee, b.damage_fee, b.total) == (20_000, 30_000, 30_000, 80_000)
