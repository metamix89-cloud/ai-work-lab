"""두둑은행 지점 방문 예약 · 대기 현황판."""
import asyncio
import hmac
import os
import re
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB_PATH = os.environ.get("DUDUG_DB", str(BASE.parent / "dudug.db"))

# ---- 지점 규칙 -------------------------------------------------------------
PRIORITY_WINDOW = timedelta(minutes=10)   # 예약 시각 앞뒤 10분
CALL_TIMEOUT = timedelta(minutes=3)       # 호출 후 3분 내 미도착 → 보류
WINDOW_TYPE = {1: "deposit", 2: "deposit", 3: "loan", 4: "fx"}
PREFIX = {"deposit": "A", "loan": "B", "fx": "C"}
TYPE_LABEL = {"deposit": "예금", "loan": "대출", "fx": "외환"}
OPEN_H, CLOSE_H = 9, 16                   # 예약 가능 시간대 09:00~16:00

# ---- 데모용 PIN (운영 시 환경변수로 교체) ------------------------------------
TELLER_PINS = dict(zip(WINDOW_TYPE, os.environ.get(
    "DUDUG_TELLER_PINS", "1111,2222,3333,4444").split(",")))
MANAGER_PIN = os.environ.get("DUDUG_MANAGER_PIN", "9999")
SESSION_TTL = timedelta(hours=8)

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
sessions: dict[str, dict] = {}
fails: dict[str, list[datetime]] = {}


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS reservations(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, phone TEXT, account_last4 TEXT,
  work_type TEXT, reserved_at TEXT, status TEXT DEFAULT 'reserved');
CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY, ticket_date TEXT, seq INTEGER, number TEXT, work_type TEXT,
  name TEXT, phone TEXT, account_last4 TEXT, reservation_id INTEGER,
  arrived_at TEXT, priority INTEGER DEFAULT 0, status TEXT DEFAULT 'waiting',
  window INTEGER, called_at TEXT, started_at TEXT, finished_at TEXT, held INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_t ON tickets(ticket_date, status);
"""


def init_db(path: str = DB_PATH, seed_data: bool = True):
    global _conn
    with _lock:
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        if seed_data and not _conn.execute("SELECT 1 FROM tickets").fetchone():
            seed(_conn)
        _conn.commit()


@contextmanager
def db():
    with _lock:
        try:
            sweep(_conn)
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


# ---- 도메인 로직 -------------------------------------------------------------
def mask_name(name: str) -> str:
    n = len(name)
    if n <= 1:
        return "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


def mask_phone(p: str) -> str:
    return f"{p[:3]}-****-{p[-4:]}"


ORDER = "priority DESC, arrived_at, id"


def new_ticket(c, wt, name, phone, last4, arrived, priority, res_id=None) -> sqlite3.Row:
    day = arrived.date().isoformat()
    seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM tickets WHERE ticket_date=? AND work_type=?",
                    (day, wt)).fetchone()[0]
    cur = c.execute(
        "INSERT INTO tickets(ticket_date,seq,number,work_type,name,phone,account_last4,"
        "reservation_id,arrived_at,priority) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (day, seq, f"{PREFIX[wt]}{seq:03d}", wt, name, phone, last4, res_id, iso(arrived), int(priority)))
    return c.execute("SELECT * FROM tickets WHERE id=?", (cur.lastrowid,)).fetchone()


def active_ticket(c, window: int):
    return c.execute("SELECT * FROM tickets WHERE ticket_date=? AND window=? AND status IN ('called','serving')",
                     (now().date().isoformat(), window)).fetchone()


def call_next(c, window: int):
    """창구 업무에 맞는 대기 1순위를 호출. 이미 응대 중이면 None."""
    if active_ticket(c, window):
        return None
    row = c.execute(f"SELECT id FROM tickets WHERE ticket_date=? AND status='waiting' AND work_type=? "
                    f"ORDER BY {ORDER} LIMIT 1", (now().date().isoformat(), WINDOW_TYPE[window])).fetchone()
    if not row:
        return None
    c.execute("UPDATE tickets SET status='called', window=?, called_at=? WHERE id=?",
              (window, iso(now()), row["id"]))
    return row["id"]


def sweep(c):
    """호출 후 3분 초과 → 보류, 같은 창구의 다음 번호 호출."""
    limit = iso(now() - CALL_TIMEOUT)
    for r in c.execute("SELECT id, window FROM tickets WHERE status='called' AND called_at<=?", (limit,)).fetchall():
        c.execute("UPDATE tickets SET status='hold', held=1 WHERE id=?", (r["id"],))
        call_next(c, r["window"])
    c.commit()


# ---- 스키마(입력 검증) -------------------------------------------------------
WorkType = Literal["deposit", "loan", "fx"]


class Person(BaseModel):
    name: str
    phone: str
    account: str
    work_type: WorkType

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[가-힣A-Za-z]{2,20}", v):
            raise ValueError("이름은 2~20자의 한글/영문이어야 합니다")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        v = re.sub(r"\D", "", v)
        if not re.fullmatch(r"0\d{9,10}", v):
            raise ValueError("전화번호 형식이 올바르지 않습니다")
        return v

    @field_validator("account")
    @classmethod
    def _acct(cls, v):
        v = re.sub(r"\D", "", v)
        if not 10 <= len(v) <= 16:
            raise ValueError("계좌번호는 숫자 10~16자리여야 합니다")
        return v


class ReserveIn(Person):
    reserved_at: datetime


class CheckinIn(BaseModel):
    code: str
    phone_last4: str


class LoginIn(BaseModel):
    role: Literal["teller", "manager"]
    window: Optional[int] = None
    pin: str


# ---- 인증 -------------------------------------------------------------------
def auth(role: str):
    def dep(x_token: str = Header(default="")):
        s = sessions.get(x_token)
        if not s or s["exp"] < now() or s["role"] != role:
            raise HTTPException(401, "로그인이 필요합니다")
        return s
    return dep


@asynccontextmanager
async def lifespan(app):
    init_db()

    async def loop():
        while True:
            await asyncio.sleep(5)
            with _lock:
                sweep(_conn)
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="두둑은행 대기 현황판", lifespan=lifespan)


# ---- 고객 (공개) -------------------------------------------------------------
def ahead_of(c, t) -> int:
    return c.execute(
        "SELECT COUNT(*) FROM tickets WHERE ticket_date=? AND status='waiting' AND work_type=? AND id!=? AND "
        "(priority>? OR (priority=? AND (arrived_at<? OR (arrived_at=? AND id<?))))",
        (t["ticket_date"], t["work_type"], t["id"], t["priority"], t["priority"],
         t["arrived_at"], t["arrived_at"], t["id"])).fetchone()[0]


@app.post("/api/reservations")
def reserve(b: ReserveIn):
    t = b.reserved_at.replace(tzinfo=None, second=0, microsecond=0)
    n = now()
    if t < n or t > n + timedelta(days=7):
        raise HTTPException(422, "예약은 지금부터 7일 이내만 가능합니다")
    if not (OPEN_H, 0) <= (t.hour, t.minute) <= (CLOSE_H, 0):
        raise HTTPException(422, f"예약 가능 시간은 {OPEN_H:02d}:00~{CLOSE_H:02d}:00 입니다")
    with db() as c:
        for _ in range(20):
            code = f"{secrets.randbelow(10**6):06d}"
            if not c.execute("SELECT 1 FROM reservations WHERE code=?", (code,)).fetchone():
                break
        c.execute("INSERT INTO reservations(code,name,phone,account_last4,work_type,reserved_at) VALUES(?,?,?,?,?,?)",
                  (code, b.name, b.phone, b.account[-4:], b.work_type, iso(t)))
    return {"code": code, "reserved_at": iso(t)}


@app.post("/api/reservations/checkin")
def checkin(b: CheckinIn):
    with db() as c:
        r = c.execute("SELECT * FROM reservations WHERE code=?", (b.code.strip(),)).fetchone()
        if not r or not hmac.compare_digest(r["phone"][-4:], b.phone_last4.strip()):
            raise HTTPException(404, "예약을 찾을 수 없습니다")
        n = now()
        if r["status"] != "reserved":
            raise HTTPException(409, "이미 도착 확인된 예약입니다")
        if r["reserved_at"][:10] != n.date().isoformat():
            raise HTTPException(409, "예약 당일에만 도착 확인이 가능합니다")
        prio = abs(n - datetime.fromisoformat(r["reserved_at"])) <= PRIORITY_WINDOW
        t = new_ticket(c, r["work_type"], r["name"], r["phone"], r["account_last4"], n, prio, r["id"])
        c.execute("UPDATE reservations SET status='checked_in' WHERE id=?", (r["id"],))
        return {"number": t["number"], "priority": prio, "ahead": ahead_of(c, t)}


@app.post("/api/tickets")
def walk_in(b: Person):
    with db() as c:
        t = new_ticket(c, b.work_type, b.name, b.phone, b.account[-4:], now(), False)
        return {"number": t["number"], "priority": False, "ahead": ahead_of(c, t)}


@app.get("/api/display")
def display():
    """대기 화면: 번호 · 가린 이름 · 창구 번호만 내보낸다."""
    day = now().date().isoformat()
    with db() as c:
        calling = c.execute("SELECT window, number, name FROM tickets WHERE ticket_date=? AND "
                            "status IN ('called','serving')", (day,)).fetchall()
        waiting = c.execute(f"SELECT number, name FROM tickets WHERE ticket_date=? AND status='waiting' "
                            f"ORDER BY {ORDER} LIMIT 30", (day,)).fetchall()
    by_win = {r["window"]: r for r in calling}
    return {
        "windows": [{"window": w, "number": by_win[w]["number"] if w in by_win else None,
                     "name": mask_name(by_win[w]["name"]) if w in by_win else None} for w in WINDOW_TYPE],
        "waiting": [{"number": r["number"], "name": mask_name(r["name"])} for r in waiting],
    }


# ---- 로그인 -----------------------------------------------------------------
@app.post("/api/login")
def login(b: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    n = now()
    fails[ip] = [t for t in fails.get(ip, []) if n - t < timedelta(minutes=1)]
    if len(fails[ip]) >= 5:
        raise HTTPException(429, "시도가 너무 많습니다. 잠시 후 다시 시도하세요")
    if b.role == "teller":
        if b.window not in WINDOW_TYPE:
            raise HTTPException(422, "창구 번호가 올바르지 않습니다")
        expected = TELLER_PINS[b.window]
    else:
        expected = MANAGER_PIN
    if not hmac.compare_digest(expected.encode(), b.pin.encode()):
        fails[ip].append(n)
        raise HTTPException(401, "PIN이 올바르지 않습니다")
    token = secrets.token_urlsafe(24)
    sessions[token] = {"role": b.role, "window": b.window if b.role == "teller" else None, "exp": n + SESSION_TTL}
    return {"token": token, "role": b.role, "window": sessions[token]["window"]}


# ---- 창구 직원 ---------------------------------------------------------------
def detail(t) -> dict:
    left = None
    if t["status"] == "called":
        left = max(0, int((datetime.fromisoformat(t["called_at"]) + CALL_TIMEOUT - now()).total_seconds()))
    return {"id": t["id"], "number": t["number"], "status": t["status"], "name": t["name"],
            "phone": mask_phone(t["phone"]), "account_last4": t["account_last4"],
            "work_type": TYPE_LABEL[t["work_type"]], "reserved": t["reservation_id"] is not None,
            "priority": bool(t["priority"]), "seconds_left": left}


@app.get("/api/teller/state")
def teller_state(s=Depends(auth("teller"))):
    w, day = s["window"], now().date().isoformat()
    with db() as c:
        cur = active_ticket(c, w)
        wait = c.execute(f"SELECT number, name FROM tickets WHERE ticket_date=? AND status='waiting' AND work_type=? "
                         f"ORDER BY {ORDER}", (day, WINDOW_TYPE[w])).fetchall()
        hold = c.execute("SELECT id, number, name FROM tickets WHERE ticket_date=? AND status='hold' AND work_type=?",
                         (day, WINDOW_TYPE[w])).fetchall()
    return {"window": w, "work_type": TYPE_LABEL[WINDOW_TYPE[w]],
            "current": detail(cur) if cur else None,
            "waiting": [{"number": r["number"], "name": mask_name(r["name"])} for r in wait],
            "hold": [{"id": r["id"], "number": r["number"], "name": mask_name(r["name"])} for r in hold]}


@app.post("/api/teller/call-next")
def teller_call(s=Depends(auth("teller"))):
    with db() as c:
        if active_ticket(c, s["window"]):
            raise HTTPException(409, "응대 중인 고객이 있습니다")
        if call_next(c, s["window"]) is None:
            raise HTTPException(404, "대기 고객이 없습니다")
    return {"ok": True}


def own_ticket(c, s, tid: int, *statuses: str):
    t = c.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    # 다른 창구/업무의 고객은 존재 여부도 알려주지 않는다
    if not t or t["work_type"] != WINDOW_TYPE[s["window"]] or (t["window"] not in (None, s["window"])):
        raise HTTPException(404, "해당 고객을 찾을 수 없습니다")
    if t["status"] not in statuses:
        raise HTTPException(409, "처리할 수 없는 상태입니다")
    return t


@app.post("/api/teller/{tid}/start")
def teller_start(tid: int, s=Depends(auth("teller"))):
    with db() as c:
        own_ticket(c, s, tid, "called")
        c.execute("UPDATE tickets SET status='serving', started_at=? WHERE id=?", (iso(now()), tid))
    return {"ok": True}


@app.post("/api/teller/{tid}/complete")
def teller_complete(tid: int, s=Depends(auth("teller"))):
    with db() as c:
        own_ticket(c, s, tid, "serving")
        c.execute("UPDATE tickets SET status='done', finished_at=? WHERE id=?", (iso(now()), tid))
    return {"ok": True}


@app.post("/api/teller/{tid}/recall")
def teller_recall(tid: int, s=Depends(auth("teller"))):
    with db() as c:
        own_ticket(c, s, tid, "hold")
        if active_ticket(c, s["window"]):
            raise HTTPException(409, "응대 중인 고객이 있습니다")
        c.execute("UPDATE tickets SET status='called', window=?, called_at=? WHERE id=?",
                  (s["window"], iso(now()), tid))
    return {"ok": True}


# ---- 지점장: 숫자만 -----------------------------------------------------------
@app.get("/api/manager/summary")
def manager_summary(_=Depends(auth("manager"))):
    n = now()
    day = n.date().isoformat()
    with db() as c:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
        per_type = {}
        for wt, label in TYPE_LABEL.items():
            oldest = q("SELECT MIN(arrived_at) FROM tickets WHERE ticket_date=? AND status='waiting' AND work_type=?", day, wt)
            per_type[wt] = {
                "label": label,
                "waiting": q("SELECT COUNT(*) FROM tickets WHERE ticket_date=? AND status='waiting' AND work_type=?", day, wt),
                "done": q("SELECT COUNT(*) FROM tickets WHERE ticket_date=? AND status='done' AND work_type=?", day, wt),
                "longest_wait_min": int((n - datetime.fromisoformat(oldest)).total_seconds() // 60) if oldest else 0,
            }
        cutoff = iso(n - PRIORITY_WINDOW)
        return {
            "generated_at": iso(n),
            "waiting": sum(v["waiting"] for v in per_type.values()),
            "in_service": q("SELECT COUNT(*) FROM tickets WHERE ticket_date=? AND status IN ('called','serving')", day),
            "done": sum(v["done"] for v in per_type.values()),
            "per_type": per_type,
            "reservations_today": q("SELECT COUNT(*) FROM reservations WHERE substr(reserved_at,1,10)=?", day),
            "noshow_reservation": q("SELECT COUNT(*) FROM reservations WHERE substr(reserved_at,1,10)=? AND "
                                    "status='reserved' AND reserved_at<?", day, cutoff),
            "noshow_after_call": q("SELECT COUNT(*) FROM tickets WHERE ticket_date=? AND held=1", day),
            "on_hold_now": q("SELECT COUNT(*) FROM tickets WHERE ticket_date=? AND status='hold'", day),
        }


# ---- 가상 데이터 --------------------------------------------------------------
def seed(c):
    n = now()
    m = lambda x: n + timedelta(minutes=x)  # noqa: E731

    def res(name, phone, acct, wt, at, status="reserved"):
        cur = c.execute("INSERT INTO reservations(code,name,phone,account_last4,work_type,reserved_at,status) "
                        "VALUES(?,?,?,?,?,?,?)", (f"{secrets.randbelow(10**6):06d}", name, phone, acct[-4:], wt, iso(at), status))
        return cur.lastrowid

    def tk(wt, name, phone, acct, arrived, prio=False, rid=None, **st):
        t = new_ticket(c, wt, name, phone, acct[-4:], arrived, prio, rid)
        if st:
            c.execute("UPDATE tickets SET " + ",".join(f"{k}=?" for k in st) + " WHERE id=?", (*st.values(), t["id"]))

    d = "deposit"
    tk(d, "박진호", "010-0000-4634", "1102345678901", m(-55), status="done", window=1, called_at=iso(m(-50)), finished_at=iso(m(-42)))
    tk("loan", "이나래", "010-0000-4420", "3023456789012", m(-50), status="done", window=3, called_at=iso(m(-45)), finished_at=iso(m(-30)))
    tk("fx", "정우성", "010-0000-5373", "2209876543210", m(-40), status="done", window=4, called_at=iso(m(-35)), finished_at=iso(m(-25)))
    tk(d, "최유리", "010-0000-1735", "1105678901234", m(-20), status="serving", window=1, called_at=iso(m(-8)), started_at=iso(m(-6)))
    r = res("김민수", "010-0000-1273", "1107777788889", d, m(-3), "checked_in")
    tk(d, "김민수", "010-0000-1273", "1107777788889", m(-4), True, r, status="called", window=2, called_at=iso(m(-1)))
    r = res("정하늘", "010-0000-3249", "1108888899990", d, m(4), "checked_in")
    tk(d, "정하늘", "010-0000-3249", "1108888899990", m(-1), True, r)          # 우선
    tk(d, "오세훈", "010-0000-7680", "1109999900001", m(-12))
    r = res("한지민", "010-0000-1160", "1101111122223", d, m(-45), "checked_in")
    tk(d, "한지민", "010-0000-1160", "1101111122223", m(-8), False, r)         # 예약 시각 지나 도착 → 일반
    r = res("윤서연", "010-0000-4084", "3021111222233", "loan", m(2), "checked_in")
    tk("loan", "윤서연", "010-0000-4084", "3021111222233", m(-2), True, r)
    tk("loan", "강동원", "010-0000-5478", "3025555666677", m(-15))
    tk("fx", "송지훈", "010-0000-9800", "2207777888899", m(-6))
    tk("fx", "조민재", "010-0000-1799", "2204444555566", m(-30), status="hold", held=1, window=4, called_at=iso(m(-12)))
    res("임수정", "010-0000-9280", "1103333444455", "loan", m(30))
    res("배도윤", "010-0000-2724", "2206666777788", "fx", m(80))
    res("노지원", "010-0000-3875", "1102222333344", d, m(-30))                  # 예약 미방문(노쇼)


# ---- 화면 -------------------------------------------------------------------
for route, page in {"/": "index", "/display": "display", "/teller": "teller", "/manager": "manager"}.items():
    app.add_api_route(route, (lambda p: lambda: FileResponse(STATIC / f"{p}.html"))(page), include_in_schema=False)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
