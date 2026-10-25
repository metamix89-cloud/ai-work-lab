"""대여 시작 / 반납 계산 / 반납 확정 로직."""
import sqlite3
from datetime import datetime, timedelta

from . import billing
from .db import tx

TIME_FMT = "%Y-%m-%dT%H:%M"


class RuleError(Exception):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.msg, self.status = msg, status


def parse_time(s: str, label: str) -> datetime:
    try:
        return datetime.strptime(s[:16], TIME_FMT)
    except (ValueError, TypeError):
        raise RuleError(f"{label} 형식이 올바르지 않습니다.")


def now_str() -> str:
    return datetime.now().strftime(TIME_FMT)


def _check_damages(damages, label):
    seen = set()
    for d in damages:
        if d["part"] not in billing.PARTS:
            raise RuleError(f"알 수 없는 부위: {d['part']}")
        if d["grade"] not in billing.GRADES:
            raise RuleError("흠집 등급은 1~3이어야 합니다.")
        if d["part"] in seen:
            raise RuleError(f"{label}: '{d['part']}' 부위가 중복되었습니다. 부위당 1건만 입력하세요.")
        seen.add(d["part"])


def calculate(db: sqlite3.Connection, rental, data: dict) -> dict:
    """반납 입력으로 요금을 계산한다(저장하지 않음)."""
    if rental["status"] != "active":
        raise RuleError("이미 반납 처리된 대여입니다.", 409)
    veh = db.execute("SELECT * FROM vehicles WHERE id=?", (rental["vehicle_id"],)).fetchone()
    returned = parse_time(data["returned_at"], "반납 시각")
    if returned < parse_time(rental["start_at"], "대여 시각"):
        raise RuleError("반납 시각이 대여 시작보다 빠릅니다.")
    if returned > datetime.now() + timedelta(minutes=10):
        raise RuleError("반납 시각이 미래입니다.")
    if data["odometer"] < rental["start_odometer"]:
        raise RuleError(f"주행거리는 대여 시작 시({rental['start_odometer']:,} km)보다 작을 수 없습니다.")
    _check_damages(data["damages"], "반납 흠집")

    base = {r["part"]: r["grade"] for r in db.execute(
        "SELECT part, grade FROM rental_damage WHERE rental_id=? AND phase='pickup'", (rental["id"],))}
    lines, dmg_total = [], 0
    for d in data["damages"]:
        fee, status = billing.damage_line(base.get(d["part"], 0), d["grade"])
        dmg_total += fee
        lines.append({**d, "fee": fee, "status": status, "baseline_grade": base.get(d["part"], 0)})

    late_min, late = billing.late_fee(parse_time(rental["due_at"], "반납 예정"), returned, rental["daily_rate"])
    short, fuel = billing.fuel_fee(rental["start_fuel"], data["fuel"], veh["tank_liters"])
    return {
        "late_minutes": late_min, "late_fee": late,
        "fuel_short": short, "fuel_fee": fuel,
        "damage_fee": dmg_total, "damages": lines,
        "total": late + fuel + dmg_total,
        "distance": data["odometer"] - rental["start_odometer"],
    }


def start_rental(db, user_id, vehicle_id, due_at, start_fuel, extra_damages, start_at=None):
    """대여 시작. 차량의 기존 흠집 + 인도 시 추가 확인된 흠집을 '대여 전 흠집'으로 고정한다."""
    start_at = start_at or now_str()
    if parse_time(due_at, "반납 예정") <= parse_time(start_at, "대여 시각"):
        raise RuleError("반납 예정 시각은 대여 시작 이후여야 합니다.")
    _check_damages(extra_damages, "인도 시 흠집")
    with tx(db):
        veh = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
        cust = db.execute("SELECT id FROM users WHERE id=? AND role='customer'", (user_id,)).fetchone()
        if not veh or not cust:
            raise RuleError("고객 또는 차량을 찾을 수 없습니다.", 404)
        if db.execute("SELECT 1 FROM rentals WHERE vehicle_id=? AND status='active'", (vehicle_id,)).fetchone():
            raise RuleError("이미 대여 중인 차량입니다.", 409)
        for d in extra_damages:
            cur = db.execute("SELECT grade FROM vehicle_damage WHERE vehicle_id=? AND part=?",
                             (vehicle_id, d["part"])).fetchone()
            if not cur or cur["grade"] < d["grade"]:
                db.execute("INSERT OR REPLACE INTO vehicle_damage VALUES (?,?,?,?,?)",
                           (vehicle_id, d["part"], d["grade"], d.get("note", ""), d.get("photo")))
        cur = db.execute(
            "INSERT INTO rentals (user_id, vehicle_id, start_at, due_at, start_fuel, start_odometer, daily_rate, status)"
            " VALUES (?,?,?,?,?,?,?, 'active')",
            (user_id, vehicle_id, start_at, due_at, start_fuel, veh["odometer"], veh["daily_rate"]))
        rid = cur.lastrowid
        db.execute(
            "INSERT INTO rental_damage (rental_id, phase, part, grade, note, photo)"
            " SELECT ?, 'pickup', part, grade, note, photo FROM vehicle_damage WHERE vehicle_id=?", (rid, vehicle_id))
    return rid


def finish_return(db, rental_id, data, staff_id):
    """반납 확정: 요금 계산 → 청구서 저장 → 차량 상태 갱신을 한 트랜잭션으로 처리."""
    with tx(db):
        rental = db.execute("SELECT * FROM rentals WHERE id=?", (rental_id,)).fetchone()
        if not rental:
            raise RuleError("대여 건을 찾을 수 없습니다.", 404)
        res = calculate(db, rental, data)   # status 재검증 포함(BEGIN IMMEDIATE로 이중 반납 방지)
        db.execute("UPDATE rentals SET status='returned', returned_at=?, return_fuel=?, return_odometer=? WHERE id=?",
                   (data["returned_at"][:16], data["fuel"], data["odometer"], rental_id))
        for d in res["damages"]:
            db.execute(
                "INSERT INTO rental_damage (rental_id, phase, part, grade, note, photo, fee, status)"
                " VALUES (?, 'return', ?,?,?,?,?,?)",
                (rental_id, d["part"], d["grade"], d.get("note", ""), d.get("photo"), d["fee"], d["status"]))
            cur = db.execute("SELECT grade FROM vehicle_damage WHERE vehicle_id=? AND part=?",
                             (rental["vehicle_id"], d["part"])).fetchone()
            if not cur or cur["grade"] < d["grade"]:
                db.execute("INSERT OR REPLACE INTO vehicle_damage VALUES (?,?,?,?,?)",
                           (rental["vehicle_id"], d["part"], d["grade"], d.get("note", ""), d.get("photo")))
        db.execute("UPDATE vehicles SET odometer=? WHERE id=?", (data["odometer"], rental["vehicle_id"]))
        db.execute(
            "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?)",
            (rental_id, res["late_minutes"], res["late_fee"], res["fuel_short"], res["fuel_fee"],
             res["damage_fee"], res["total"], now_str(), staff_id))
    return res
