"""가상 데이터 (모두 허구의 이름/번호). 시각은 실행 시점 기준 상대값."""
import time

from main import SERVICES, assign_ticket, day_of, is_priority


def seed(c):
    now = int(time.time())
    today = day_of(now)
    m = 60
    n = [0]

    def add(name, svc, *, kind="walkin", reserved=None, code=None, arrived=None, status="waiting",
            win=None, called=None, started=None, finished=None):
        n[0] += 1
        phone = f"010{1000 + n[0]:04d}{2000 + n[0] * 7:04d}"
        pr = 1 if (reserved is not None and arrived is not None and is_priority(reserved, arrived)) else 0
        day = day_of(reserved) if status == "booked" else today
        vid = c.execute(
            """INSERT INTO visits(kind,name,phone,acct_last4,service,day,reserved_at,rcode,order_at,priority,
                                  status,win,called_at,started_at,finished_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (kind, name, phone, f"{(n[0] * 1373) % 10000:04d}", svc, day, reserved, code, arrived, pr,
             status, win, called, started, finished, now - 60 * m)).lastrowid
        if status != "booked":
            assign_ticket(c, vid, svc, today)

    # 처리 이력
    add("정하늘", "deposit", arrived=now - 50 * m, status="done", win=1, called=now - 45 * m,
        started=now - 44 * m, finished=now - 38 * m)
    add("오세훈", "loan", arrived=now - 30 * m, status="serving", win=3, called=now - 12 * m, started=now - 10 * m)
    add("윤도현", "deposit", arrived=now - 35 * m, status="hold", win=2, called=now - 10 * m)
    # 현재 호출 중 (창구 1)
    add("한지민", "deposit", arrived=now - 25 * m, status="called", win=1, called=now - 60)
    # 대기: 예금
    add("김민수", "deposit", arrived=now - 20 * m)
    add("이서연", "deposit", kind="reserved", reserved=now - 2 * m, arrived=now - 1 * m)        # 우선 (±10분 이내)
    add("박준호", "deposit", kind="reserved", reserved=now - 60 * m, arrived=now - 3 * m)       # 늦게 도착 → 일반
    # 대기: 대출
    add("최유진", "loan", arrived=now - 15 * m)
    add("강태우", "loan", kind="reserved", reserved=now + 3 * m, arrived=now - 4 * m)           # 우선
    # 대기: 외환
    add("조수빈", "fx", arrived=now - 8 * m)
    add("임하준", "fx", kind="reserved", reserved=now - 45 * m, arrived=now - 1 * m)            # 늦게 도착 → 일반
    # 아직 도착 접수 전 예약 (데모용 예약번호 고정)
    add("송가은", "loan", kind="reserved", reserved=now + 90 * m, code="DEMO01", status="booked")
    add("배서진", "deposit", kind="reserved", reserved=now - 25 * m, code="DEMO02", status="booked")  # 노쇼 집계
    add("남궁민", "fx", kind="reserved", reserved=now + 5 * m, code="DEMO03", status="booked")
    # 예약 중 phone 은 위 규칙으로 생성됨 (add 호출 순서 = n)


def demo_phone(order):
    """DEMO 예약의 전화번호 (시드 순서 12,13,14번째)."""
    return f"010{1000 + order:04d}{2000 + order * 7:04d}"
