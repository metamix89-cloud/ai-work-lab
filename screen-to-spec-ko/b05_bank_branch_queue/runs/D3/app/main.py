import asyncio
import hmac
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import core
from .seed import seed

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")

# 데모용 PIN. 운영 시 환경변수로 바꿀 것.
TELLER_PINS = {w: os.environ.get(f"DUDUK_PIN_W{w}", f"{w}{w}{w}{w}") for w in core.WINDOWS}
MANAGER_PIN = os.environ.get("DUDUK_PIN_MANAGER", "9999")
SESSION_TTL = timedelta(hours=8)
sessions: dict[str, tuple[str, Optional[int], datetime]] = {}  # token -> (role, window, expiry)

conn = core.connect()


async def _ticker():
    while True:
        core.expire_calls(conn)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app):
    core.init_db(conn)
    seed(conn)
    task = asyncio.create_task(_ticker())
    yield
    task.cancel()


app = FastAPI(title="두둑은행 방문 예약 · 대기 현황판", lifespan=lifespan)


# ---------- 입력 모델 ----------
class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    phone: str
    account: str
    service: Literal["deposit", "loan", "fx"]

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[가-힣A-Za-z ]{1,20}", v):
            raise ValueError("이름은 한글/영문만 입력하세요")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        d = re.sub(r"[\s-]", "", v)
        if not re.fullmatch(r"01\d{8,9}", d):
            raise ValueError("전화번호 형식이 올바르지 않습니다")
        return d

    @field_validator("account")
    @classmethod
    def _acct(cls, v):
        d = re.sub(r"[\s-]", "", v)
        if not re.fullmatch(r"\d{8,16}", d):
            raise ValueError("계좌번호는 숫자 8~16자리입니다")
        return d


class ReservationIn(CustomerIn):
    reserved_at: datetime


class CheckInIn(BaseModel):
    code: str = Field(min_length=8, max_length=8)


class LoginIn(BaseModel):
    role: Literal["teller", "manager"]
    window: Optional[int] = None
    pin: str = Field(max_length=32)


# ---------- 인증 ----------
def _session(authorization: Optional[str]):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "로그인이 필요합니다")
    s = sessions.get(authorization[7:])
    if not s or s[2] < core.now():
        raise HTTPException(401, "세션이 만료되었습니다")
    return s


def teller(authorization: Optional[str] = Header(None)) -> int:
    role, window, _ = _session(authorization)
    if role != "teller":
        raise HTTPException(403, "창구 직원 전용입니다")
    return window  # 창구 번호는 항상 세션에서만 얻는다 (요청 값 사용 안 함)


def manager(authorization: Optional[str] = Header(None)) -> None:
    if _session(authorization)[0] != "manager":
        raise HTTPException(403, "지점장 전용입니다")


@app.post("/api/login")
def login(body: LoginIn):
    if body.role == "teller":
        if body.window not in core.WINDOWS:
            raise HTTPException(400, "창구 번호가 올바르지 않습니다")
        expected = TELLER_PINS[body.window]
    else:
        expected = MANAGER_PIN
    if not hmac.compare_digest(body.pin.encode(), expected.encode()):
        raise HTTPException(401, "PIN이 올바르지 않습니다")
    token = secrets.token_urlsafe(24)
    window = body.window if body.role == "teller" else None
    sessions[token] = (body.role, window, core.now() + SESSION_TTL)
    return {"token": token, "role": body.role, "window": window}


# ---------- 고객 ----------
@app.post("/api/reservations")
def reserve(body: ReservationIn):
    t = core.now()
    r = body.reserved_at.replace(tzinfo=None, second=0)
    if r < t or r > t + timedelta(days=14):
        raise HTTPException(400, "예약은 지금부터 14일 이내만 가능합니다")
    if not (9 <= r.hour < 16 or (r.hour == 16 and r.minute <= 30)):
        raise HTTPException(400, "예약 가능 시간은 09:00~16:30 입니다")
    if r.weekday() >= 5:
        raise HTTPException(400, "주말에는 예약할 수 없습니다")
    code = core.create_reservation(conn, body.name, body.phone, body.account[-4:], body.service, r)
    return {"code": code, "reserved_at": core.ts(r), "service": core.SERVICES[body.service][0]}


@app.post("/api/check-in")
def check_in(body: CheckInIn):
    res = core.check_in(conn, body.code.upper())
    if res is None:
        raise HTTPException(404, "예약 코드를 찾을 수 없습니다")
    if res == "already":
        raise HTTPException(409, "이미 도착 처리된 예약입니다")
    if res == "wrong_day":
        raise HTTPException(400, "예약 당일에만 도착 확인이 가능합니다")
    ticket, prio, name = res
    return {"ticket": ticket, "priority": bool(prio), "name": core.mask_name(name)}


@app.post("/api/tickets")
def take_ticket(body: CustomerIn):
    ticket, _ = core.walk_in(conn, body.name, body.phone, body.account[-4:], body.service)
    ahead = len([r for r in core.waiting_rows(conn, body.service) if r["ticket_no"] != ticket])
    return {"ticket": ticket, "ahead": ahead}


# ---------- 대기 화면 (공개: 번호 · 가린 이름 · 창구만) ----------
@app.get("/api/display")
def display():
    core.expire_calls(conn)
    return core.display_data(conn)


# ---------- 창구 직원 ----------
def _current(window):
    r = conn.execute("SELECT * FROM visits WHERE window=? AND status IN ('called','serving') LIMIT 1",
                     (window,)).fetchone()
    if not r:
        return None
    left = None
    if r["status"] == "called":
        due = datetime.strptime(r["called_at"], core.FMT) + core.CALL_TIMEOUT
        left = max(0, int((due - core.now()).total_seconds()))
    return {"ticket": r["ticket_no"], "name": r["name"], "phone": r["phone"],
            "account": "****" + r["account_last4"],  # 끝 4자리만
            "service": core.SERVICES[r["service"]][0], "kind": r["kind"], "reserved_at": r["reserved_at"],
            "priority": bool(r["is_priority"]), "status": r["status"], "seconds_left": left}


@app.get("/api/teller/state")
def teller_state(window: int = Depends(teller)):
    core.expire_calls(conn)
    svc = core.WINDOWS[window]
    return {"window": window, "service": core.SERVICES[svc][0], "current": _current(window),
            "waiting": [{"ticket": r["ticket_no"], "name": core.mask_name(r["name"]), "priority": bool(r["is_priority"])}
                        for r in core.waiting_rows(conn, svc)]}


@app.post("/api/teller/call-next")
def teller_call(window: int = Depends(teller)):
    core.expire_calls(conn)
    res = core.call_next(conn, window)
    if res == "busy":
        raise HTTPException(409, "현재 고객 응대를 먼저 마무리하세요")
    if res is None:
        raise HTTPException(404, "대기 중인 고객이 없습니다")
    return teller_state(window)


@app.post("/api/teller/start")
def teller_start(window: int = Depends(teller)):
    if not core.set_state(conn, window, ("called",), "serving"):
        raise HTTPException(409, "호출된 고객이 없습니다")
    return teller_state(window)


@app.post("/api/teller/finish")
def teller_finish(window: int = Depends(teller)):
    if not core.set_state(conn, window, ("called", "serving"), "done"):
        raise HTTPException(409, "응대 중인 고객이 없습니다")
    return teller_state(window)


# ---------- 지점장 (숫자만) ----------
@app.get("/api/manager/summary")
def manager_summary(_: None = Depends(manager)):
    core.expire_calls(conn)
    return core.manager_summary(conn)


# ---------- 정적 페이지 ----------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
