"""반납 확정: 검증 → 요금 계산 → 한 트랜잭션으로 기록."""
import sqlite3
from datetime import datetime

from . import billing
from .billing import GRADE_LABEL, GRADE_RANK, KST

PARTS = {
    "front_bumper": "앞 범퍼", "rear_bumper": "뒤 범퍼", "hood": "보닛", "roof": "루프",
    "trunk": "트렁크", "windshield": "앞 유리", "rear_window": "뒷 유리",
    "left_front_door": "좌 앞문", "left_rear_door": "좌 뒷문",
    "right_front_door": "우 앞문", "right_rear_door": "우 뒷문",
    "left_fender": "좌 휀더", "right_fender": "우 휀더",
    "wheel": "휠/타이어", "interior": "실내",
}


class ReturnError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def now_kst() -> datetime:
    return datetime.now(KST)


def parse_kst(value: str) -> datetime:
    """시간대 없는 값은 KST로 간주. 초 이하는 버린다(분 단위 업무)."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ReturnError("반납 시각 형식이 올바르지 않습니다.")
    dt = dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)
    return dt.replace(second=0, microsecond=0)


def finalize_return(conn: sqlite3.Connection, rental_id: int, staff_id: int, returned_at: datetime,
                    end_fuel: int, end_odometer: int, damages: list[dict]) -> dict:
    """damages: [{part, grade, photo(저장된 파일명), note, pre_existing_id|None}].
    '대여 전 흠집' 여부는 클라이언트 플래그가 아니라 대여 시점에 기록된 흠집과의 연결로만 판정한다."""
    if not 0 <= end_fuel <= billing.FUEL_MAX:
        raise ReturnError("연료는 0~8칸이어야 합니다.")
    if end_odometer < 0:
        raise ReturnError("주행거리가 올바르지 않습니다.")
    for d in damages:
        if d["part"] not in PARTS:
            raise ReturnError(f"알 수 없는 부위: {d['part']}")
        if d["grade"] not in billing.DAMAGE_FEES:
            raise ReturnError(f"알 수 없는 등급: {d['grade']}")
        if not d.get("photo"):
            raise ReturnError("사진이 없는 흠집은 접수할 수 없습니다.")

    conn.execute("BEGIN IMMEDIATE")  # 동시 이중 반납 방지
    try:
        r = conn.execute("SELECT * FROM rentals WHERE id=?", (rental_id,)).fetchone()
        if r is None:
            raise ReturnError("대여 건을 찾을 수 없습니다.", 404)
        if r["status"] != "active":
            raise ReturnError("이미 반납 처리된 건입니다.", 409)
        started = datetime.fromisoformat(r["started_at"])
        due = datetime.fromisoformat(r["due_at"])
        if returned_at < started:
            raise ReturnError("반납 시각이 대여 시작보다 빠릅니다.")
        if end_odometer < r["start_odometer"]:
            raise ReturnError("반납 주행거리가 대여 시작 주행거리보다 작습니다.")

        pickup = {row["id"]: row for row in conn.execute(
            "SELECT * FROM damages WHERE rental_id=? AND phase='pickup'", (rental_id,))}
        used: set[int] = set()
        lines: list[tuple] = []  # (kind, description, amount, damage_index)

        late_min, late = billing.late_fee(due, returned_at)
        if late:
            lines.append(("late", f"지연 반납 {late_min}분 (유예 30분 초과)", late, None))
        else:
            lines.append(("late", f"지연 없음 ({late_min}분, 유예 30분 이내)" if late_min else "지연 없음", 0, None))
        short, fuel = billing.fuel_fee(r["start_fuel"], end_fuel)
        lines.append(("fuel", f"연료 {short}칸 부족 (대여 {r['start_fuel']}칸 → 반납 {end_fuel}칸)" if short
                      else f"연료 부족 없음 (대여 {r['start_fuel']}칸 → 반납 {end_fuel}칸)", fuel, None))

        rows = []
        for i, d in enumerate(damages):
            pid = d.get("pre_existing_id")
            if pid is not None:
                p = pickup.get(pid)
                if p is None:
                    raise ReturnError("연결한 대여 전 흠집이 이 대여 건에 없습니다.")
                if pid in used:
                    raise ReturnError("같은 대여 전 흠집을 두 번 연결할 수 없습니다.")
                if p["part"] != d["part"]:
                    raise ReturnError("대여 전 흠집과 부위가 다릅니다.")
                if GRADE_RANK[d["grade"]] > GRADE_RANK[p["grade"]]:
                    raise ReturnError(
                        f"{PARTS[d['part']]}: 대여 전({GRADE_LABEL[p['grade']]})보다 악화되었습니다. "
                        "새 흠집으로 등록하세요.")
                used.add(pid)
            pre = pid is not None
            fee = billing.damage_fee(d["grade"], pre)
            desc = (f"{PARTS[d['part']]} {GRADE_LABEL[d['grade']]} 흠집 — 대여 전부터 있던 흠집(청구 제외)" if pre
                    else f"{PARTS[d['part']]} {GRADE_LABEL[d['grade']]} 흠집")
            rows.append((d, pid, int(pre), fee))
            lines.append(("damage", desc, fee, i))

        damage_ids: dict[int, int] = {}
        for i, (d, pid, pre, fee) in enumerate(rows):
            cur = conn.execute(
                "INSERT INTO damages(rental_id,phase,part,grade,photo,note,pre_existing_id,pre_existing,fee)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (rental_id, "return", d["part"], d["grade"], d["photo"], d.get("note", "")[:200], pid, pre, fee))
            damage_ids[i] = cur.lastrowid
        total = 0
        for kind, desc, amount, idx in lines:
            conn.execute("INSERT INTO charges(rental_id,kind,description,amount,damage_id) VALUES(?,?,?,?,?)",
                         (rental_id, kind, desc, amount, damage_ids.get(idx) if idx is not None else None))
            total += amount
        conn.execute(
            "UPDATE rentals SET status='returned', returned_at=?, end_fuel=?, end_odometer=?,"
            " inspected_by=?, total_charge=? WHERE id=?",
            (returned_at.isoformat(), end_fuel, end_odometer, staff_id, total, rental_id))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return {"rental_id": rental_id, "total_charge": total}
