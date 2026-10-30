"""두둑은행 지점 방문 예약 · 대기 현황판 (FastAPI + SQLite)."""
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DUDUK_DB", str(BASE / "duduk.db"))
PINS = {
    "staff": os.environ.get("STAFF_PIN", "1111"),
    "manager": os.environ.get("MANAGER_PIN", "9999"),
}

SERVICES = ("예금", "대출", "외환")
PREFIX = {"예금": "D", "대출": "L", "외환": "F"}
# 창구별 처리 업무
COUNTERS = {1: ["예금"], 2: ["예금"], 3: ["대출"], 4: ["외환"], 5: ["예금", "대출", "외환"]}
SLOT_TIMES = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)]  # 09:00 ~ 15:30
SLOT_CAPACITY = 4
NOSHOW_GRACE_MIN = 15      # 예약 시각 + 15분까지 도착 확인 없으면 노쇼
CHECKIN_EARLY_MIN = 30     # 예약 시각 30분 전부터 도착 확인 가능
MAX_ADVANCE_DAYS = 7

FMT_DT = "%Y-%m-%d %H:%M:%S"
FMT_MIN = "%Y-%m-%d %H:%M"

app = FastAPI(title="두둑은행 방문 예약 · 대기 현황판")


# ---------------------------------------------------------------- DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_no TEXT NOT NULL,
  day TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('reservation','walkin')),
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  account TEXT NOT NULL,
  service TEXT NOT NULL,
  reserved_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('reserved','waiting','called','done','noshow','cancelled')),
  counter INTEGER,
  created_at TEXT NOT NULL,
  arrived_at TEXT,
  called_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tickets_day_status ON tickets(day, status);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db(write=False):
    conn = connect()
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.execute("COMMIT")
    except BaseException:
        if write:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def now():
    return datetime.now().replace(microsecond=0)


def today():
    return date.today().isoformat()


def sweep(conn):
    """도착 확인이 없는 지난 예약을 노쇼로 확정."""
    cutoff = (now() - timedelta(minutes=NOSHOW_GRACE_MIN)).strftime(FMT_MIN)
    conn.execute(
        "UPDATE tickets SET status='noshow', finished_at=? WHERE status='reserved' AND reserved_at < ?",
        (now().strftime(FMT_DT), cutoff),
    )


def next_ticket_no(conn, day, kind, service):
    prefix = ("R" if kind == "reservation" else "") + PREFIX[service]
    n = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE day=? AND ticket_no LIKE ?", (day, prefix + "%")
    ).fetchone()[0]
    return f"{prefix}{n + 1:03d}"


def insert_ticket(conn, *, day, kind, name, phone, account, service, status,
                  reserved_at=None, counter=None, created_at=None,
                  arrived_at=None, called_at=None, finished_at=None):
    no = next_ticket_no(conn, day, kind, service)
    created_at = created_at or now().strftime(FMT_DT)
    cur = conn.execute(
        """INSERT INTO tickets (ticket_no, day, kind, name, phone, account, service, reserved_at,
           status, counter, created_at, arrived_at, called_at, finished_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (no, day, kind, name, phone, account, service, reserved_at, status, counter,
         created_at, arrived_at, called_at, finished_at),
    )
    return cur.lastrowid, no


# ---------------------------------------------------------------- 개인정보 마스킹
def mask_name(n):
    if len(n) <= 1:
        return n
    if len(n) == 2:
        return n[0] + "*"
    return n[0] + "*" * (len(n) - 2) + n[-1]


def mask_phone(p):
    return re.sub(r"^(\d{3})-(\d{3,4})-(\d{4})$", r"\1-****-\3", p)


def mask_account(a):
    return re.sub(r"\d(?=[\d-]*\d{4}$)", "*", a)


def view(t, full=False):
    """티켓 -> dict. full=False 이면 개인정보 마스킹."""
    d = {
        "id": t["id"], "ticket_no": t["ticket_no"], "kind": t["kind"], "service": t["service"],
        "status": t["status"], "counter": t["counter"], "reserved_at": t["reserved_at"],
        "arrived_at": t["arrived_at"], "called_at": t["called_at"], "finished_at": t["finished_at"],
        "day": t["day"],
    }
    if full:
        d.update(name=t["name"], phone=t["phone"], account=t["account"])
    else:
        d.update(name=mask_name(t["name"]), phone=mask_phone(t["phone"]), account=mask_account(t["account"]))
    return d


def waiting_sorted(conn, services=None):
    """대기열 순서: 예약 고객 우선(예약 시각순) → 현장 고객(도착순)."""
    rows = conn.execute("SELECT * FROM tickets WHERE day=? AND status='waiting'", (today(),)).fetchall()
    if services is not None:
        rows = [r for r in rows if r["service"] in services]
    return sorted(
        rows,
        key=lambda r: (0, r["reserved_at"], r["id"]) if r["kind"] == "reservation"
        else (1, r["arrived_at"] or r["created_at"], r["id"]),
    )


# ---------------------------------------------------------------- 인증
SESSIONS: dict[str, tuple[str, float]] = {}
SESSION_TTL = 12 * 3600
FAILS: dict[str, tuple[int, float]] = {}


def require(role):
    def dep(x_token: str = Header(default="")):
        s = SESSIONS.get(x_token)
        if not s or s[1] < time.time():
            raise HTTPException(401, "로그인이 필요합니다")
        if role == "manager" and s[0] != "manager":
            raise HTTPException(403, "지점장 권한이 필요합니다")
        return s[0]
    return dep


class LoginIn(BaseModel):
    role: Literal["staff", "manager"]
    pin: str = Field(max_length=20)


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    cnt, until = FAILS.get(ip, (0, 0))
    if cnt >= 5 and until > time.time():
        raise HTTPException(429, "시도 횟수 초과. 잠시 후 다시 시도하세요")
    if not secrets.compare_digest(body.pin, PINS[body.role]):
        FAILS[ip] = (cnt + 1, time.time() + 60)
        raise HTTPException(401, "PIN이 올바르지 않습니다")
    FAILS.pop(ip, None)
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = (body.role, time.time() + SESSION_TTL)
    return {"token": token, "role": body.role}


# ---------------------------------------------------------------- 고객 입력
def normalize_phone(v):
    digits = re.sub(r"\D", "", v)
    if not re.fullmatch(r"01\d{8,9}", digits):
        raise ValueError("휴대전화 번호를 확인해 주세요 (예: 010-0000-4878)")
    return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    phone: str
    account: str
    service: Literal["예금", "대출", "외환"]

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or re.search(r"[<>&\"'\\]", v):
            raise ValueError("이름을 확인해 주세요")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)

    @field_validator("account")
    @classmethod
    def _account(cls, v):
        v = v.strip()
        digits = re.sub(r"\D", "", v)
        if not re.fullmatch(r"[\d-]+", v) or not 10 <= len(digits) <= 16:
            raise ValueError("계좌번호는 숫자 10~16자리로 입력해 주세요")
        return v


class ReservationIn(CustomerIn):
    date: date
    time: str

    @field_validator("time")
    @classmethod
    def _time(cls, v):
        if v not in SLOT_TIMES:
            raise ValueError("예약 시간을 확인해 주세요")
        return v


def position_of(conn, ticket_id):
    q = waiting_sorted(conn)
    for i, r in enumerate(q):
        if r["id"] == ticket_id:
            return i + 1, sum(1 for x in q[:i] if x["service"] == r["service"])
    return None, None


@app.get("/api/slots")
def slots(date: date):
    n = now()
    today_d = n.date()
    if date < today_d or date > today_d + timedelta(days=MAX_ADVANCE_DAYS):
        return {"date": date.isoformat(), "closed": True, "reason": "예약 가능 기간이 아닙니다", "slots": []}
    if date.weekday() >= 5:
        return {"date": date.isoformat(), "closed": True, "reason": "주말에는 예약할 수 없습니다", "slots": []}
    with db() as conn:
        used = {
            r["reserved_at"][11:16]: r["c"]
            for r in conn.execute(
                "SELECT reserved_at, COUNT(*) c FROM tickets WHERE kind='reservation' AND day=? "
                "AND status!='cancelled' GROUP BY reserved_at", (date.isoformat(),))
        }
    out = []
    for t in SLOT_TIMES:
        start = datetime.strptime(f"{date.isoformat()} {t}", FMT_MIN)
        past = start <= n
        out.append({"time": t, "remaining": 0 if past else max(0, SLOT_CAPACITY - used.get(t, 0))})
    return {"date": date.isoformat(), "closed": False, "slots": out}


def active_dup(conn, day, phone):
    return conn.execute(
        "SELECT ticket_no FROM tickets WHERE day=? AND phone=? AND status IN ('reserved','waiting','called')",
        (day, phone)).fetchone()


@app.post("/api/reservations")
def reserve(b: ReservationIn):
    start = datetime.strptime(f"{b.date.isoformat()} {b.time}", FMT_MIN)
    if start <= now():
        raise HTTPException(422, "이미 지난 시간입니다")
    if b.date > now().date() + timedelta(days=MAX_ADVANCE_DAYS) or b.date.weekday() >= 5:
        raise HTTPException(422, "예약할 수 없는 날짜입니다")
    with db(write=True) as conn:
        dup = active_dup(conn, b.date.isoformat(), b.phone)
        if dup:
            raise HTTPException(409, f"같은 날 이미 접수된 건이 있습니다 ({dup['ticket_no']})")
        used = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE kind='reservation' AND reserved_at=? AND status!='cancelled'",
            (start.strftime(FMT_MIN),)).fetchone()[0]
        if used >= SLOT_CAPACITY:
            raise HTTPException(409, "해당 시간은 예약이 마감되었습니다")
        _, no = insert_ticket(conn, day=b.date.isoformat(), kind="reservation", name=b.name,
                              phone=b.phone, account=b.account, service=b.service,
                              status="reserved", reserved_at=start.strftime(FMT_MIN))
    return {"ticket_no": no, "date": b.date.isoformat(), "time": b.time, "service": b.service,
            "message": f"예약 완료. 방문 시 '예약 도착 확인'을 하시면 우선 호출됩니다 "
                       f"(예약 시각 +{NOSHOW_GRACE_MIN}분까지)."}


@app.post("/api/tickets")
def take_ticket(b: CustomerIn):
    with db(write=True) as conn:
        sweep(conn)
        dup = active_dup(conn, today(), b.phone)
        if dup:
            raise HTTPException(409, f"이미 접수된 번호표가 있습니다 ({dup['ticket_no']})")
        tid, no = insert_ticket(conn, day=today(), kind="walkin", name=b.name, phone=b.phone,
                                account=b.account, service=b.service, status="waiting",
                                arrived_at=now().strftime(FMT_DT))
        pos, ahead = position_of(conn, tid)
    return {"ticket_no": no, "service": b.service, "position": pos, "ahead_same_service": ahead}


class CheckinIn(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)


@app.post("/api/checkin")
def checkin(b: CheckinIn):
    n = now()
    with db(write=True) as conn:
        sweep(conn)
        rows = conn.execute(
            "SELECT * FROM tickets WHERE day=? AND phone=? AND kind='reservation' AND status='reserved' "
            "ORDER BY reserved_at", (today(), b.phone)).fetchall()
        if not rows:
            raise HTTPException(404, "오늘 예약 내역이 없거나 노쇼 처리되었습니다. 번호표를 새로 뽑아 주세요")
        t = rows[0]
        start = datetime.strptime(t["reserved_at"], FMT_MIN)
        if n < start - timedelta(minutes=CHECKIN_EARLY_MIN):
            raise HTTPException(
                409, f"예약 시각({t['reserved_at'][11:]}) {CHECKIN_EARLY_MIN}분 전부터 도착 확인이 가능합니다")
        conn.execute("UPDATE tickets SET status='waiting', arrived_at=? WHERE id=?",
                     (n.strftime(FMT_DT), t["id"]))
        pos, ahead = position_of(conn, t["id"])
    return {"ticket_no": t["ticket_no"], "service": t["service"], "reserved_at": t["reserved_at"],
            "position": pos, "ahead_same_service": ahead}


# ---------------------------------------------------------------- 대기 화면 (공개, 개인정보 없음)
@app.get("/api/board")
def board():
    with db(write=True) as conn:
        sweep(conn)
        called = {
            r["counter"]: r for r in conn.execute(
                "SELECT * FROM tickets WHERE day=? AND status='called'", (today(),))
        }
        q = waiting_sorted(conn)
    counters = []
    for n, svcs in COUNTERS.items():
        t = called.get(n)
        counters.append({
            "counter": n, "services": svcs,
            "ticket_no": t["ticket_no"] if t else None,
            "service": t["service"] if t else None,
            "called_at": t["called_at"] if t else None,
            "fresh": bool(t and (now() - datetime.strptime(t["called_at"], FMT_DT)).total_seconds() < 30),
        })
    return {
        "now": now().strftime(FMT_DT),
        "counters": counters,
        "waiting": [{"order": i + 1, "ticket_no": r["ticket_no"], "service": r["service"],
                     "priority": r["kind"] == "reservation"} for i, r in enumerate(q[:14])],
        "waiting_total": len(q),
        "by_service": {s: sum(1 for r in q if r["service"] == s) for s in SERVICES},
    }


# ---------------------------------------------------------------- 창구 직원
def check_counter(n):
    if n not in COUNTERS:
        raise HTTPException(404, "없는 창구입니다")


def current_called(conn, n):
    return conn.execute("SELECT * FROM tickets WHERE day=? AND status='called' AND counter=?",
                        (today(), n)).fetchone()


def counter_state(conn, n):
    cur = current_called(conn, n)
    q = waiting_sorted(conn, COUNTERS[n])
    return {
        "counter": n, "services": COUNTERS[n],
        "current": view(cur, full=True) if cur else None,  # 호출한 고객만 상세(전체) 공개
        "queue": [dict(view(r), order=i + 1, priority=r["kind"] == "reservation") for i, r in enumerate(q[:15])],
        "queue_total": len(q),
    }


@app.get("/api/counters")
def counters_list(_=Depends(require("staff"))):
    return [{"counter": n, "services": s} for n, s in COUNTERS.items()]


@app.get("/api/counter/{n}")
def counter_get(n: int, _=Depends(require("staff"))):
    check_counter(n)
    with db(write=True) as conn:
        sweep(conn)
        return counter_state(conn, n)


@app.post("/api/counter/{n}/next")
def counter_next(n: int, _=Depends(require("staff"))):
    check_counter(n)
    with db(write=True) as conn:
        sweep(conn)
        if current_called(conn, n):
            raise HTTPException(409, "현재 호출한 고객의 처리를 먼저 완료하세요")
        q = waiting_sorted(conn, COUNTERS[n])
        if not q:
            raise HTTPException(404, "대기 중인 고객이 없습니다")
        conn.execute("UPDATE tickets SET status='called', counter=?, called_at=? WHERE id=?",
                     (n, now().strftime(FMT_DT), q[0]["id"]))
        return counter_state(conn, n)


def _finish(n, status):
    with db(write=True) as conn:
        cur = current_called(conn, n)
        if not cur:
            raise HTTPException(409, "호출한 고객이 없습니다")
        conn.execute("UPDATE tickets SET status=?, finished_at=? WHERE id=?",
                     (status, now().strftime(FMT_DT), cur["id"]))
        return counter_state(conn, n)


@app.post("/api/counter/{n}/complete")
def counter_complete(n: int, _=Depends(require("staff"))):
    check_counter(n)
    return _finish(n, "done")


@app.post("/api/counter/{n}/noshow")
def counter_noshow(n: int, _=Depends(require("staff"))):
    check_counter(n)
    return _finish(n, "noshow")


@app.post("/api/counter/{n}/recall")
def counter_recall(n: int, _=Depends(require("staff"))):
    check_counter(n)
    with db(write=True) as conn:
        cur = current_called(conn, n)
        if not cur:
            raise HTTPException(409, "호출한 고객이 없습니다")
        conn.execute("UPDATE tickets SET called_at=? WHERE id=?", (now().strftime(FMT_DT), cur["id"]))
        return counter_state(conn, n)


# ---------------------------------------------------------------- 지점장
@app.get("/api/manager/summary")
def manager_summary(_=Depends(require("manager"))):
    d0 = today()
    week_ago = (date.today() - timedelta(days=6)).isoformat()
    with db(write=True) as conn:
        sweep(conn)
        todays = conn.execute("SELECT * FROM tickets WHERE day=?", (d0,)).fetchall()
        week = conn.execute("SELECT * FROM tickets WHERE day>=? AND day<=?", (week_ago, d0)).fetchall()
        q = waiting_sorted(conn)
        counters = []
        for n, svcs in COUNTERS.items():
            cur = current_called(conn, n)
            counters.append({"counter": n, "services": svcs,
                             "ticket_no": cur["ticket_no"] if cur else None,
                             "called_at": cur["called_at"] if cur else None})

    def cnt(rows, st):
        return sum(1 for r in rows if r["status"] == st)

    waits = [(datetime.strptime(r["called_at"], FMT_DT) - datetime.strptime(r["arrived_at"], FMT_DT)).total_seconds() / 60
             for r in todays if r["called_at"] and r["arrived_at"]]
    n = now()
    longest = max(((n - datetime.strptime(r["arrived_at"], FMT_DT)).total_seconds() / 60 for r in q), default=0)

    # 노쇼율 = 노쇼 예약 / (결과가 확정된 예약: 이용 + 노쇼)  — 아직 예정/취소는 제외
    def noshow_rate(rows):
        res = [r for r in rows if r["kind"] == "reservation" and r["status"] in ("done", "called", "waiting", "noshow")]
        ns = [r for r in res if r["status"] == "noshow"]
        return {"noshow": len(ns), "total": len(res), "rate": round(100 * len(ns) / len(res), 1) if res else 0}

    daily = []
    for i in range(6, -1, -1):
        dd = (date.today() - timedelta(days=i)).isoformat()
        rows = [r for r in week if r["day"] == dd]
        daily.append({"day": dd, "tickets": len(rows), "noshow": cnt(rows, "noshow"),
                      "reservation_noshow": noshow_rate(rows)["noshow"]})

    noshows = sorted((r for r in week if r["status"] == "noshow"),
                     key=lambda r: (r["day"], r["reserved_at"] or r["created_at"]), reverse=True)
    return {
        "now": n.strftime(FMT_DT),
        "today": {
            "total": len(todays), "waiting": cnt(todays, "waiting"), "called": cnt(todays, "called"),
            "done": cnt(todays, "done"), "reserved_pending": cnt(todays, "reserved"),
            "noshow": cnt(todays, "noshow"),
            "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else 0,
            "longest_wait_min": round(longest, 1),
        },
        "waiting_by_service": {s: sum(1 for r in q if r["service"] == s) for s in SERVICES},
        "noshow_today": noshow_rate(todays),
        "noshow_week": noshow_rate(week),
        "daily": daily,
        "counters": counters,
        "waiting": [dict(view(r), order=i + 1, priority=r["kind"] == "reservation") for i, r in enumerate(q[:30])],
        "noshows": [dict(view(r), stage="미도착" if not r["arrived_at"] else "호출 불응") for r in noshows[:40]],
    }


# ---------------------------------------------------------------- 가상 데이터
def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]:
        return
    n = now()
    d0 = n.date()

    def ts(minutes_ago):
        return (n - timedelta(minutes=minutes_ago)).strftime(FMT_DT)

    def slot(minutes_from_now):
        t = n + timedelta(minutes=minutes_from_now)
        t = t.replace(minute=0 if t.minute < 30 else 30, second=0, microsecond=0)
        return t.strftime(FMT_MIN)

    people = [
        ("김서준", "010-0000-4857", "1002-345-678901"), ("이하윤", "010-0000-1944", "110-234-567890"),
        ("박지호", "010-0000-2182", "3333-12-3456789"), ("최서연", "010-0000-7357", "1002-456-789012"),
        ("정도윤", "010-0000-8429", "110-345-678901"), ("강지우", "010-0000-3438", "3333-23-4567890"),
        ("조예린", "010-0000-4568", "1002-567-890123"), ("윤민재", "010-0000-9134", "110-456-789012"),
        ("장수아", "010-0000-3083", "3333-34-5678901"), ("임현우", "010-0000-8458", "1002-678-901234"),
        ("한소율", "010-0000-6723", "110-567-890123"), ("오건우", "010-0000-8225", "3333-45-6789012"),
        ("서지안", "010-0000-7816", "1002-789-012345"), ("신유진", "010-0000-6262", "110-678-901234"),
        ("권태민", "010-0000-4292", "3333-56-7890123"), ("황나은", "010-0000-2218", "1002-890-123456"),
        ("안재현", "010-0000-7358", "110-789-012345"), ("송다은", "010-0000-6937", "3333-67-8901234"),
        ("류시우", "010-0000-8063", "1002-901-234567"), ("문채원", "010-0000-8538", "110-890-123456"),
        ("배준서", "010-0000-3061", "3333-78-9012345"), ("노지민", "010-0000-9294", "1002-012-345678"),
        ("홍가은", "010-0000-8708", "110-901-234567"), ("남주원", "010-0000-3079", "3333-89-0123456"),
        ("구하린", "010-0000-5202", "1002-123-456789"), ("백승민", "010-0000-1956", "110-012-345678"),
        ("전소희", "010-0000-7902", "3333-90-1234567"), ("유도현", "010-0000-4173", "1002-234-567890"),
    ]
    it = iter(people)

    def P():
        return next(it)

    # 지난 6일 이력 (노쇼율 추세용)
    hist_ns = {1: 1, 2: 0, 3: 2, 4: 1, 5: 1, 6: 0}
    for back in range(6, 0, -1):
        dd = d0 - timedelta(days=back)
        if dd.weekday() >= 5:
            continue
        for k in range(8):
            nm, ph, ac = people[(back * 3 + k) % len(people)]
            sv = SERVICES[(k + back) % 3]
            res = k < 4
            hh = f"{9 + k * 1:02d}:{'00' if k % 2 == 0 else '30'}"
            st = "noshow" if res and k < hist_ns.get(back, 0) else "done"
            insert_ticket(conn, day=dd.isoformat(), kind="reservation" if res else "walkin", name=nm,
                          phone=ph, account=ac, service=sv, status=st,
                          reserved_at=f"{dd.isoformat()} {hh}" if res else None,
                          created_at=f"{dd.isoformat()} {hh}:00",
                          arrived_at=None if st == "noshow" else f"{dd.isoformat()} {hh}:00",
                          called_at=None if st == "noshow" else f"{dd.isoformat()} {hh}:00",
                          finished_at=f"{dd.isoformat()} {hh}:00")

    day = d0.isoformat()
    # 오늘 처리 완료
    for (mins_ago, kind, sv, wait) in [(95, "walkin", "예금", 6), (80, "reservation", "대출", 3),
                                      (70, "walkin", "예금", 9), (55, "walkin", "외환", 7),
                                      (45, "reservation", "예금", 2), (30, "walkin", "대출", 11)]:
        nm, ph, ac = P()
        arrived = ts(mins_ago + wait)
        insert_ticket(conn, day=day, kind=kind, name=nm, phone=ph, account=ac, service=sv, status="done",
                      counter={"예금": 1, "대출": 3, "외환": 4}[sv], reserved_at=slot(-mins_ago - wait) if kind == "reservation" else None,
                      created_at=arrived, arrived_at=arrived, called_at=ts(mins_ago), finished_at=ts(mins_ago - 8))
    # 오늘 노쇼 (예약 후 미도착 / 호출 불응)
    nm, ph, ac = P()
    insert_ticket(conn, day=day, kind="reservation", name=nm, phone=ph, account=ac, service="대출",
                  status="noshow", reserved_at=slot(-120), created_at=ts(2000), finished_at=ts(100))
    nm, ph, ac = P()
    arrived = ts(60)
    insert_ticket(conn, day=day, kind="reservation", name=nm, phone=ph, account=ac, service="외환",
                  status="noshow", counter=4, reserved_at=slot(-70), created_at=ts(2000),
                  arrived_at=arrived, called_at=ts(50), finished_at=ts(48))
    # 지금 호출 중 (창구 1, 3)
    nm, ph, ac = P()
    insert_ticket(conn, day=day, kind="reservation", name=nm, phone=ph, account=ac, service="예금",
                  status="called", counter=1, reserved_at=slot(-20), created_at=ts(1500),
                  arrived_at=ts(14), called_at=ts(1))
    nm, ph, ac = P()
    insert_ticket(conn, day=day, kind="walkin", name=nm, phone=ph, account=ac, service="대출",
                  status="called", counter=3, created_at=ts(18), arrived_at=ts(18), called_at=ts(4))
    # 대기 중: 현장 고객이 먼저 도착했어도 예약 고객이 앞섬
    for mins_ago, kind, sv in [(16, "walkin", "예금"), (13, "walkin", "외환"), (11, "reservation", "예금"),
                               (9, "walkin", "대출"), (7, "walkin", "예금"), (5, "reservation", "대출"),
                               (3, "walkin", "외환")]:
        nm, ph, ac = P()
        insert_ticket(conn, day=day, kind=kind, name=nm, phone=ph, account=ac, service=sv, status="waiting",
                      reserved_at=slot(-mins_ago - 5) if kind == "reservation" else None,
                      created_at=ts(mins_ago if kind == "walkin" else 1400),
                      arrived_at=ts(mins_ago))
    # 아직 안 온 예약 (오늘 이후 + 내일)
    for mins, sv in [(20, "예금"), (45, "외환"), (90, "대출")]:
        nm, ph, ac = P()
        insert_ticket(conn, day=day, kind="reservation", name=nm, phone=ph, account=ac, service=sv,
                      status="reserved", reserved_at=slot(mins), created_at=ts(3000))
    nxt = d0 + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    for hh, sv in [("10:00", "대출"), ("14:30", "예금")]:
        nm, ph, ac = P()
        insert_ticket(conn, day=nxt.isoformat(), kind="reservation", name=nm, phone=ph, account=ac,
                      service=sv, status="reserved", reserved_at=f"{nxt.isoformat()} {hh}", created_at=ts(600))


@app.on_event("startup")
def startup():
    with db(write=False) as conn:
        conn.executescript(SCHEMA)
    with db(write=True) as conn:
        seed(conn)


# ---------------------------------------------------------------- 페이지
STATIC = BASE / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def page(name):
    return lambda: FileResponse(STATIC / name)


app.get("/", include_in_schema=False)(page("index.html"))
app.get("/board", include_in_schema=False)(page("board.html"))
app.get("/counter", include_in_schema=False)(page("counter.html"))
app.get("/manager", include_in_schema=False)(page("manager.html"))
