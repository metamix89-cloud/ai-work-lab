"""두둑은행 지점 방문 예약 · 대기 현황판"""
import hmac
import os
import re
import sys
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DUDUK_DB", str(BASE / "duduk.db"))

# ---- 지점 규칙 ----
PRIORITY_WINDOW = timedelta(minutes=10)   # 예약 시각 앞뒤 10분
CALL_TIMEOUT = timedelta(minutes=3)       # 호출 후 3분
COUNTERS = {1: ("예금",), 2: ("예금",), 3: ("대출",), 4: ("외환",)}
SERVICES = ("예금", "대출", "외환")

# 데모용 PIN. 운영 시 환경변수로 반드시 교체.
STAFF_PINS = {int(c): p for c, p in
              zip(COUNTERS, os.environ.get("DUDUK_STAFF_PINS", "1111,2222,3333,4444").split(","))}
MANAGER_PIN = os.environ.get("DUDUK_MANAGER_PIN", "9999")

lock = threading.RLock()
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def init_db():
    db.executescript("""
    CREATE TABLE IF NOT EXISTS visits(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      day TEXT NOT NULL,
      kind TEXT NOT NULL,             -- reservation | walkin
      name TEXT NOT NULL,
      phone TEXT NOT NULL,
      account_last4 TEXT NOT NULL,    -- 계좌 전체는 저장하지 않음
      service TEXT NOT NULL,
      reserved_at TEXT,
      code TEXT UNIQUE,
      status TEXT NOT NULL,           -- reserved|waiting|called|serving|done|hold|noshow
      ticket_no INTEGER,
      priority INTEGER NOT NULL DEFAULT 0,
      queued_at TEXT,
      called_counter INTEGER,
      called_at TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_status ON visits(status, day);
    """)
    db.commit()


# ---- 마스킹 ----
def mask_name(n: str) -> str:
    if len(n) <= 1:
        return n
    if len(n) == 2:
        return n[0] + "*"
    return n[0] + "*" * (len(n) - 2) + n[-1]


# ---- 큐 로직 (lock 안에서 호출) ----
def next_ticket() -> int:
    r = db.execute("SELECT COALESCE(MAX(ticket_no),0)+1 FROM visits WHERE day=? AND ticket_no IS NOT NULL",
                   (iso(now())[:10],)).fetchone()
    return r[0]


def order_key(r) -> tuple:
    # 우선(예약 시각 순) → 일반(대기열 진입 순)
    if r["priority"]:
        return (0, r["reserved_at"], r["ticket_no"])
    return (1, r["queued_at"], r["ticket_no"])


def waiting_rows(services=None):
    rows = db.execute("SELECT * FROM visits WHERE status='waiting' AND day=?", (iso(now())[:10],)).fetchall()
    if services:
        rows = [r for r in rows if r["service"] in services]
    return sorted(rows, key=order_key)


def call_next_locked(counter: int):
    busy = db.execute("SELECT 1 FROM visits WHERE called_counter=? AND status IN('called','serving')",
                      (counter,)).fetchone()
    if busy:
        return None
    q = waiting_rows(COUNTERS[counter])
    if not q:
        return None
    r = q[0]
    db.execute("UPDATE visits SET status='called', called_counter=?, called_at=? WHERE id=?",
               (counter, iso(now()), r["id"]))
    db.commit()
    return r["id"]


def sweep():
    """호출 3분 초과 → 보류 후 다음 번호 호출. 예약 +10분 지나도 미도착 → 노쇼."""
    with lock:
        t = now()
        for r in db.execute("SELECT id, called_counter, called_at FROM visits WHERE status='called'").fetchall():
            if t - datetime.fromisoformat(r["called_at"]) >= CALL_TIMEOUT:
                db.execute("UPDATE visits SET status='hold' WHERE id=?", (r["id"],))
                db.commit()
                call_next_locked(r["called_counter"])
        limit = iso(t - PRIORITY_WINDOW)
        db.execute("UPDATE visits SET status='noshow' WHERE status='reserved' AND reserved_at < ?", (limit,))
        db.commit()


def checkin_locked(r, t: datetime):
    pri = 0
    if r["kind"] == "reservation":
        pri = int(abs(t - datetime.fromisoformat(r["reserved_at"])) <= PRIORITY_WINDOW)
    tk = next_ticket()
    db.execute("UPDATE visits SET status='waiting', ticket_no=?, priority=?, queued_at=? WHERE id=?",
               (tk, pri, iso(t), r["id"]))
    db.commit()
    return tk


# ---- 인증 ----
sessions: dict[str, dict] = {}
fails: dict[str, list] = {}


def login(role: str, counter, pin: str) -> str:
    key = f"{role}:{counter}"
    f = fails.get(key, [0, 0.0])
    if f[0] >= 5 and time.time() < f[1]:
        raise HTTPException(429, "시도 횟수 초과. 잠시 후 다시 시도하세요.")
    expected = STAFF_PINS.get(counter, "") if role == "staff" else MANAGER_PIN
    if not hmac.compare_digest(pin.encode(), expected.encode()):
        f[0] += 1
        f[1] = time.time() + 60
        fails[key] = f
        raise HTTPException(401, "PIN이 올바르지 않습니다.")
    fails.pop(key, None)
    tok = secrets.token_urlsafe(24)
    sessions[tok] = {"role": role, "counter": counter, "exp": time.time() + 12 * 3600}
    return tok


def auth(role: str):
    def dep(authorization: str = Header(default="")):
        s = sessions.get(authorization.removeprefix("Bearer ").strip())
        if not s or s["exp"] < time.time() or s["role"] != role:
            raise HTTPException(401, "로그인이 필요합니다.")
        return s
    return dep


# ---- 스키마 ----
class Person(BaseModel):
    name: str = Field(min_length=2, max_length=20)
    phone: str
    account: str
    service: Literal["예금", "대출", "외환"]

    @field_validator("name")
    @classmethod
    def v_name(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[가-힣A-Za-z ]{2,20}", v):
            raise ValueError("이름 형식 오류")
        return v

    @field_validator("phone")
    @classmethod
    def v_phone(cls, v):
        d = re.sub(r"\D", "", v)
        if not re.fullmatch(r"01\d{8,9}", d):
            raise ValueError("전화번호 형식 오류")
        return d

    @field_validator("account")
    @classmethod
    def v_acc(cls, v):
        d = re.sub(r"[-\s]", "", v)
        if not re.fullmatch(r"\d{8,20}", d):
            raise ValueError("계좌번호 형식 오류")
        return d


class Reserve(Person):
    reserved_at: datetime


class CheckIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class StaffLogin(BaseModel):
    counter: int
    pin: str = Field(max_length=32)


class MgrLogin(BaseModel):
    pin: str = Field(max_length=32)


def new_code() -> str:
    while True:
        c = f"{secrets.randbelow(10**6):06d}"
        if not db.execute("SELECT 1 FROM visits WHERE code=?", (c,)).fetchone():
            return c


def insert(p: Person, kind, status, reserved_at=None, code=None, ticket=None, pri=0, queued=None):
    t = now()
    cur = db.execute(
        "INSERT INTO visits(day,kind,name,phone,account_last4,service,reserved_at,code,status,ticket_no,priority,queued_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (iso(reserved_at or t)[:10], kind, p.name, p.phone, p.account[-4:], p.service,
         iso(reserved_at) if reserved_at else None, code, status, ticket, pri, queued))
    db.commit()
    return cur.lastrowid


# ---- 앱 ----
def bg():
    while True:
        time.sleep(5)
        try:
            sweep()
        except Exception as e:  # 백그라운드 스레드가 죽지 않게
            print("sweep error", e)


@asynccontextmanager
async def lifespan(app):
    init_db()
    from seed import seed
    with lock:
        seed(sys.modules[__name__])
    threading.Thread(target=bg, daemon=True).start()
    yield

app = FastAPI(title="두둑은행 대기 현황판", lifespan=lifespan)


@app.post("/api/reserve")
def reserve(b: Reserve):
    t = now()
    if b.reserved_at < t or b.reserved_at > t + timedelta(days=14):
        raise HTTPException(400, "예약 시각은 지금부터 14일 이내여야 합니다.")
    if not (9 <= b.reserved_at.hour < 16):
        raise HTTPException(400, "예약은 09:00~16:00 사이만 가능합니다.")
    with lock:
        code = new_code()
        insert(b, "reservation", "reserved", reserved_at=b.reserved_at.replace(tzinfo=None, microsecond=0), code=code)
    return {"code": code, "reserved_at": iso(b.reserved_at)}


@app.post("/api/checkin")
def checkin(b: CheckIn):
    sweep()
    with lock:
        r = db.execute("SELECT * FROM visits WHERE code=?", (b.code,)).fetchone()
        if not r or r["status"] != "reserved":
            raise HTTPException(404, "도착 확인할 수 있는 예약이 아닙니다. (없음·노쇼·이미 접수)")
        if r["day"] != iso(now())[:10]:
            raise HTTPException(400, "예약 당일에만 도착 확인이 가능합니다.")
        tk = checkin_locked(r, now())
    return {"ticket_no": tk}


@app.post("/api/walkin")
def walkin(b: Person):
    with lock:
        t = now()
        tk = next_ticket()
        insert(b, "walkin", "waiting", ticket=tk, queued=iso(t))
    return {"ticket_no": tk}


@app.get("/api/display")
def display():
    """공용 모니터용: 번호 · 가린 이름 · 창구 번호만."""
    sweep()
    with lock:
        calling = db.execute(
            "SELECT * FROM visits WHERE status IN('called','serving') ORDER BY called_counter").fetchall()
        waiting = waiting_rows()
    return {
        "calling": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"]),
                     "counter": r["called_counter"], "state": r["status"]} for r in calling],
        "waiting": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"])} for r in waiting],
    }


# ---- 창구 직원 ----
@app.post("/api/staff/login")
def staff_login(b: StaffLogin):
    if b.counter not in COUNTERS:
        raise HTTPException(400, "없는 창구")
    return {"token": login("staff", b.counter, b.pin), "counter": b.counter, "services": COUNTERS[b.counter]}


def detail(r):
    return {"id": r["id"], "ticket_no": r["ticket_no"], "name": r["name"], "phone": r["phone"],
            "account": "****" + r["account_last4"], "service": r["service"], "state": r["status"],
            "kind": r["kind"], "reserved_at": r["reserved_at"], "called_at": r["called_at"]}


@app.get("/api/staff/me")
def staff_me(s=Depends(auth("staff"))):
    sweep()
    c = s["counter"]
    with lock:
        cur = db.execute("SELECT * FROM visits WHERE called_counter=? AND status IN('called','serving')",
                         (c,)).fetchone()
        holds = db.execute("SELECT * FROM visits WHERE called_counter=? AND status='hold' AND day=?",
                           (c, iso(now())[:10])).fetchall()
        q = waiting_rows(COUNTERS[c])
    return {"counter": c, "services": COUNTERS[c], "waiting_count": len(q),
            "current": detail(cur) if cur else None,
            "holds": [{"id": h["id"], "ticket_no": h["ticket_no"], "name": mask_name(h["name"])} for h in holds]}


@app.post("/api/staff/call-next")
def staff_call(s=Depends(auth("staff"))):
    sweep()
    with lock:
        if not call_next_locked(s["counter"]):
            raise HTTPException(409, "호출할 고객이 없거나 이미 호출·응대 중입니다.")
    return {"ok": True}


def own_current(c):
    r = db.execute("SELECT * FROM visits WHERE called_counter=? AND status IN('called','serving')", (c,)).fetchone()
    if not r:
        raise HTTPException(409, "현재 호출한 고객이 없습니다.")
    return r


@app.post("/api/staff/start")
def staff_start(s=Depends(auth("staff"))):
    sweep()
    with lock:
        r = own_current(s["counter"])
        if r["status"] != "called":
            raise HTTPException(409, "이미 응대 중입니다.")
        db.execute("UPDATE visits SET status='serving' WHERE id=?", (r["id"],))
        db.commit()
    return {"ok": True}


@app.post("/api/staff/finish")
def staff_finish(s=Depends(auth("staff"))):
    with lock:
        r = own_current(s["counter"])
        if r["status"] != "serving":
            raise HTTPException(409, "응대를 시작하지 않았습니다.")
        db.execute("UPDATE visits SET status='done' WHERE id=?", (r["id"],))
        db.commit()
    return {"ok": True}


@app.post("/api/staff/requeue/{vid}")
def staff_requeue(vid: int, s=Depends(auth("staff"))):
    """보류 고객이 뒤늦게 나타나면 일반 대기열 맨 뒤로 복귀 (본인 창구가 보류한 건만)."""
    with lock:
        r = db.execute("SELECT * FROM visits WHERE id=? AND status='hold' AND called_counter=?",
                       (vid, s["counter"])).fetchone()
        if not r:
            raise HTTPException(404, "해당 보류 고객이 없습니다.")
        db.execute("UPDATE visits SET status='waiting', priority=0, queued_at=? WHERE id=?",
                   (iso(now()), vid))
        db.commit()
    return {"ok": True}


# ---- 지점장 (숫자만) ----
@app.post("/api/manager/login")
def mgr_login(b: MgrLogin):
    return {"token": login("manager", None, b.pin)}


@app.get("/api/manager/stats")
def mgr_stats(_=Depends(auth("manager"))):
    sweep()
    day = iso(now())[:10]
    with lock:
        by_status = {k: 0 for k in ("reserved", "waiting", "called", "serving", "done", "hold", "noshow")}
        for r in db.execute("SELECT status, COUNT(*) n FROM visits WHERE day=? GROUP BY status", (day,)):
            by_status[r["status"]] = r["n"]
        wait_by = {s: 0 for s in SERVICES}
        for r in db.execute("SELECT service, COUNT(*) n FROM visits WHERE day=? AND status='waiting' GROUP BY service",
                            (day,)):
            wait_by[r["service"]] = r["n"]
        total_res = db.execute("SELECT COUNT(*) FROM visits WHERE day=? AND kind='reservation'", (day,)).fetchone()[0]
    ns = by_status["noshow"]
    return {"by_status": by_status, "waiting_by_service": wait_by, "reservations_total": total_res,
            "noshow": ns, "noshow_rate": round(ns / total_res * 100, 1) if total_res else 0.0}


@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
