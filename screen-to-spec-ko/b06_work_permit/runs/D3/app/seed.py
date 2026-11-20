"""가상 데이터. 시각은 '지금' 기준 상대값이라 언제 실행해도 상태가 자연스럽다."""
import json
from datetime import timedelta

from . import clock, db
from .rules import CHECKLISTS, fmt, valid_until_for

USERS = [
    (1, "김철수", "작업반장", "뚝딱건설 골조팀"),
    (2, "이영호", "작업반장", "뚝딱건설 설비팀"),
    (3, "박민수", "작업반장", "한빛용접"),
    (4, "최안전", "안전담당", "뚝딱건설 안전팀"),
    (5, "정보건", "안전담당", "뚝딱건설 안전팀"),
    (6, "한소장", "현장책임자", "뚝딱건설 현장사무소"),
    (7, "오부소장", "현장책임자", "뚝딱건설 현장사무소"),
]
ZONES = [(1, "A구역 지상 골조"), (2, "B구역 지하 피트"), (3, "C구역 기계실"), (4, "D구역 옥상")]
DESC = {
    "고소": "외부 비계 작업", "화기": "배관 용접 작업", "밀폐": "맨홀 내부 점검·도장",
}


def seed():
    con = db.connect()
    now = clock.now()
    day0 = now.replace(hour=0, minute=0, second=0)
    ago = lambda **kw: max(day0, now - timedelta(**kw))  # 오늘 0시 이전으로 가지 않게

    con.executemany("INSERT INTO users VALUES(?,?,?,?)", USERS)
    con.executemany("INSERT INTO zones VALUES(?,?)", ZONES)

    def add(applicant, zone, wtype, status, created, **kw):
        checks = {k: True for k in CHECKLISTS[wtype]}
        cols = dict(applicant_id=applicant, zone_id=zone, work_type=wtype, description=DESC[wtype],
                    status=status, checks_json=json.dumps(checks), created_at=fmt(created))
        for k, v in kw.items():
            cols[k] = fmt(v) if hasattr(v, "year") else v
        q = ",".join(cols)
        con.execute(f"INSERT INTO permits({q}) VALUES({','.join('?' * len(cols))})", list(cols.values()))

    def approved(approved_at):
        return dict(reviewer_id=4, reviewed_at=approved_at - timedelta(minutes=10), approver_id=6,
                    approved_at=approved_at, valid_until=valid_until_for(approved_at))

    # 어제 승인된 허가 -> 이미 만료
    y = (now - timedelta(days=1)).replace(hour=9, minute=0, second=0)
    add(1, 1, "고소", "approved", y - timedelta(hours=1), **approved(y))
    # 작업 중 (A구역 고소)
    t = ago(hours=3)
    add(1, 1, "고소", "in_progress", t - timedelta(minutes=40), started_at=t + timedelta(minutes=5), **approved(t))
    # 승인 완료, 아직 시작 전 (B구역 화기)
    t = ago(minutes=30)
    add(3, 2, "화기", "approved", t - timedelta(hours=1), **approved(t))
    # 종료된 허가 (C구역 밀폐, 오늘 이른 시간) - B구역 화기와 구역이 달라 충돌 없음
    t = ago(hours=5)
    add(2, 3, "밀폐", "completed", t - timedelta(minutes=30), started_at=t + timedelta(minutes=10),
        ended_at=min(now, t + timedelta(hours=2)), **approved(t))
    # 안전 담당 검토 대기 / 책임자 승인 대기 / 반려
    add(2, 3, "화기", "requested", ago(minutes=20))
    add(2, 2, "밀폐", "reviewed", ago(minutes=50), reviewer_id=4, reviewed_at=ago(minutes=15),
        review_comment="가스 측정 기록 확인함")  # B구역: 화기 승인분과 충돌 -> 승인 시 막히는 시연용
    add(3, 4, "고소", "requested", ago(minutes=5))
    add(1, 4, "화기", "rejected", ago(hours=2), rejected_by=4, rejected_at=ago(hours=1, minutes=40),
        reject_reason="소화기 위치 재확인 후 재신청")
    con.close()
