"""두둑은행 지점 방문 예약 · 대기 현황판 (FastAPI + SQLite)"""
import os, re, secrets, sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "queue.db"))
TELLER_PIN = os.environ.get("TELLER_PIN", "1111")
MANAGER_PIN = os.environ.get("MANAGER_PIN", "9999")
OPEN_T = os.environ.get("BANK_OPEN", "09:00")
CLOSE_T = os.environ.get("BANK_CLOSE", "16:00")
COUNTERS = [1, 2, 3, 4]
SLOT_MIN = 10          # 예약 슬롯 간격(분)
SLOT_CAP = 3           # 슬롯당 최대 예약 수
GRACE_MIN = 15         # 예약 시각 후 이 시간까지 미도착이면 노쇼
SERVICES = {"예금": "D", "대출": "L", "외환": "F"}

app = FastAPI(title="두둑은행 대기 현황판")


# ---------- DB ----------
@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def today() -> str:
    return now().date().isoformat()


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL, ticket_no TEXT NOT NULL,
            name TEXT NOT NULL, phone TEXT NOT NULL, account TEXT NOT NULL,
            service TEXT NOT NULL, kind TEXT NOT NULL,        -- reservation | walkin
            status TEXT NOT NULL,                              -- reserved|waiting|called|done|noshow
            reserved_at TEXT, created_at TEXT NOT NULL, arrived_at TEXT,
            called_at TEXT, finished_at TEXT, counter INTEGER, noshow_reason TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_day_status ON tickets(day,status)")
        if c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
            seed(c)


def seed(c):
    """가상 데이터 (모두 허구의 이름·번호). 현재 시각 기준 상대 시간으로 생성."""
    n = now()
    cnt = {}

    def add(name, phone, acct, svc, kind, status, created_ago, reserved_in=None,
            counter=None, called_ago=None, dur=None, reason=None):
        pre = "R" if kind == "reservation" else SERVICES[svc]
        cnt[pre] = cnt.get(pre, 0) + 1
        created = n - timedelta(minutes=created_ago)
        rsv = iso(n + timedelta(minutes=reserved_in)) if reserved_in is not None else None
        arrived = None if (status == "reserved" or (status == "noshow" and counter is None)) else iso(created)
        called = iso(n - timedelta(minutes=called_ago)) if called_ago is not None else None
        fin = iso(n - timedelta(minutes=called_ago - dur)) if (dur and called_ago is not None) else None
        c.execute("""INSERT INTO tickets(day,ticket_no,name,phone,account,service,kind,status,reserved_at,
                     created_at,arrived_at,called_at,finished_at,counter,noshow_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (today(), f"{pre}{cnt[pre]:03d}", name, phone, acct, svc, kind, status, rsv, iso(created),
                   arrived, called, fin, counter, reason))

    A = lambda i: f"110-4201-88{i:04d}"
    P = lambda i: f"010-5501-{i:04d}"
    # 완료
    add("김민준", P(101), A(101), "예금", "walkin", "done", 95, counter=1, called_ago=80, dur=7)
    add("이서연", P(102), A(102), "대출", "reservation", "done", 90, reserved_in=-88, counter=2, called_ago=84, dur=22)
    add("박지후", P(103), A(103), "외환", "walkin", "done", 70, counter=3, called_ago=58, dur=11)
    add("최수아", P(104), A(104), "예금", "walkin", "done", 55, counter=1, called_ago=40, dur=9)
    add("정도윤", P(105), A(105), "예금", "reservation", "done", 50, reserved_in=-48, counter=4, called_ago=44, dur=6)
    # 노쇼 (미도착 예약 2건, 호출 후 미응답 1건)
    add("강하준", P(106), A(106), "대출", "reservation", "noshow", 80, reserved_in=-60, reason="미도착(예약시각 경과)")
    add("윤서현", P(107), A(107), "예금", "walkin", "noshow", 45, counter=2, called_ago=30, reason="호출 후 미응답")
    add("임지안", P(108), A(108), "외환", "reservation", "noshow", 40, reserved_in=-35, reason="미도착(예약시각 경과)")
    # 호출 중
    add("한예린", P(109), A(109), "대출", "reservation", "called", 25, reserved_in=-22, counter=1, called_ago=3)
    add("오건우", P(110), A(110), "예금", "walkin", "called", 20, counter=2, called_ago=1)
    add("서유나", P(111), A(111), "외환", "walkin", "called", 18, counter=3, called_ago=6)
    # 대기 (예약 도착 고객 + 현장 고객)
    add("권시우", P(112), A(112), "예금", "walkin", "waiting", 17)
    add("조은서", P(113), A(113), "대출", "reservation", "waiting", 14, reserved_in=-8)
    add("신재민", P(114), A(114), "예금", "walkin", "waiting", 12)
    add("배소율", P(115), A(115), "외환", "walkin", "waiting", 9)
    add("홍태오", P(116), A(116), "예금", "reservation", "waiting", 6, reserved_in=-3)
    add("류하린", P(117), A(117), "대출", "walkin", "waiting", 4)
    add("문지훈", P(118), A(118), "예금", "walkin", "waiting", 1)
    # 예약 (아직 도착 전)
    add("송다온", P(119), A(119), "예금", "reservation", "reserved", 120, reserved_in=8)
    add("안채원", P(120), A(120), "대출", "reservation", "reserved", 100, reserved_in=20)
    add("노윤호", P(121), A(121), "외환", "reservation", "reserved", 60, reserved_in=40)


def expire(c):
    """예약 시각 + 유예시간이 지나도 도착하지 않은 예약을 노쇼 처리."""
    limit = iso(now() - timedelta(minutes=GRACE_MIN))
    c.execute("""UPDATE tickets SET status='noshow', noshow_reason='미도착(예약시각 경과)'
                 WHERE day=? AND status='reserved' AND reserved_at < ?""", (today(), limit))


def waiting_rows(c):
    rows = c.execute("SELECT * FROM tickets WHERE day=? AND status='waiting'", (today(),)).fetchall()
    # 예약 도착 고객 우선(예약시각 순) → 현장 고객(발급 순)
    return sorted(rows, key=lambda r: (0 if r["kind"] == "reservation" else 1,
                                       r["reserved_at"] if r["kind"] == "reservation" else r["created_at"]))


# ---------- 마스킹 / 검증 ----------
def mask_name(n):
    if len(n) <= 1:
        return n
    if len(n) == 2:
        return n[0] + "*"
    return n[0] + "*" * (len(n) - 2) + n[-1]


def mask_acct(a):
    d = re.sub(r"\D", "", a)
    return "*" * (len(d) - 4) + d[-4:]


class Customer(BaseModel):
    name: str
    phone: str
    account: str
    service: Literal["예금", "대출", "외환"]

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[가-힣a-zA-Z ]{2,20}", v):
            raise ValueError("이름은 한글/영문 2~20자로 입력해 주세요")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        d = re.sub(r"\D", "", v)
        if not re.fullmatch(r"01\d{8,9}", d):
            raise ValueError("휴대전화 번호 형식이 올바르지 않습니다")
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"

    @field_validator("account")
    @classmethod
    def _acct(cls, v):
        if not re.fullmatch(r"[\d-]+", v.strip()) or not 10 <= len(re.sub(r"\D", "", v)) <= 14:
            raise ValueError("계좌번호는 숫자 10~14자리로 입력해 주세요")
        return v.strip()


class Reservation(Customer):
    slot: str  # HH:MM


def next_no(c, prefix):
    n = c.execute("SELECT COUNT(*) FROM tickets WHERE day=? AND ticket_no LIKE ?", (today(), prefix + "%")).fetchone()[0]
    return f"{prefix}{n + 1:03d}"


def ensure_no_active(c, phone):
    if c.execute("SELECT 1 FROM tickets WHERE day=? AND phone=? AND status IN ('reserved','waiting','called')",
                 (today(), phone)).fetchone():
        raise HTTPException(409, "이미 진행 중인 예약/번호표가 있습니다")


def slot_list():
    n = now()
    o = datetime.combine(n.date(), datetime.strptime(OPEN_T, "%H:%M").time())
    cl = datetime.combine(n.date(), datetime.strptime(CLOSE_T, "%H:%M").time())
    t, out = o, []
    while t <= cl - timedelta(minutes=SLOT_MIN):
        if t > n:
            out.append(t)
        t += timedelta(minutes=SLOT_MIN)
    return out


def slot_used(c, t):
    return c.execute("SELECT COUNT(*) FROM tickets WHERE kind='reservation' AND day=? AND reserved_at=? "
                     "AND status!='noshow'", (today(), iso(t))).fetchone()[0]


# ---------- 인증 ----------
TOKENS: dict = {}


class Login(BaseModel):
    role: Literal["teller", "manager"]
    pin: str


@app.post("/api/login")
def login(b: Login):
    pin = TELLER_PIN if b.role == "teller" else MANAGER_PIN
    if not secrets.compare_digest(b.pin.encode(), pin.encode()):
        raise HTTPException(401, "PIN이 올바르지 않습니다")
    t = secrets.token_urlsafe(24)
    TOKENS[t] = b.role
    return {"token": t}


def need(role):
    def dep(x_token: Optional[str] = Header(None)):
        r = TOKENS.get(x_token or "")
        if r is None or (r != role and r != "manager"):  # 지점장은 창구 화면도 열람 가능
            raise HTTPException(401, "로그인이 필요합니다")
        return r
    return dep


# ---------- 고객용 ----------
@app.get("/api/slots")
def slots():
    with db() as c:
        out = []
        for t in slot_list():
            used = slot_used(c, t)
            if used < SLOT_CAP:
                out.append({"slot": t.strftime("%H:%M"), "left": SLOT_CAP - used})
        return {"slots": out}


@app.post("/api/reservations")
def reserve(b: Reservation):
    valid = {t.strftime("%H:%M"): t for t in slot_list()}
    if b.slot not in valid:
        raise HTTPException(400, "선택할 수 없는 예약 시간입니다")
    t = valid[b.slot]
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            ensure_no_active(c, b.phone)
            if slot_used(c, t) >= SLOT_CAP:
                raise HTTPException(409, "해당 시간은 마감되었습니다")
            no = next_no(c, "R")
            c.execute("""INSERT INTO tickets(day,ticket_no,name,phone,account,service,kind,status,reserved_at,created_at)
                         VALUES(?,?,?,?,?,?,'reservation','reserved',?,?)""",
                      (today(), no, b.name, b.phone, b.account, b.service, iso(t), iso(now())))
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return {"ticket_no": no, "slot": b.slot,
            "message": f"예약 완료. 방문 시 예약번호 {no} 와 휴대전화 뒤 4자리로 도착 확인을 해 주세요."}


@app.post("/api/walkin")
def walkin(b: Customer):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            ensure_no_active(c, b.phone)
            no = next_no(c, SERVICES[b.service])
            ts = iso(now())
            c.execute("""INSERT INTO tickets(day,ticket_no,name,phone,account,service,kind,status,created_at,arrived_at)
                         VALUES(?,?,?,?,?,?,'walkin','waiting',?,?)""",
                      (today(), no, b.name, b.phone, b.account, b.service, ts, ts))
            ahead = len(waiting_rows(c)) - 1
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return {"ticket_no": no, "ahead": ahead}


class CheckIn(BaseModel):
    ticket_no: str
    phone_last4: str


@app.post("/api/checkin")
def checkin(b: CheckIn):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            expire(c)
            r = c.execute("SELECT * FROM tickets WHERE day=? AND ticket_no=? AND kind='reservation'",
                          (today(), b.ticket_no.strip().upper())).fetchone()
            last4 = b.phone_last4.strip()
            if not r or len(last4) != 4 or not r["phone"].endswith(last4):
                raise HTTPException(404, "예약 정보를 찾을 수 없습니다")
            if r["status"] == "noshow":
                raise HTTPException(410, "예약 시간이 지나 취소되었습니다. 현장 번호표를 발급해 주세요")
            if r["status"] != "reserved":
                raise HTTPException(409, "이미 도착 확인이 완료되었습니다")
            if now() < datetime.fromisoformat(r["reserved_at"]) - timedelta(minutes=30):
                raise HTTPException(400, "예약 시각 30분 전부터 도착 확인이 가능합니다")
            c.execute("UPDATE tickets SET status='waiting', arrived_at=? WHERE id=?", (iso(now()), r["id"]))
            pos = [w["id"] for w in waiting_rows(c)].index(r["id"]) + 1
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return {"ticket_no": r["ticket_no"], "position": pos}


# ---------- 대기 화면 (개인정보 마스킹: 이름 일부 + 번호표만) ----------
@app.get("/api/display")
def display():
    with db() as c:
        expire(c)
        called = {r["counter"]: r for r in c.execute(
            "SELECT * FROM tickets WHERE day=? AND status='called'", (today(),))}
        w = waiting_rows(c)
        return {
            "counters": [{"counter": k,
                          "ticket_no": called[k]["ticket_no"] if k in called else None,
                          "service": called[k]["service"] if k in called else None,
                          "name": mask_name(called[k]["name"]) if k in called else None,
                          "called_at": called[k]["called_at"] if k in called else None} for k in COUNTERS],
            "waiting": [{"pos": i + 1, "ticket_no": r["ticket_no"], "service": r["service"],
                         "kind": r["kind"], "name": mask_name(r["name"])} for i, r in enumerate(w[:12])],
            "waiting_count": len(w), "now": iso(now()),
        }


# ---------- 창구 ----------
def detail(r):
    if r is None:
        return None
    return {k: r[k] for k in ("ticket_no", "name", "phone", "account", "service", "kind",
                              "reserved_at", "arrived_at", "called_at")}


def current(c, counter):
    return c.execute("SELECT * FROM tickets WHERE day=? AND status='called' AND counter=?",
                     (today(), counter)).fetchone()


def check_counter(n):
    if n not in COUNTERS:
        raise HTTPException(400, "존재하지 않는 창구입니다")


class CounterReq(BaseModel):
    counter: int


@app.get("/api/teller/state", dependencies=[Depends(need("teller"))])
def teller_state(counter: int):
    check_counter(counter)
    with db() as c:
        expire(c)
        w = waiting_rows(c)
        return {"current": detail(current(c, counter)), "waiting_count": len(w),
                "next": [{"ticket_no": r["ticket_no"], "service": r["service"], "kind": r["kind"]} for r in w[:5]]}


@app.post("/api/teller/call", dependencies=[Depends(need("teller"))])
def teller_call(b: CounterReq):
    check_counter(b.counter)
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            expire(c)
            if current(c, b.counter):
                raise HTTPException(409, "현재 응대 중인 고객을 먼저 완료/노쇼 처리해 주세요")
            w = waiting_rows(c)
            if not w:
                raise HTTPException(404, "대기 중인 고객이 없습니다")
            c.execute("UPDATE tickets SET status='called', counter=?, called_at=? WHERE id=?",
                      (b.counter, iso(now()), w[0]["id"]))
            r = current(c, b.counter)
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return detail(r)


def close_current(counter, status, reason=None):
    check_counter(counter)
    with db() as c:
        r = current(c, counter)
        if not r:
            raise HTTPException(404, "응대 중인 고객이 없습니다")
        c.execute("UPDATE tickets SET status=?, finished_at=?, noshow_reason=? WHERE id=?",
                  (status, iso(now()), reason, r["id"]))
    return {"ok": True}


@app.post("/api/teller/finish", dependencies=[Depends(need("teller"))])
def teller_finish(b: CounterReq):
    return close_current(b.counter, "done")


@app.post("/api/teller/noshow", dependencies=[Depends(need("teller"))])
def teller_noshow(b: CounterReq):
    return close_current(b.counter, "noshow", "호출 후 미응답")


# ---------- 지점장 ----------
@app.get("/api/manager/summary", dependencies=[Depends(need("manager"))])
def manager_summary():
    with db() as c:
        expire(c)
        rows = c.execute("SELECT * FROM tickets WHERE day=?", (today(),)).fetchall()

        def by(s):
            return [r for r in rows if r["status"] == s]

        def mins(a, b):
            return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds() / 60

        waits = [mins(r["called_at"], r["arrived_at"]) for r in rows if r["called_at"] and r["arrived_at"]]
        rsv = [r for r in rows if r["kind"] == "reservation"]
        w = waiting_rows(c)
        n = iso(now())
        ns_rsv = [r for r in by("noshow") if r["kind"] == "reservation"]
        cur = {r["counter"]: r["ticket_no"] for r in by("called")}
        return {
            "counts": {"waiting": len(w), "called": len(by("called")), "done": len(by("done")),
                       "noshow": len(by("noshow")), "reserved_upcoming": len(by("reserved"))},
            "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else 0,
            "max_wait_now_min": round(max((mins(n, r["arrived_at"]) for r in w), default=0), 1),
            "reservation_total": len(rsv),
            "reservation_noshow_rate": round(100 * len(ns_rsv) / len(rsv), 1) if rsv else 0,
            "by_service": {s: {"waiting": sum(1 for r in w if r["service"] == s),
                               "done": sum(1 for r in by("done") if r["service"] == s)} for s in SERVICES},
            "counters": [{"counter": k, "ticket_no": cur.get(k),
                          "done": sum(1 for r in by("done") if r["counter"] == k)} for k in COUNTERS],
            "noshows": [{"ticket_no": r["ticket_no"], "name": r["name"], "phone": r["phone"],
                         "account": mask_acct(r["account"]), "service": r["service"], "kind": r["kind"],
                         "reserved_at": r["reserved_at"], "reason": r["noshow_reason"]}
                        for r in sorted(by("noshow"), key=lambda r: r["created_at"], reverse=True)],
            "waiting": [{"pos": i + 1, "ticket_no": r["ticket_no"], "service": r["service"], "kind": r["kind"],
                         "name": mask_name(r["name"]), "waited_min": round(mins(n, r["arrived_at"]))}
                        for i, r in enumerate(w)],
        }


# ---------- 화면 ----------
@app.get("/")
def root():
    return RedirectResponse("/static/index.html")


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
init_db()
