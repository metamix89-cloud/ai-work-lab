"""두둑은행 지점 방문 예약 · 대기 현황판."""
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DUDUK_DB", str(BASE.parent / "duduk.db"))

# ---- 지점 규칙 -------------------------------------------------------------
PRIORITY_WINDOW = timedelta(minutes=10)   # 예약 시각 앞뒤 10분
CALL_TIMEOUT = timedelta(minutes=3)       # 호출 후 3분 내 미도착 -> 보류
SERVICES = {"deposit": "예금", "loan": "대출", "fx": "외환"}
PREFIX = {"deposit": "A", "loan": "B", "fx": "C"}
WINDOW_SERVICE = {1: "deposit", 2: "deposit", 3: "loan", 4: "fx"}

# 데모용 PIN (운영 시 환경변수로 교체)
TELLER_PINS = {w: os.environ.get(f"TELLER{w}_PIN", f"{1110 + w}") for w in WINDOW_SERVICE}
MANAGER_PIN = os.environ.get("MANAGER_PIN", "9999")

lock = threading.RLock()
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_no TEXT,
  service TEXT NOT NULL,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  account TEXT NOT NULL,
  source TEXT NOT NULL,            -- reservation | walkin
  reservation_code TEXT UNIQUE,
  reserved_at TEXT,
  arrived_at TEXT,
  status TEXT NOT NULL,            -- reserved waiting called serving done hold noshow
  window INTEGER,
  called_at TEXT,
  ended_at TEXT
);
"""


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(d: datetime | None) -> str | None:
    return d.isoformat(timespec="seconds") if d else None


def parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


# ---- 마스킹 ----------------------------------------------------------------
def mask_name(name: str) -> str:
    if len(name) <= 1:
        return name
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def mask_account(acc: str) -> str:
    return "****-" + acc[-4:]


def mask_phone(p: str) -> str:
    return "***-****-" + p[-4:]


# ---- 큐 로직 ---------------------------------------------------------------
def is_priority(r: sqlite3.Row) -> bool:
    if r["source"] != "reservation" or not r["reserved_at"] or not r["arrived_at"]:
        return False
    return abs(parse(r["arrived_at"]) - parse(r["reserved_at"])) <= PRIORITY_WINDOW


def queue_key(r: sqlite3.Row):
    # 우선 대상은 예약 시각 순, 나머지는 도착 순
    if is_priority(r):
        return (0, parse(r["reserved_at"]), r["id"])
    return (1, parse(r["arrived_at"]), r["id"])


def waiting_sorted(service: str | None = None) -> list[sqlite3.Row]:
    q = "SELECT * FROM tickets WHERE status='waiting'"
    args: tuple = ()
    if service:
        q += " AND service=?"
        args = (service,)
    return sorted(db.execute(q, args).fetchall(), key=queue_key)


def issue_number(service: str, d: datetime) -> str:
    day = d.date().isoformat()
    n = db.execute(
        "SELECT COUNT(*) FROM tickets WHERE service=? AND ticket_no IS NOT NULL AND arrived_at LIKE ?",
        (service, day + "%"),
    ).fetchone()[0]
    return f"{PREFIX[service]}{n + 1:03d}"


def call_next(window: int) -> sqlite3.Row | None:
    """창구는 자기 업무 고객만 호출한다."""
    busy = db.execute(
        "SELECT 1 FROM tickets WHERE window=? AND status IN ('called','serving')", (window,)
    ).fetchone()
    if busy:
        return None
    q = waiting_sorted(WINDOW_SERVICE[window])
    if not q:
        return None
    t = q[0]
    db.execute(
        "UPDATE tickets SET status='called', window=?, called_at=? WHERE id=?",
        (window, iso(now()), t["id"]),
    )
    db.commit()
    return db.execute("SELECT * FROM tickets WHERE id=?", (t["id"],)).fetchone()


def sweep():
    """호출 3분 초과 -> 보류 후 다음 번호 호출. 예약 시각+10분 경과 미도착 -> 노쇼."""
    with lock:
        n = now()
        for r in db.execute("SELECT * FROM tickets WHERE status='called'").fetchall():
            if n - parse(r["called_at"]) > CALL_TIMEOUT:
                db.execute("UPDATE tickets SET status='hold', ended_at=? WHERE id=?", (iso(n), r["id"]))
                db.commit()
                call_next(r["window"])
        for r in db.execute("SELECT * FROM tickets WHERE status='reserved'").fetchall():
            if n > parse(r["reserved_at"]) + PRIORITY_WINDOW:
                db.execute("UPDATE tickets SET status='noshow' WHERE id=?", (r["id"],))
        db.commit()


def sweeper_loop():
    while True:
        time.sleep(5)
        try:
            sweep()
        except Exception:
            pass


# ---- 인증 (창구 PIN / 지점장 PIN -> 토큰) -----------------------------------
sessions: dict[str, dict] = {}
fails: dict[str, list] = {}


class LoginIn(BaseModel):
    role: str = Field(pattern="^(teller|manager)$")
    window: int | None = None
    pin: str = Field(max_length=20)


def current_session(authorization: str = Header(default="")) -> dict:
    s = sessions.get(authorization.removeprefix("Bearer ").strip())
    if not s:
        raise HTTPException(401, "로그인이 필요합니다")
    return s


def teller_only(s: dict = Depends(current_session)) -> dict:
    if s["role"] != "teller":
        raise HTTPException(403, "창구 직원만 사용할 수 있습니다")
    return s


def manager_only(s: dict = Depends(current_session)) -> dict:
    if s["role"] != "manager":
        raise HTTPException(403, "지점장만 사용할 수 있습니다")
    return s


# ---- 입력 모델 -------------------------------------------------------------
class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=10)
    phone: str = Field(max_length=20)
    account: str = Field(max_length=24)
    service: str

    def clean(self):
        name = self.name.strip()
        if not re.fullmatch(r"[가-힣A-Za-z ]{2,10}", name):
            raise HTTPException(422, "이름은 한글/영문 2~10자로 입력하세요")
        phone = re.sub(r"\D", "", self.phone)
        if not re.fullmatch(r"01\d{8,9}", phone):
            raise HTTPException(422, "휴대전화 번호 형식이 올바르지 않습니다")
        acc = re.sub(r"[\s-]", "", self.account)
        if not re.fullmatch(r"\d{10,16}", acc):
            raise HTTPException(422, "계좌번호는 숫자 10~16자리입니다")
        if self.service not in SERVICES:
            raise HTTPException(422, "업무 종류가 올바르지 않습니다")
        return name, phone, acc


class ReservationIn(CustomerIn):
    reserved_at: str  # 'YYYY-MM-DDTHH:MM'


class CheckinIn(BaseModel):
    code: str = Field(max_length=12)
    phone_last4: str = Field(pattern=r"^\d{4}$")


# ---- 앱 --------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    with lock:
        db.executescript(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
            import seed
            seed.run(db, issue_number, iso, now)
    threading.Thread(target=sweeper_loop, daemon=True).start()
    print("\n== 데모 PIN ==  창구1~4:", ", ".join(f"{w}={p}" for w, p in TELLER_PINS.items()),
          " 지점장:", MANAGER_PIN, "\n")
    yield


app = FastAPI(title="두둑은행 대기 현황판", lifespan=lifespan)


@app.post("/api/login")
def login(body: LoginIn):
    key = f"{body.role}:{body.window}"
    recent = [t for t in fails.get(key, []) if time.time() - t < 60]
    if len(recent) >= 5:
        raise HTTPException(429, "시도가 너무 많습니다. 잠시 후 다시 시도하세요")
    if body.role == "teller":
        if body.window not in WINDOW_SERVICE:
            raise HTTPException(422, "창구 번호가 올바르지 않습니다")
        expected = TELLER_PINS[body.window]
    else:
        expected = MANAGER_PIN
    if not hmac.compare_digest(body.pin.encode(), expected.encode()):
        recent.append(time.time())
        fails[key] = recent
        raise HTTPException(401, "PIN이 올바르지 않습니다")
    token = secrets.token_urlsafe(24)
    sessions[token] = {"role": body.role, "window": body.window if body.role == "teller" else None}
    return {"token": token, "role": body.role, "window": sessions[token]["window"]}


# --- 고객 (비로그인): 본인 번호표/예약번호만 돌려준다 ---
@app.post("/api/reservations")
def reserve(body: ReservationIn):
    name, phone, acc = body.clean()
    try:
        when = datetime.fromisoformat(body.reserved_at).replace(second=0)
    except ValueError:
        raise HTTPException(422, "예약 시각 형식이 올바르지 않습니다")
    n = now()
    if when < n or when > n + timedelta(days=14):
        raise HTTPException(422, "예약은 지금부터 14일 이내만 가능합니다")
    with lock:
        code = secrets.token_hex(3).upper()
        db.execute(
            "INSERT INTO tickets(service,name,phone,account,source,reservation_code,reserved_at,status)"
            " VALUES(?,?,?,?,?,?,?,'reserved')",
            (body.service, name, phone, acc, "reservation", code, iso(when)),
        )
        db.commit()
    return {"code": code, "reserved_at": iso(when), "service": SERVICES[body.service]}


@app.post("/api/tickets")
def walk_in(body: CustomerIn):
    name, phone, acc = body.clean()
    with lock:
        sweep()
        n = now()
        no = issue_number(body.service, n)
        db.execute(
            "INSERT INTO tickets(ticket_no,service,name,phone,account,source,arrived_at,status)"
            " VALUES(?,?,?,?,?,?,?,'waiting')",
            (no, body.service, name, phone, acc, "walkin", iso(n)),
        )
        db.commit()
        ahead = len(waiting_sorted(body.service)) - 1
    return {"ticket_no": no, "ahead": ahead}


@app.post("/api/checkin")
def checkin(body: CheckinIn):
    with lock:
        sweep()
        r = db.execute(
            "SELECT * FROM tickets WHERE reservation_code=? AND status IN ('reserved','noshow')",
            (body.code.strip().upper(),),
        ).fetchone()
        # 코드 존재 여부를 흘리지 않도록 동일 메시지
        if not r or not hmac.compare_digest(r["phone"][-4:], body.phone_last4):
            raise HTTPException(404, "예약 정보를 찾을 수 없습니다")
        n = now()
        no = issue_number(r["service"], n)
        db.execute("UPDATE tickets SET status='waiting', arrived_at=?, ticket_no=? WHERE id=?",
                   (iso(n), no, r["id"]))
        db.commit()
        r = db.execute("SELECT * FROM tickets WHERE id=?", (r["id"],)).fetchone()
        priority = is_priority(r)
        ahead = len([x for x in waiting_sorted(r["service"]) if queue_key(x) < queue_key(r)])
    return {"ticket_no": no, "priority": priority, "ahead": ahead}


# --- 대기 화면 (공개, 마스킹된 값만) ---
@app.get("/api/display")
def display():
    with lock:
        sweep()
        called = db.execute(
            "SELECT ticket_no,name,window FROM tickets WHERE status='called' ORDER BY called_at DESC"
        ).fetchall()
        waiting = waiting_sorted()
    return {
        "called": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"]), "window": r["window"]}
                   for r in called],
        "waiting": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"])} for r in waiting],
    }


# --- 창구 직원: 자기 창구에 배정된 고객만 ---
def current_ticket(window: int):
    return db.execute(
        "SELECT * FROM tickets WHERE window=? AND status IN ('called','serving')", (window,)
    ).fetchone()


def teller_view(window: int):
    r = current_ticket(window)
    detail = None
    if r:
        detail = {
            "ticket_no": r["ticket_no"], "status": r["status"], "name": r["name"],
            "phone": mask_phone(r["phone"]), "account": mask_account(r["account"]),
            "service": SERVICES[r["service"]],
            "reservation": r["source"] == "reservation",
            "priority": is_priority(r),
            "call_deadline": iso(parse(r["called_at"]) + CALL_TIMEOUT) if r["status"] == "called" else None,
        }
    return {
        "window": window, "service": SERVICES[WINDOW_SERVICE[window]],
        "waiting_count": len(waiting_sorted(WINDOW_SERVICE[window])), "current": detail,
    }


@app.get("/api/teller/me")
def teller_me(s: dict = Depends(teller_only)):
    with lock:
        sweep()
        return teller_view(s["window"])


@app.post("/api/teller/call-next")
def teller_call(s: dict = Depends(teller_only)):
    with lock:
        sweep()
        if current_ticket(s["window"]):
            raise HTTPException(409, "처리 중인 고객이 있습니다")
        if not call_next(s["window"]):
            raise HTTPException(404, "대기 중인 고객이 없습니다")
        return teller_view(s["window"])


def _advance(window: int, frm: str, to: str):
    with lock:
        sweep()
        r = current_ticket(window)
        if not r or r["status"] != frm:
            raise HTTPException(409, "처리할 수 없는 상태입니다")
        db.execute("UPDATE tickets SET status=?, ended_at=? WHERE id=?",
                   (to, iso(now()) if to == "done" else None, r["id"]))
        db.commit()
        return teller_view(window)


@app.post("/api/teller/serve")
def teller_serve(s: dict = Depends(teller_only)):
    return _advance(s["window"], "called", "serving")


@app.post("/api/teller/done")
def teller_done(s: dict = Depends(teller_only)):
    return _advance(s["window"], "serving", "done")


# --- 지점장: 집계 숫자만, 고객 정보 없음 ---
@app.get("/api/manager/stats")
def manager_stats(_: dict = Depends(manager_only)):
    with lock:
        sweep()
        rows = db.execute("SELECT service,status,COUNT(*) c FROM tickets GROUP BY service,status").fetchall()
        res_total = db.execute("SELECT COUNT(*) FROM tickets WHERE source='reservation'").fetchone()[0]
        noshow = db.execute("SELECT COUNT(*) FROM tickets WHERE status='noshow'").fetchone()[0]
        done = db.execute(
            "SELECT arrived_at,called_at FROM tickets WHERE status IN ('done','serving','called') AND called_at IS NOT NULL"
        ).fetchall()
    by = {s: {} for s in SERVICES}
    for r in rows:
        by[r["service"]][r["status"]] = r["c"]
    waits = [(parse(r["called_at"]) - parse(r["arrived_at"])).total_seconds() / 60 for r in done]
    return {
        "by_service": {SERVICES[s]: v for s, v in by.items()},
        "totals": {k: sum(v.get(k, 0) for v in by.values())
                   for k in ("reserved", "waiting", "called", "serving", "done", "hold", "noshow")},
        "reservations_total": res_total,
        "noshow_rate": round(noshow / res_total * 100, 1) if res_total else 0,
        "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else 0,
    }


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
