"""현장 규칙(순수 로직). DB·HTTP 와 분리해서 단위 테스트가 쉽다."""
from datetime import datetime, timedelta

FMT = "%Y-%m-%d %H:%M:%S"

# 작업 종류별 필수 점검 항목(각 3개). key -> 화면에 보이는 문구
CHECKLISTS = {
    "고소": {
        "harness": "안전대 착용 및 고리 체결 확인",
        "scaffold": "작업발판·난간(추락방호망) 설치 확인",
        "below": "하부 출입통제 및 낙하물 방지 조치",
    },
    "화기": {
        "extinguisher": "소화기 비치(작업지점 5m 이내)",
        "combustible": "가연물 제거 및 불티 비산방지포 설치",
        "watcher": "화재감시자 배치",
    },
    "밀폐": {
        "gas": "산소·유해가스 농도 측정(산소 18% 이상)",
        "ventilation": "환기 장치 가동",
        "standby": "외부 감시인 배치 및 비상 구조장비 비치",
    },
}

VALID_HOURS = 8


def parse(s):
    return datetime.strptime(s, FMT) if s else None


def fmt(dt):
    return dt.strftime(FMT) if dt else None


def missing_checks(work_type, checks):
    """비어 있는(True 가 아닌) 필수 항목 key 목록. 종류가 잘못되면 None."""
    items = CHECKLISTS.get(work_type)
    if items is None:
        return None
    checks = checks or {}
    return [k for k in items if checks.get(k) is not True]


def valid_until_for(approved_at):
    """승인 시각 + 8시간, 단 그날 23:59 를 넘기지 않는다."""
    end_of_day = approved_at.replace(hour=23, minute=59, second=0)
    return min(approved_at + timedelta(hours=VALID_HOURS), end_of_day)


def effective_status(permit, now):
    """저장 상태 + 시각 => 화면/판단용 상태. 승인 후 유효시간이 지나면 '만료'."""
    st = permit["status"]
    if st == "approved" and now > parse(permit["valid_until"]):
        return "expired"
    return st


def occupied_window(permit, now):
    """승인된 허가가 현장을 점유하는 시간 구간. 점유하지 않으면 None."""
    st = permit["status"]
    if st not in ("approved", "in_progress", "completed") or not permit["approved_at"]:
        return None
    start = parse(permit["approved_at"])
    if st == "completed":
        end = parse(permit["ended_at"])
    elif st == "in_progress":
        end = datetime.max  # 종료 처리 전까지는 (유효시간이 지났어도) 계속 점유
    else:
        end = parse(permit["valid_until"])
    return (start, end)


def find_conflict(candidate, others, now):
    """candidate 를 now 에 승인한다고 할 때 부딪히는 허가(화기<->밀폐, 같은 구역, 시간 겹침)."""
    pair = {"화기", "밀폐"}
    if candidate["work_type"] not in pair:
        return None
    c_start, c_end = now, valid_until_for(now)
    for o in others:
        if o["id"] == candidate["id"] or o["zone_id"] != candidate["zone_id"]:
            continue
        if o["work_type"] not in pair or o["work_type"] == candidate["work_type"]:
            continue
        w = occupied_window(o, now)
        if w and w[0] < c_end and c_start < w[1]:
            return o
    return None
