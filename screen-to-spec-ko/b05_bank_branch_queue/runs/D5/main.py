"""두둑은행 지점 방문 예약 · 대기 현황판 (FastAPI + SQLite)"""
import asyncio
import contextlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DUDUK_DB", os.path.join(BASE, "duduk.db"))

PRIORITY_WINDOW_SEC = 10 * 60   # 예약 시각 앞뒤 10분
CALL_TIMEOUT_SEC = 3 * 60       # 호출 후 3분
WINDOWS = {1: "deposit", 2: "deposit", 3: "loan", 4: "fx"}
SERVICES = {"deposit": ("예금", "A"), "loan": ("대출", "B"), "fx": ("외환", "C")}
WINDOW_LABEL = {"deposit": "창구 1·2", "loan": "창구 3", "fx": "창구 4"}

# 데모용 기본 PIN. 운영 시 반드시 환경변수로 교체.
TELLER_PINS = dict(zip(WINDOWS, os.environ.get("TELLER_PINS", "1111,2222,3333,4444").split(",")))
MANAGER_PIN = os.environ.get("MANAGER_PIN", "9999")

# 대기 순서: 우선(예약 도착 ±10분) 먼저 → 우선끼리는 예약 시각, 일반은 접수 순
ORDER = "priority DESC, CASE WHEN priority=1 THEN reserved_at ELSE order_at END, id"


# ---------------------------------------------------------------- DB
def connect():
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


@contextlib.contextmanager
def tx():
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except BaseException:
        with contextlib.suppress(sqlite3.Error):
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


@contextlib.contextmanager
def rd():
    c = connect()
    try:
        yield c
    finally:
        c.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS visits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,              -- walkin | reserved
  name TEXT NOT NULL, phone TEXT NOT NULL,
  acct_last4 TEXT NOT NULL,        -- 계좌번호 전체는 저장하지 않음
  service TEXT NOT NULL, day TEXT NOT NULL,
  reserved_at INTEGER, rcode TEXT UNIQUE,
  ticket_seq INTEGER, ticket_no TEXT,
  order_at INTEGER, priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,            -- booked|waiting|called|serving|done|hold
  win INTEGER,
  called_at INTEGER, started_at INTEGER, finished_at INTEGER,
  created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_q ON visits(day, status, service);
"""


def day_of(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def mask_name(n):
    n = n.strip()
    if len(n) <= 1:
        return "*"
    if len(n) == 2:
        return n[0] + "*"
    return n[0] + "*" * (len(n) - 2) + n[-1]


def is_priority(reserved_at, arrived_at):
    return reserved_at is not None and abs(arrived_at - reserved_at) <= PRIORITY_WINDOW_SEC


def assign_ticket(c, vid, service, day):
    prefix = SERVICES[service][1]
    seq = c.execute("SELECT COALESCE(MAX(ticket_seq),0)+1 FROM visits WHERE day=? AND service=?",
                    (day, service)).fetchone()[0]
    c.execute("UPDATE visits SET ticket_seq=?, ticket_no=? WHERE id=?", (seq, f"{prefix}{seq:03d}", vid))


def position(c, vid, service, day):
    ids = [r[0] for r in c.execute(
        f"SELECT id FROM visits WHERE day=? AND status='waiting' AND service=? ORDER BY {ORDER}", (day, service))]
    return ids.index(vid) if vid in ids else 0


def call_next(c, win, now):
    """창구 win 이 비어 있으면 자기 업무의 다음 고객을 호출. 호출된 id 또는 None."""
    busy = c.execute("SELECT 1 FROM visits WHERE win=? AND status IN ('called','serving')", (win,)).fetchone()
    if busy:
        return None
    row = c.execute(f"SELECT id FROM visits WHERE day=? AND status='waiting' AND service=? ORDER BY {ORDER} LIMIT 1",
                    (day_of(now), WINDOWS[win])).fetchone()
    if not row:
        return None
    c.execute("UPDATE visits SET status='called', win=?, called_at=? WHERE id=?", (win, now, row[0]))
    return row[0]


def tick():
    """호출 후 3분 지난 고객은 보류 처리하고 그 창구가 다음 번호를 호출."""
    now = int(time.time())
    with tx() as c:
        for r in c.execute("SELECT id, win FROM visits WHERE status='called' AND called_at<=?",
                           (now - CALL_TIMEOUT_SEC,)).fetchall():
            c.execute("UPDATE visits SET status='hold' WHERE id=?", (r["id"],))
            call_next(c, r["win"], now)


# ---------------------------------------------------------------- 인증
SESSIONS = {}
FAILS = {}  # (role, win) -> (횟수, 잠금 해제 시각)


def check_pin(role, win, pin):
    key = (role, win)
    cnt, until = FAILS.get(key, (0, 0))
    if until > time.time():
        raise HTTPException(429, "시도 횟수 초과. 잠시 후 다시 시도하세요.")
    expected = MANAGER_PIN if role == "manager" else TELLER_PINS.get(win, "")
    if not hmac.compare_digest(pin.encode(), expected.encode()):
        cnt += 1
        FAILS[key] = (cnt, time.time() + 60 if cnt >= 5 else 0)
        raise HTTPException(401, "PIN 이 올바르지 않습니다.")
    FAILS.pop(key, None)


def require(role):
    def dep(authorization: str = Header(None)):
        s = SESSIONS.get(authorization[7:]) if authorization and authorization.startswith("Bearer ") else None
        if not s or s["exp"] < time.time():
            raise HTTPException(401, "로그인이 필요합니다.")
        if s["role"] != role:
            raise HTTPException(403, "권한이 없습니다.")
        return s
    return dep


# ---------------------------------------------------------------- 모델
class Customer(BaseModel):
    name: str
    phone: str
    account: str
    service: Literal["deposit", "loan", "fx"]

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[가-힣A-Za-z ]{1,20}", v):
            raise ValueError("이름은 한글/영문 1~20자로 입력하세요.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        v = re.sub(r"\D", "", v)
        if not re.fullmatch(r"01\d{8,9}", v):
            raise ValueError("전화번호 형식이 올바르지 않습니다.")
        return v

    @field_validator("account")
    @classmethod
    def _acct(cls, v):
        v = re.sub(r"[\s-]", "", v)
        if not re.fullmatch(r"\d{8,20}", v):
            raise ValueError("계좌번호는 숫자 8~20자리로 입력하세요.")
        return v


class Reservation(Customer):
    reserved_at: int  # epoch seconds


class CheckIn(BaseModel):
    code: str
    phone: str


class Login(BaseModel):
    role: Literal["teller", "manager"]
    window: int | None = None
    pin: str


# ---------------------------------------------------------------- 앱
async def _ticker():
    while True:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(tick)
        await asyncio.sleep(2)


@contextlib.asynccontextmanager
async def lifespan(app):
    c = connect()
    c.executescript(SCHEMA)
    empty = c.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0
    c.close()
    if empty:
        from seed import seed
        with tx() as c:
            seed(c)
    task = asyncio.create_task(_ticker())
    yield
    task.cancel()


app = FastAPI(title="두둑은행 대기 현황판", lifespan=lifespan)


@app.middleware("http")
async def no_store(request, call_next_):
    resp = await call_next_(request)
    if request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---- 고객용 (공개)
@app.post("/api/reservations")
def reserve(r: Reservation):
    now = int(time.time())
    if not (now - PRIORITY_WINDOW_SEC <= r.reserved_at <= now + 30 * 86400):
        raise HTTPException(422, "예약 시각은 지금부터 30일 이내여야 합니다.")
    with tx() as c:
        code = next(x for x in (
            "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6)) for _ in range(50))
            if not c.execute("SELECT 1 FROM visits WHERE rcode=?", (x,)).fetchone())
        c.execute("""INSERT INTO visits(kind,name,phone,acct_last4,service,day,reserved_at,rcode,status,created_at)
                     VALUES('reserved',?,?,?,?,?,?,?,'booked',?)""",
                  (r.name, r.phone, r.account[-4:], r.service, day_of(r.reserved_at), r.reserved_at, code, now))
    return {"code": code, "reserved_at": r.reserved_at, "service": SERVICES[r.service][0]}


@app.post("/api/tickets")
def walkin(cu: Customer):
    now = int(time.time())
    day = day_of(now)
    with tx() as c:
        vid = c.execute("""INSERT INTO visits(kind,name,phone,acct_last4,service,day,order_at,status,created_at)
                           VALUES('walkin',?,?,?,?,?,?,'waiting',?)""",
                        (cu.name, cu.phone, cu.account[-4:], cu.service, day, now, now)).lastrowid
        assign_ticket(c, vid, cu.service, day)
        no = c.execute("SELECT ticket_no FROM visits WHERE id=?", (vid,)).fetchone()[0]
        ahead = position(c, vid, cu.service, day)
    return {"ticket_no": no, "ahead": ahead, "window": WINDOW_LABEL[cu.service], "priority": False}


@app.post("/api/checkin")
def checkin(ci: CheckIn):
    now = int(time.time())
    phone = re.sub(r"\D", "", ci.phone)
    bad = HTTPException(404, "예약을 찾을 수 없습니다. 예약번호와 전화번호를 확인하세요.")
    with tx() as c:
        v = c.execute("SELECT * FROM visits WHERE rcode=?", (ci.code.strip().upper(),)).fetchone()
        if not v or not hmac.compare_digest(v["phone"].encode(), phone.encode()):
            raise bad
        if v["status"] != "booked":
            raise HTTPException(409, "이미 접수된 예약입니다.")
        if v["day"] != day_of(now):
            raise HTTPException(409, "예약 당일에만 도착 접수가 가능합니다.")
        pr = 1 if is_priority(v["reserved_at"], now) else 0
        c.execute("UPDATE visits SET status='waiting', order_at=?, priority=? WHERE id=?", (now, pr, v["id"]))
        assign_ticket(c, v["id"], v["service"], v["day"])
        no = c.execute("SELECT ticket_no FROM visits WHERE id=?", (v["id"],)).fetchone()[0]
        ahead = position(c, v["id"], v["service"], v["day"])
    return {"ticket_no": no, "ahead": ahead, "window": WINDOW_LABEL[v["service"]], "priority": bool(pr)}


# ---- 대기 화면 (공개: 번호 · 가린 이름 · 창구 번호만)
@app.get("/api/display")
def display():
    day = day_of(int(time.time()))
    with rd() as c:
        called = [{"ticket": r["ticket_no"], "name": mask_name(r["name"]), "window": r["win"]}
                  for r in c.execute("SELECT * FROM visits WHERE day=? AND status='called' ORDER BY called_at DESC", (day,))]
        groups = []
        for svc in SERVICES:
            rows = c.execute(f"SELECT ticket_no, name FROM visits WHERE day=? AND status='waiting' AND service=? ORDER BY {ORDER}",
                             (day, svc)).fetchall()
            groups.append({"label": WINDOW_LABEL[svc],
                           "items": [{"ticket": r["ticket_no"], "name": mask_name(r["name"])} for r in rows[:8]],
                           "more": max(0, len(rows) - 8)})
    return {"called": called, "waiting": groups}


# ---- 인증
@app.post("/api/login")
def login(b: Login):
    win = b.window if b.role == "teller" else None
    if b.role == "teller" and win not in WINDOWS:
        raise HTTPException(422, "창구 번호가 올바르지 않습니다.")
    check_pin(b.role, win, b.pin)
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"role": b.role, "win": win, "exp": time.time() + 8 * 3600}
    return {"token": token, "window": win}


# ---- 창구 직원 (자기 창구 고객만)
def _teller_view(c, win):
    now = int(time.time())
    day = day_of(now)
    svc = WINDOWS[win]
    cur = c.execute("SELECT * FROM visits WHERE win=? AND status IN ('called','serving')", (win,)).fetchone()
    current = None
    if cur:
        current = {
            "id": cur["id"], "ticket_no": cur["ticket_no"], "status": cur["status"],
            "name": cur["name"], "phone": cur["phone"], "account_tail": cur["acct_last4"],
            "service": SERVICES[cur["service"]][0], "kind": cur["kind"],
            "reserved_at": cur["reserved_at"], "priority": bool(cur["priority"]),
            "seconds_left": max(0, CALL_TIMEOUT_SEC - (now - cur["called_at"])) if cur["status"] == "called" else None,
        }
    held = [{"id": r["id"], "ticket_no": r["ticket_no"], "name": r["name"]} for r in c.execute(
        "SELECT * FROM visits WHERE day=? AND win=? AND status='hold' ORDER BY called_at", (day, win))]
    waiting = c.execute("SELECT COUNT(*) FROM visits WHERE day=? AND status='waiting' AND service=?", (day, svc)).fetchone()[0]
    done = c.execute("SELECT COUNT(*) FROM visits WHERE day=? AND win=? AND status='done'", (day, win)).fetchone()[0]
    return {"window": win, "service": SERVICES[svc][0], "waiting": waiting, "done": done,
            "current": current, "held": held}


@app.get("/api/teller/state")
def teller_state(s=Depends(require("teller"))):
    with rd() as c:
        return _teller_view(c, s["win"])


@app.post("/api/teller/call-next")
def teller_call(s=Depends(require("teller"))):
    with tx() as c:
        if not call_next(c, s["win"], int(time.time())):
            raise HTTPException(409, "호출할 수 없습니다. (진행 중인 고객이 있거나 대기 고객이 없음)")
        return _teller_view(c, s["win"])


def _transition(s, src, sql, args=()):
    with tx() as c:
        n = c.execute(f"UPDATE visits SET {sql} WHERE win=? AND status=?", (*args, s["win"], src)).rowcount
        if not n:
            raise HTTPException(409, "처리할 고객이 없습니다. (이미 보류되었을 수 있음)")
        return _teller_view(c, s["win"])


@app.post("/api/teller/start")
def teller_start(s=Depends(require("teller"))):
    return _transition(s, "called", "status='serving', started_at=?", (int(time.time()),))


@app.post("/api/teller/finish")
def teller_finish(s=Depends(require("teller"))):
    return _transition(s, "serving", "status='done', finished_at=?", (int(time.time()),))


@app.post("/api/teller/requeue/{vid}")
def teller_requeue(vid: int, s=Depends(require("teller"))):
    now = int(time.time())
    with tx() as c:
        n = c.execute("""UPDATE visits SET status='waiting', win=NULL, called_at=NULL, priority=0, order_at=?
                         WHERE id=? AND win=? AND status='hold'""", (now, vid, s["win"])).rowcount
        if not n:
            raise HTTPException(404, "보류 고객을 찾을 수 없습니다.")
        return _teller_view(c, s["win"])


# ---- 지점장 (숫자만, 고객 식별정보 없음)
@app.get("/api/manager/summary")
def manager_summary(_=Depends(require("manager"))):
    now = int(time.time())
    day = day_of(now)
    with rd() as c:
        def n(sql, *a):
            return c.execute(sql, a).fetchone()[0]
        by = {}
        for svc, (label, _p) in SERVICES.items():
            by[svc] = {"label": label,
                       "waiting": n("SELECT COUNT(*) FROM visits WHERE day=? AND service=? AND status='waiting'", day, svc),
                       "called": n("SELECT COUNT(*) FROM visits WHERE day=? AND service=? AND status IN ('called','serving')", day, svc),
                       "done": n("SELECT COUNT(*) FROM visits WHERE day=? AND service=? AND status='done'", day, svc),
                       "hold": n("SELECT COUNT(*) FROM visits WHERE day=? AND service=? AND status='hold'", day, svc)}
        avg = c.execute("SELECT AVG(called_at-order_at) FROM visits WHERE day=? AND called_at IS NOT NULL AND order_at IS NOT NULL",
                        (day,)).fetchone()[0]
        return {
            "by_service": list(by.values()),
            "total_waiting": sum(x["waiting"] for x in by.values()),
            "reservations": n("SELECT COUNT(*) FROM visits WHERE day=? AND kind='reserved'", day),
            "priority_served": n("SELECT COUNT(*) FROM visits WHERE day=? AND kind='reserved' AND priority=1", day),
            "walkins": n("SELECT COUNT(*) FROM visits WHERE day=? AND kind='walkin'", day),
            # 노쇼: 예약 시각+10분이 지나도 도착 접수가 없는 예약
            "noshow": n("SELECT COUNT(*) FROM visits WHERE day=? AND status='booked' AND reserved_at<?",
                        day, now - PRIORITY_WINDOW_SEC),
            "upcoming": n("SELECT COUNT(*) FROM visits WHERE day=? AND status='booked' AND reserved_at>=?",
                          day, now - PRIORITY_WINDOW_SEC),
            "hold": sum(x["hold"] for x in by.values()),
            "avg_wait_min": round(avg / 60, 1) if avg is not None else None,
            "updated": now,
        }


# ---- 정적 페이지
for _p, _f in {"/": "index.html", "/display": "display.html", "/teller": "teller.html", "/manager": "manager.html"}.items():
    app.add_api_route(_p, (lambda f=_f: FileResponse(os.path.join(BASE, "static", f))), include_in_schema=False)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
