"""두둑은행 지점 방문 예약 · 대기 현황판 (FastAPI + SQLite)."""
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DUDUK_DB", str(BASE / "duduk.db"))
TELLER_PIN = os.environ.get("TELLER_PIN", "1111")
MANAGER_PIN = os.environ.get("MANAGER_PIN", "9999")

SERVICES = {"예금": "D", "대출": "L", "외환": "F"}
# 창구별 처리 업무
COUNTERS = {1: ["예금"], 2: ["예금", "대출"], 3: ["대출"], 4: ["외환", "예금"]}
SLOT_TIMES = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)] + ["16:00"]
SLOT_CAPACITY = 3
GRACE_MIN = 15       # 예약 시각 이후 이 시간까지 도착 확인이 없으면 노쇼
EARLY_MIN = 30       # 예약 시각 이 시간 전부터 도착 확인 가능

app = FastAPI(title="두둑은행 대기 현황판")
tokens: dict[str, str] = {}   # token -> role ("teller" | "manager")


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
    return d.isoformat(sep=" ")


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL,
            kind TEXT NOT NULL,              -- reserved | walkin
            service TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            account TEXT NOT NULL,
            slot TEXT,                       -- 예약 시각 (reserved만)
            status TEXT NOT NULL,            -- reserved|waiting|called|serving|done|noshow
            counter INTEGER,
            created_at TEXT NOT NULL,
            arrived_at TEXT,
            called_at TEXT,
            started_at TEXT,
            finished_at TEXT)""")
        if con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
            seed(con)


def next_number(con, service: str) -> str:
    n = con.execute("SELECT COUNT(*) FROM tickets WHERE service=?", (service,)).fetchone()[0]
    return f"{SERVICES[service]}{n + 1:03d}"


def seed(con):
    """가상 데이터. 시각은 현재 시각 기준 상대값이라 언제 실행해도 화면이 채워진다."""
    t = now()
    # (종류, 업무, 이름, 전화, 계좌, 예약 오프셋(분), 상태, 창구, 도착 오프셋(분))
    rows = [
        ("reserved", "예금", "김하늘", "010-0000-1001", "11000001000010", -150, "done", 1, -155),
        ("walkin", "예금", "이도윤", "010-0000-1002", "11000001000020", None, "done", 2, -140),
        ("reserved", "대출", "박서연", "010-0000-1003", "22000001000030", -120, "done", 3, -125),
        ("reserved", "외환", "최민준", "010-0000-1004", "33000001000040", -90, "noshow", None, None),
        ("walkin", "대출", "정지우", "010-0000-1005", "22000001000050", None, "done", 3, -80),
        ("reserved", "예금", "강예린", "010-0000-1006", "11000001000060", -60, "noshow", None, None),
        ("walkin", "예금", "조현우", "010-0000-1007", "11000001000070", None, "serving", 1, -25),
        ("reserved", "대출", "윤서아", "010-0000-1008", "22000001000080", -10, "called", 3, -20),
        ("reserved", "외환", "임주원", "010-0000-1009", "33000001000090", 0, "waiting", None, -5),
        ("walkin", "예금", "한지민", "010-0000-1010", "11000001000100", None, "waiting", None, -22),
        ("walkin", "외환", "오세훈", "010-0000-1011", "33000001000110", None, "waiting", None, -15),
        ("reserved", "예금", "서유진", "010-0000-1012", "11000001000120", 5, "waiting", None, -3),
        ("walkin", "대출", "배수빈", "010-0000-1013", "22000001000130", None, "waiting", None, -8),
        ("walkin", "예금", "문채원", "010-0000-1014", "11000001000140", None, "waiting", None, -2),
        ("reserved", "예금", "노지훈", "010-0000-1015", "11000001000150", 45, "reserved", None, None),
        ("reserved", "대출", "황다은", "010-0000-1016", "22000001000160", 75, "reserved", None, None),
    ]
    for kind, svc, name, phone, acct, off, status, ctr, arr in rows:
        slot = None
        if off is not None:
            s = t + timedelta(minutes=off)
            slot = iso(s.replace(minute=(s.minute // 5) * 5, second=0))
        base = arr if arr is not None else (off or 0) - 60
        created = iso(t + timedelta(minutes=base))
        arrived = iso(t + timedelta(minutes=arr)) if arr is not None else None
        called = started = finished = None
        if status in ("called", "serving", "done"):
            called = iso(t + timedelta(minutes=arr + 8))
        if status in ("serving", "done"):
            started = iso(t + timedelta(minutes=arr + 10))
        if status == "done":
            finished = iso(t + timedelta(minutes=arr + 22))
        con.execute(
            """INSERT INTO tickets(number,kind,service,name,phone,account,slot,status,counter,
               created_at,arrived_at,called_at,started_at,finished_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (next_number(con, svc), kind, svc, name, phone, acct, slot, status, ctr,
             created, arrived, called, started, finished))


@app.on_event("startup")
def startup():
    init_db()


def sweep(con):
    """예약 시각 + 유예시간이 지나도 도착 확인이 없으면 노쇼 처리."""
    limit = iso(now() - timedelta(minutes=GRACE_MIN))
    con.execute("UPDATE tickets SET status='noshow' WHERE status='reserved' AND slot<?", (limit,))


# ---------- 마스킹 / 인증 ----------
def mask_name(n: str) -> str:
    return n[0] + "*" * (len(n) - 1) if len(n) > 1 else n


def mask_phone(p: str) -> str:
    return re.sub(r"(\d{3})-(\d{3,4})-(\d{4})", r"\1-****-\3", p)


def mask_account(a: str) -> str:
    return "*" * (len(a) - 4) + a[-4:]


def require(role: str):
    def dep(x_token: str = Header(default="")):
        if tokens.get(x_token) != role:
            raise HTTPException(401, "로그인이 필요합니다.")
    return dep


class Login(BaseModel):
    role: str
    pin: str


@app.post("/api/login")
def login(b: Login):
    pins = {"teller": TELLER_PIN, "manager": MANAGER_PIN}
    if b.role not in pins or not secrets.compare_digest(b.pin.encode(), pins[b.role].encode()):
        raise HTTPException(401, "PIN이 올바르지 않습니다.")
    tok = secrets.token_urlsafe(16)
    tokens[tok] = b.role
    return {"token": tok}


# ---------- 고객: 예약 / 번호표 / 도착 확인 ----------
def norm_phone(v: str) -> str:
    d = re.sub(r"\D", "", v)
    if not re.fullmatch(r"01\d{8,9}", d):
        raise ValueError("전화번호 형식이 올바르지 않습니다.")
    return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"


class Customer(BaseModel):
    name: str
    phone: str
    account: str
    service: str

    @field_validator("name")
    @classmethod
    def v_name(cls, v):
        v = v.strip()
        if not 1 <= len(v) <= 20:
            raise ValueError("이름을 확인해 주세요.")
        return v

    @field_validator("phone")
    @classmethod
    def v_phone(cls, v):
        return norm_phone(v)

    @field_validator("account")
    @classmethod
    def v_account(cls, v):
        d = re.sub(r"[\s-]", "", v)
        if not re.fullmatch(r"\d{10,14}", d):
            raise ValueError("계좌번호는 숫자 10~14자리로 입력해 주세요.")
        return d

    @field_validator("service")
    @classmethod
    def v_service(cls, v):
        if v not in SERVICES:
            raise ValueError("업무 종류는 예금·대출·외환 중 하나입니다.")
        return v


class Reservation(Customer):
    slot: str   # HH:MM


def slot_dt(s: str) -> datetime:
    return datetime.strptime(f"{now():%Y-%m-%d} {s}", "%Y-%m-%d %H:%M")


def slot_used(con, start: datetime) -> int:
    return con.execute("SELECT COUNT(*) FROM tickets WHERE kind='reserved' AND slot=? AND status!='noshow'",
                       (iso(start),)).fetchone()[0]


@app.get("/api/slots")
def slots():
    with db() as con:
        out = []
        for s in SLOT_TIMES:
            start = slot_dt(s)
            left = max(0, SLOT_CAPACITY - slot_used(con, start))
            out.append({"time": s, "available": start > now() and left > 0, "left": left})
        return out


@app.post("/api/reservations")
def reserve(b: Reservation):
    if b.slot not in SLOT_TIMES:
        raise HTTPException(422, "예약 가능한 시간이 아닙니다.")
    start = slot_dt(b.slot)
    if start <= now():
        raise HTTPException(422, "이미 지난 시간입니다.")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            if slot_used(con, start) >= SLOT_CAPACITY:
                raise HTTPException(409, "해당 시간은 마감되었습니다.")
            if con.execute("SELECT 1 FROM tickets WHERE phone=? AND status IN ('reserved','waiting','called','serving')",
                           (b.phone,)).fetchone():
                raise HTTPException(409, "이미 진행 중인 예약/대기가 있습니다.")
            num = next_number(con, b.service)
            con.execute("""INSERT INTO tickets(number,kind,service,name,phone,account,slot,status,created_at)
                           VALUES(?,?,?,?,?,?,?,'reserved',?)""",
                        (num, "reserved", b.service, b.name, b.phone, b.account, iso(start), iso(now())))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return {"number": num, "message": f"{b.slot} 예약 완료 (번호 {num}). 방문하셔서 '예약 도착 확인'을 해 주세요."}


@app.post("/api/walkin")
def walkin(b: Customer):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            dup = con.execute("SELECT number FROM tickets WHERE phone=? AND status IN ('waiting','called','serving')",
                              (b.phone,)).fetchone()
            if dup:
                raise HTTPException(409, f"이미 대기 중입니다. (번호표 {dup['number']})")
            num = next_number(con, b.service)
            t = iso(now())
            con.execute("""INSERT INTO tickets(number,kind,service,name,phone,account,status,created_at,arrived_at)
                           VALUES(?,?,?,?,?,?,'waiting',?,?)""",
                        (num, "walkin", b.service, b.name, b.phone, b.account, t, t))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return {"number": num, "message": f"번호표 {num} 이(가) 발급되었습니다. 대기 화면을 확인해 주세요."}


class CheckIn(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def v_phone(cls, v):
        return norm_phone(v)


@app.post("/api/checkin")
def checkin(b: CheckIn):
    with db() as con:
        sweep(con)
        r = con.execute("SELECT * FROM tickets WHERE phone=? AND status='reserved' ORDER BY slot LIMIT 1",
                        (b.phone,)).fetchone()
        if not r:
            raise HTTPException(404, "오늘 예약을 찾을 수 없습니다. 예약 시간이 지나 노쇼 처리되었다면 번호표를 새로 뽑아 주세요.")
        slot = datetime.fromisoformat(r["slot"])
        if now() < slot - timedelta(minutes=EARLY_MIN):
            raise HTTPException(409, f"예약 {EARLY_MIN}분 전부터 도착 확인이 가능합니다. (예약 {slot:%H:%M})")
        con.execute("UPDATE tickets SET status='waiting', arrived_at=? WHERE id=?", (iso(now()), r["id"]))
    return {"number": r["number"], "message": f"도착 확인 완료. 번호 {r['number']} — 예약 고객은 우선 호출됩니다."}


# ---------- 대기 순서: 예약 고객 우선, 그 안에서는 예약 시각순, 현장은 도착순 ----------
ORDER = ("CASE kind WHEN 'reserved' THEN 0 ELSE 1 END, "
         "CASE kind WHEN 'reserved' THEN slot ELSE arrived_at END, id")


def waiting_rows(con):
    return con.execute(f"SELECT * FROM tickets WHERE status='waiting' ORDER BY {ORDER}").fetchall()


@app.get("/api/display")
def display():
    """공용 모니터용. 개인정보 없음 (번호표·업무·창구만)."""
    with db() as con:
        sweep(con)
        calling = con.execute("""SELECT number,service,counter,status FROM tickets
                                 WHERE status IN ('called','serving') ORDER BY counter""").fetchall()
        wait = waiting_rows(con)
        return {
            "now": iso(now()),
            "calling": [dict(r) for r in calling],
            "waiting": [{"number": r["number"], "service": r["service"],
                         "reserved": r["kind"] == "reserved", "order": i + 1}
                        for i, r in enumerate(wait)],
        }


# ---------- 창구 ----------
class CallReq(BaseModel):
    counter: int


@app.get("/api/counters")
def counters():
    return {str(k): v for k, v in COUNTERS.items()}


def detail(r):
    return {k: r[k] for k in ("id", "number", "kind", "service", "name", "phone", "account", "slot",
                              "status", "counter", "arrived_at", "called_at", "started_at")}


@app.get("/api/teller/state", dependencies=[Depends(require("teller"))])
def teller_state(counter: int):
    if counter not in COUNTERS:
        raise HTTPException(404, "없는 창구입니다.")
    with db() as con:
        sweep(con)
        cur = con.execute("SELECT * FROM tickets WHERE counter=? AND status IN ('called','serving')",
                          (counter,)).fetchone()
        mine = [r for r in waiting_rows(con) if r["service"] in COUNTERS[counter]]
        return {"current": detail(cur) if cur else None,
                "waiting": len(mine),
                "next": mine[0]["number"] if mine else None}


@app.post("/api/teller/call", dependencies=[Depends(require("teller"))])
def teller_call(b: CallReq):
    if b.counter not in COUNTERS:
        raise HTTPException(404, "없는 창구입니다.")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            sweep(con)
            if con.execute("SELECT 1 FROM tickets WHERE counter=? AND status IN ('called','serving')",
                           (b.counter,)).fetchone():
                raise HTTPException(409, "처리 중인 고객이 있습니다. 먼저 완료/노쇼 처리해 주세요.")
            nxt = next((r for r in waiting_rows(con) if r["service"] in COUNTERS[b.counter]), None)
            if not nxt:
                raise HTTPException(404, "대기 중인 고객이 없습니다.")
            con.execute("UPDATE tickets SET status='called', counter=?, called_at=? WHERE id=?",
                        (b.counter, iso(now()), nxt["id"]))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return detail(con.execute("SELECT * FROM tickets WHERE id=?", (nxt["id"],)).fetchone())


class Action(BaseModel):
    action: str   # start | done | noshow


@app.post("/api/teller/{tid}/action", dependencies=[Depends(require("teller"))])
def teller_action(tid: int, b: Action):
    t = iso(now())
    with db() as con:
        r = con.execute("SELECT status FROM tickets WHERE id=?", (tid,)).fetchone()
        if not r:
            raise HTTPException(404, "없는 번호표입니다.")
        st, a = r["status"], b.action
        if a == "start" and st == "called":
            con.execute("UPDATE tickets SET status='serving', started_at=? WHERE id=?", (t, tid))
        elif a == "done" and st == "serving":
            con.execute("UPDATE tickets SET status='done', finished_at=? WHERE id=?", (t, tid))
        elif a == "noshow" and st == "called":
            con.execute("UPDATE tickets SET status='noshow', finished_at=? WHERE id=?", (t, tid))
        else:
            raise HTTPException(409, "현재 상태에서 할 수 없는 동작입니다.")
    return {"ok": True}


# ---------- 지점장 ----------
@app.get("/api/manager/summary", dependencies=[Depends(require("manager"))])
def manager_summary():
    with db() as con:
        sweep(con)
        rows = con.execute("SELECT * FROM tickets").fetchall()
        wait = waiting_rows(con)

        def minutes(a, b):
            return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60

        n = iso(now())
        done = [r for r in rows if r["status"] == "done"]
        waits = [minutes(r["arrived_at"], r["called_at"]) for r in done if r["arrived_at"] and r["called_at"]]
        noshow = [r for r in rows if r["status"] == "noshow"]
        decided = [r for r in rows if r["kind"] == "reserved" and r["status"] != "reserved"]
        return {
            "waiting_total": len(wait),
            "waiting_by_service": {s: sum(1 for r in wait if r["service"] == s) for s in SERVICES},
            "waiting_reserved": sum(1 for r in wait if r["kind"] == "reserved"),
            "longest_wait_min": round(max((minutes(r["arrived_at"], n) for r in wait), default=0)),
            "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else 0,
            "done": len(done),
            "per_counter": {str(c): sum(1 for r in done if r["counter"] == c) for c in COUNTERS},
            "noshow_total": len(noshow),
            "noshow_rate": round(100 * sum(1 for r in decided if r["status"] == "noshow") / len(decided), 1)
            if decided else 0,
            "noshows": [{"number": r["number"], "service": r["service"], "name": mask_name(r["name"]),
                         "phone": mask_phone(r["phone"]), "account": mask_account(r["account"]),
                         "slot": r["slot"][11:16] if r["slot"] else None,
                         "kind": "예약 미도착" if r["kind"] == "reserved" and not r["counter"] else "호출 후 미응답"}
                        for r in noshow],
            "queue": [{"order": i + 1, "number": r["number"], "service": r["service"],
                       "kind": "예약" if r["kind"] == "reserved" else "현장",
                       "waited_min": round(minutes(r["arrived_at"], n))} for i, r in enumerate(wait)],
        }


# ---------- 정적 페이지 ----------
@app.get("/")
def root():
    return RedirectResponse("/static/index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
