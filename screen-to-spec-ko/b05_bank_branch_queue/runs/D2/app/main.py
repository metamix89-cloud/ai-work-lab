import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

BASE = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DUDUK_DB", str(BASE.parent / "duduk.db"))

PRIORITY_WINDOW = timedelta(minutes=10)   # 예약 시각 앞뒤 10분
CALL_TIMEOUT = timedelta(minutes=3)       # 호출 후 3분
NOSHOW_AFTER = timedelta(minutes=30)      # 예약 시각 +30분까지 미도착이면 노쇼 (운영 가정)
OPEN_HOUR, CLOSE_HOUR = 9, 16             # 예약 가능 시간 (운영 가정)

PREFIX = {"예금": "A", "대출": "B", "외환": "C"}
COUNTER_SERVICE = {1: "예금", 2: "예금", 3: "대출", 4: "외환"}
SERVICE_COUNTERS = {"예금": [1, 2], "대출": [3], "외환": [4]}

# 데모용 PIN. 실제 운영에서는 환경변수로 바꿔야 함.
PINS = {
    "counter:1": os.environ.get("DUDUK_PIN_C1", "1111"),
    "counter:2": os.environ.get("DUDUK_PIN_C2", "2222"),
    "counter:3": os.environ.get("DUDUK_PIN_C3", "3333"),
    "counter:4": os.environ.get("DUDUK_PIN_C4", "4444"),
    "manager": os.environ.get("DUDUK_PIN_MANAGER", "9999"),
}
SESSION_TTL = timedelta(hours=12)
SESSIONS: dict[str, dict] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service TEXT NOT NULL,
  number TEXT,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  account TEXT NOT NULL,
  kind TEXT NOT NULL,            -- walkin | reserved
  reserved_at TEXT,
  arrived_at TEXT,
  priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,          -- reserved waiting called serving done hold noshow
  counter INTEGER,
  called_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets(service, status);
"""


# ---------- 공통 ----------
def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def today0() -> str:
    return iso(now().replace(hour=0, minute=0, second=0))


@contextmanager
def tx():
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def mask_name(n: str) -> str:
    if len(n) <= 1:
        return n
    if len(n) == 2:
        return n[0] + "*"
    return n[0] + "*" * (len(n) - 2) + n[-1]


def fmt_phone(d: str) -> str:
    return f"{d[:3]}-{d[3:-4]}-{d[-4:]}" if len(d) >= 10 else d


def account_tail(a: str) -> str:
    digits = re.sub(r"\D", "", a)
    return "****" + digits[-4:]


# ---------- 대기열 규칙 ----------
def add_ticket(c, *, name, phone, account, service, kind, reserved_at=None,
               arrived_at=None, status=None, counter=None, called_at=None,
               finished_at=None):
    number, priority = None, 0
    if arrived_at is not None:
        number = next_number(c, service)
        if kind == "reserved" and reserved_at is not None:
            priority = int(abs(datetime.fromisoformat(arrived_at)
                               - datetime.fromisoformat(reserved_at)) <= PRIORITY_WINDOW)
    cur = c.execute(
        "INSERT INTO tickets(service,number,name,phone,account,kind,reserved_at,arrived_at,"
        "priority,status,counter,called_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (service, number, name, phone, account, kind, reserved_at, arrived_at, priority,
         status or ("waiting" if arrived_at else "reserved"), counter, called_at, finished_at))
    return cur.lastrowid


def next_number(c, service) -> str:
    n = c.execute("SELECT COUNT(*) FROM tickets WHERE service=? AND number IS NOT NULL "
                  "AND arrived_at>=?", (service, today0())).fetchone()[0]
    return f"{PREFIX[service]}{n + 1:03d}"


def ordered_waiting(c, service):
    """우선(예약 ±10분 도착) → 예약 시각순, 그 다음 일반 → 도착순."""
    rows = c.execute("SELECT * FROM tickets WHERE service=? AND status='waiting' AND arrived_at>=?",
                     (service, today0())).fetchall()
    rows.sort(key=lambda r: (0, r["reserved_at"], r["id"]) if r["priority"]
              else (1, r["arrived_at"], r["id"]))
    return rows


def active_ticket(c, counter):
    return c.execute("SELECT * FROM tickets WHERE counter=? AND status IN ('called','serving') "
                     "ORDER BY id DESC LIMIT 1", (counter,)).fetchone()


def call_next_for(c, counter):
    if active_ticket(c, counter):
        return None
    queue = ordered_waiting(c, COUNTER_SERVICE[counter])
    if not queue:
        return None
    t = queue[0]
    c.execute("UPDATE tickets SET status='called', counter=?, called_at=? WHERE id=?",
              (counter, iso(now()), t["id"]))
    return t["id"]


def sweep():
    """노쇼 / 호출 3분 초과 보류 처리. 보류되면 그 창구가 다음 번호를 호출."""
    with tx() as c:
        n = now()
        c.execute("UPDATE tickets SET status='noshow' WHERE status='reserved' AND reserved_at<?",
                  (iso(n - NOSHOW_AFTER),))
        expired = c.execute("SELECT id, counter FROM tickets WHERE status='called' AND called_at<=?",
                            (iso(n - CALL_TIMEOUT),)).fetchall()
        for r in expired:
            c.execute("UPDATE tickets SET status='hold' WHERE id=?", (r["id"],))
            call_next_for(c, r["counter"])


# ---------- 인증 ----------
def require(role):
    def dep(x_token: str | None = Header(default=None)):
        s = SESSIONS.get(x_token or "")
        if not s or s["exp"] < now():
            raise HTTPException(401, "로그인이 필요합니다")
        if s["role"] != role:
            raise HTTPException(403, "권한이 없습니다")
        return s
    return dep


class LoginIn(BaseModel):
    role: str
    counter: int | None = None
    pin: str


# ---------- 입력 모델 ----------
class CustomerIn(BaseModel):
    name: str
    phone: str
    account: str
    service: str

    @field_validator("name")
    @classmethod
    def v_name(cls, v):
        v = v.strip()
        if not 2 <= len(v) <= 10 or re.search(r"[\s\d]", v):
            raise ValueError("이름을 확인해 주세요")
        return v

    @field_validator("phone")
    @classmethod
    def v_phone(cls, v):
        d = re.sub(r"\D", "", v)
        if not re.fullmatch(r"01\d{8,9}", d):
            raise ValueError("전화번호를 확인해 주세요")
        return d

    @field_validator("account")
    @classmethod
    def v_account(cls, v):
        if not re.fullmatch(r"[\d-]+", v.strip()) or not 8 <= len(re.sub(r"\D", "", v)) <= 16:
            raise ValueError("계좌번호를 확인해 주세요")
        return v.strip()

    @field_validator("service")
    @classmethod
    def v_service(cls, v):
        if v not in PREFIX:
            raise ValueError("업무 종류를 확인해 주세요")
        return v


class ReservationIn(CustomerIn):
    reserved_at: str

    @field_validator("reserved_at")
    @classmethod
    def v_when(cls, v):
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("예약 시각을 확인해 주세요")
        if dt <= now() or dt > now() + timedelta(days=7):
            raise ValueError("예약은 지금부터 7일 이내만 가능합니다")
        if not (OPEN_HOUR <= dt.hour < CLOSE_HOUR):
            raise ValueError(f"예약 가능 시간은 {OPEN_HOUR}시~{CLOSE_HOUR}시입니다")
        return iso(dt.replace(second=0))


class CheckinIn(BaseModel):
    phone: str
    account_last4: str


# ---------- 앱 ----------
app = FastAPI(title="두둑은행 방문 예약 · 대기 현황판")


@app.on_event("startup")
def _startup():
    init_db()
    from app.seed import seed_if_empty
    seed_if_empty()


@app.post("/api/login")
def login(body: LoginIn):
    if body.role == "counter" and body.counter in COUNTER_SERVICE:
        key = f"counter:{body.counter}"
    elif body.role == "manager":
        key = "manager"
    else:
        raise HTTPException(400, "잘못된 요청")
    if not secrets.compare_digest(PINS[key], body.pin):
        raise HTTPException(401, "PIN이 맞지 않습니다")
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = {"role": body.role, "counter": body.counter, "exp": now() + SESSION_TTL}
    return {"token": token}


# --- 고객 (키오스크) ---
@app.post("/api/reservations")
def reserve(body: ReservationIn):
    with tx() as c:
        add_ticket(c, name=body.name, phone=body.phone, account=body.account,
                   service=body.service, kind="reserved", reserved_at=body.reserved_at)
    return {"name": mask_name(body.name), "service": body.service, "reserved_at": body.reserved_at}


@app.post("/api/walkin")
def walkin(body: CustomerIn):
    with tx() as c:
        tid = add_ticket(c, name=body.name, phone=body.phone, account=body.account,
                         service=body.service, kind="walkin", arrived_at=iso(now()))
        number = c.execute("SELECT number FROM tickets WHERE id=?", (tid,)).fetchone()[0]
        ahead = [r["id"] for r in ordered_waiting(c, body.service)]
        return {"number": number, "ahead": ahead.index(tid),
                "counters": SERVICE_COUNTERS[body.service]}


@app.post("/api/checkin")
def checkin(body: CheckinIn):
    phone = re.sub(r"\D", "", body.phone)
    tail = re.sub(r"\D", "", body.account_last4)
    with tx() as c:
        rows = c.execute("SELECT * FROM tickets WHERE phone=? AND kind='reserved' "
                         "AND status IN ('reserved','waiting') AND reserved_at>=? AND reserved_at<? "
                         "ORDER BY reserved_at", (phone, today0(), iso(now().replace(
                             hour=23, minute=59, second=59)))).fetchall()
        row = next((r for r in rows if re.sub(r"\D", "", r["account"]).endswith(tail) and len(tail) == 4), None)
        if not row:
            raise HTTPException(404, "오늘 예약을 찾을 수 없습니다")
        if row["status"] == "reserved":
            n = iso(now())
            number = next_number(c, row["service"])
            prio = int(abs(now() - datetime.fromisoformat(row["reserved_at"])) <= PRIORITY_WINDOW)
            c.execute("UPDATE tickets SET status='waiting', arrived_at=?, number=?, priority=? WHERE id=?",
                      (n, number, prio, row["id"]))
            row = c.execute("SELECT * FROM tickets WHERE id=?", (row["id"],)).fetchone()
        ahead = [r["id"] for r in ordered_waiting(c, row["service"])]
        return {"number": row["number"], "name": mask_name(row["name"]), "priority": bool(row["priority"]),
                "ahead": ahead.index(row["id"]) if row["id"] in ahead else 0,
                "counters": SERVICE_COUNTERS[row["service"]]}


# --- 대기 화면 (공개: 번호 · 가린 이름 · 창구 번호만) ---
@app.get("/api/display")
def display():
    sweep()
    with tx() as c:
        calling = []
        for counter in COUNTER_SERVICE:
            t = active_ticket(c, counter)
            calling.append({"counter": counter,
                            "number": t["number"] if t else None,
                            "name": mask_name(t["name"]) if t else None})
        waiting = []
        for service, counters in SERVICE_COUNTERS.items():
            for r in ordered_waiting(c, service):
                waiting.append({"number": r["number"], "name": mask_name(r["name"]),
                                "counters": counters, "_t": r["arrived_at"]})
        waiting.sort(key=lambda w: w["_t"])
        for w in waiting:
            del w["_t"]
    return {"calling": calling, "waiting": waiting}


# --- 창구 직원 ---
def _detail(t):
    left = None
    if t["status"] == "called":
        left = max(0, int((datetime.fromisoformat(t["called_at"]) + CALL_TIMEOUT - now()).total_seconds()))
    return {"id": t["id"], "number": t["number"], "name": t["name"], "phone": fmt_phone(t["phone"]),
            "account": account_tail(t["account"]), "service": t["service"], "kind": t["kind"],
            "reserved_at": t["reserved_at"], "priority": bool(t["priority"]),
            "status": t["status"], "seconds_left": left}


@app.get("/api/counter/state")
def counter_state(s=Depends(require("counter"))):
    sweep()
    counter = s["counter"]
    with tx() as c:
        cur = active_ticket(c, counter)
        holds = c.execute("SELECT id, number, name FROM tickets WHERE counter=? AND status='hold' "
                          "AND called_at>=? ORDER BY id", (counter, today0())).fetchall()
        return {"counter": counter, "service": COUNTER_SERVICE[counter],
                "current": _detail(cur) if cur else None,
                "waiting": [{"number": r["number"], "name": mask_name(r["name"]),
                             "priority": bool(r["priority"])}
                            for r in ordered_waiting(c, COUNTER_SERVICE[counter])],
                "hold": [{"id": r["id"], "number": r["number"], "name": mask_name(r["name"])} for r in holds]}


@app.post("/api/counter/call-next")
def counter_call(s=Depends(require("counter"))):
    sweep()
    with tx() as c:
        if active_ticket(c, s["counter"]):
            raise HTTPException(409, "현재 고객 응대를 먼저 마쳐 주세요")
        if call_next_for(c, s["counter"]) is None:
            raise HTTPException(404, "대기 고객이 없습니다")
    return {"ok": True}


@app.post("/api/counter/start")
def counter_start(s=Depends(require("counter"))):
    sweep()
    with tx() as c:
        t = active_ticket(c, s["counter"])
        if not t or t["status"] != "called":
            raise HTTPException(409, "호출 중인 고객이 없습니다")
        c.execute("UPDATE tickets SET status='serving' WHERE id=?", (t["id"],))
    return {"ok": True}


@app.post("/api/counter/finish")
def counter_finish(s=Depends(require("counter"))):
    with tx() as c:
        t = active_ticket(c, s["counter"])
        if not t or t["status"] != "serving":
            raise HTTPException(409, "응대 중인 고객이 없습니다")
        c.execute("UPDATE tickets SET status='done', finished_at=? WHERE id=?", (iso(now()), t["id"]))
    return {"ok": True}


@app.post("/api/counter/requeue/{ticket_id}")
def counter_requeue(ticket_id: int, s=Depends(require("counter"))):
    """보류 고객이 뒤늦게 온 경우: 일반 고객으로 다시 줄 서기 (본인 창구 보류분만)."""
    with tx() as c:
        t = c.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if not t or t["status"] != "hold" or t["counter"] != s["counter"]:
            raise HTTPException(404, "해당 보류 고객이 없습니다")
        c.execute("UPDATE tickets SET status='waiting', priority=0, arrived_at=?, counter=NULL, "
                  "called_at=NULL WHERE id=?", (iso(now()), ticket_id))
    return {"ok": True}


# --- 지점장: 숫자만 ---
@app.get("/api/manager/stats")
def manager_stats(s=Depends(require("manager"))):
    sweep()
    with tx() as c:
        rows = c.execute("SELECT service, status, arrived_at, called_at, reserved_at, priority FROM tickets "
                         "WHERE COALESCE(arrived_at, reserved_at)>=?", (today0(),)).fetchall()
    out = {}
    for service in PREFIX:
        mine = [r for r in rows if r["service"] == service]
        count = lambda st: sum(r["status"] == st for r in mine)
        waits = [(datetime.fromisoformat(r["called_at"]) - datetime.fromisoformat(r["arrived_at"])).total_seconds() / 60
                 for r in mine if r["called_at"] and r["arrived_at"]]
        cur_waits = [(now() - datetime.fromisoformat(r["arrived_at"])).total_seconds() / 60
                     for r in mine if r["status"] == "waiting"]
        out[service] = {"counters": SERVICE_COUNTERS[service],
                        "waiting": count("waiting"), "priority_waiting": sum(r["status"] == "waiting" and r["priority"] for r in mine),
                        "in_service": count("called") + count("serving"), "done": count("done"),
                        "hold": count("hold"), "noshow": count("noshow"), "reserved_pending": count("reserved"),
                        "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else None,
                        "longest_wait_min": round(max(cur_waits)) if cur_waits else 0}
    keys = ["waiting", "in_service", "done", "hold", "noshow", "reserved_pending"]
    total = {k: sum(v[k] for v in out.values()) for k in keys}
    return {"services": out, "total": total, "updated": iso(now())}


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
