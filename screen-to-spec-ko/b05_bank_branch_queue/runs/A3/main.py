"""두둑은행 지점 방문 예약 · 대기 현황판.

실행: python -m uvicorn main:app --port 8000
화면: / (안내) /kiosk /board /teller /manager
"""
import os
import re
import secrets
import sqlite3
import random
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DUDUK_DB", str(BASE / "duduk.db"))
# 데모용 기본 PIN. 운영 시 환경변수로 반드시 교체.
PINS = {
    "teller": os.environ.get("TELLER_PIN", "1111"),
    "manager": os.environ.get("MANAGER_PIN", "9999"),
}
NOSHOW_GRACE_MIN = 15
SLOT_CAPACITY = 4
OPEN_H, CLOSE_H = 9, 16  # 마지막 예약 슬롯 15:30
SERVICES = {"deposit": ("예금", "D"), "loan": ("대출", "L"), "fx": ("외환", "F")}
# 창구별 담당 업무
COUNTERS = {1: ["deposit"], 2: ["deposit"], 3: ["loan"], 4: ["fx"]}

Service = Literal["deposit", "loan", "fx"]


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat(sep=" ")


SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  number TEXT NOT NULL,
  service TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('reservation','walkin')),
  name TEXT NOT NULL, phone TEXT NOT NULL, account TEXT NOT NULL,
  code TEXT,                -- 예약 확인 코드
  slot_at TEXT,             -- 예약 시각
  status TEXT NOT NULL CHECK(status IN ('reserved','waiting','serving','done','noshow','cancelled')),
  counter INTEGER,
  created_at TEXT NOT NULL, arrived_at TEXT, called_at TEXT, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_status ON tickets(status);
"""


def next_number(con, service) -> str:
    prefix = SERVICES[service][1]
    n = con.execute("SELECT COUNT(*) FROM tickets WHERE service=?", (service,)).fetchone()[0]
    return f"{prefix}{n % 999 + 1:03d}"


def insert_ticket(con, *, service, kind, name, phone, account, slot_at=None,
                  status, created=None, arrived=None, called=None, finished=None, counter=None):
    code = f"{secrets.randbelow(900000) + 100000}" if kind == "reservation" else None
    created = created or now()
    cur = con.execute(
        """INSERT INTO tickets(number,service,kind,name,phone,account,code,slot_at,status,counter,
           created_at,arrived_at,called_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (next_number(con, service), service, kind, name, phone, account, code,
         iso(slot_at) if slot_at else None, status, counter, iso(created),
         iso(arrived) if arrived else None, iso(called) if called else None,
         iso(finished) if finished else None))
    return cur.lastrowid


# ---------- 마스킹 (대기 화면·지점장 화면에는 개인정보 원문을 내보내지 않는다) ----------
def mask_name(n: str) -> str:
    return n[0] + "*" * (len(n) - 1) if len(n) <= 2 else n[0] + "*" * (len(n) - 2) + n[-1]


def mask_phone(p: str) -> str:
    return re.sub(r"^(\d{3})-?\d{3,4}-?(\d{4})$", r"\1-****-\2", p)


def mask_account(a: str) -> str:
    return "*" * max(len(a) - 4, 0) + a[-4:]


# ---------- 입력 모델 ----------
class Person(BaseModel):
    name: str
    phone: str
    account: str
    service: Service

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[가-힣A-Za-z ]{2,20}", v):
            raise ValueError("이름은 한글/영문 2~20자로 입력하세요")
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
    def _acc(cls, v):
        d = re.sub(r"\D", "", v)
        if not 10 <= len(d) <= 14:
            raise ValueError("계좌번호는 숫자 10~14자리로 입력하세요")
        return d


class Reservation(Person):
    slot: str  # 'YYYY-MM-DD HH:MM'


class CheckIn(BaseModel):
    code: str


class Login(BaseModel):
    role: Literal["teller", "manager"]
    pin: str


# ---------- 인증 ----------
TOKENS: dict[str, str] = {}


def need(role):
    def dep(authorization: str = Header(default="")):
        tok = authorization.removeprefix("Bearer ").strip()
        r = TOKENS.get(tok)
        if r is None or (r != role and r != "manager"):  # 지점장은 창구 권한 포함
            raise HTTPException(401, "로그인이 필요합니다")
        return r
    return dep


app = FastAPI(title="두둑은행 방문 예약·대기 현황판")


@app.on_event("startup")
def startup():
    with db() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
            seed(con)
            for r in con.execute("SELECT number,name,code FROM tickets WHERE status='reserved'"):
                print(f"[데모] 예약 접수 코드 {r['code']} ({r['number']}, {mask_name(r['name'])})")


def sweep(con):
    """예약 시각 + 유예시간이 지나도 도착하지 않은 예약은 노쇼 처리."""
    limit = iso(now() - timedelta(minutes=NOSHOW_GRACE_MIN))
    con.execute("UPDATE tickets SET status='noshow' WHERE status='reserved' AND slot_at<?", (limit,))


# ---------- 고객용 ----------
@app.post("/api/login")
def login(b: Login):
    if not secrets.compare_digest(b.pin, PINS[b.role]):
        raise HTTPException(401, "PIN이 올바르지 않습니다")
    tok = secrets.token_urlsafe(24)
    TOKENS[tok] = b.role
    return {"token": tok, "role": b.role}


@app.get("/api/slots")
def slots(date: str | None = None):
    day = datetime.strptime(date, "%Y-%m-%d").date() if date else now().date()
    out, t = [], now()
    with db() as con:
        for h in range(OPEN_H, CLOSE_H):
            for m in (0, 30):
                s = datetime(day.year, day.month, day.day, h, m)
                used = con.execute(
                    "SELECT COUNT(*) FROM tickets WHERE slot_at=? AND status IN ('reserved','waiting','serving','done')",
                    (iso(s),)).fetchone()[0]
                out.append({"slot": s.strftime("%Y-%m-%d %H:%M"),
                            "available": s > t and used < SLOT_CAPACITY})
    return out


@app.post("/api/reservations", status_code=201)
def reserve(b: Reservation):
    try:
        s = datetime.strptime(b.slot, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(422, "예약 시간 형식 오류")
    if s <= now() or s.minute not in (0, 30) or not OPEN_H <= s.hour < CLOSE_H or s.weekday() >= 5:
        raise HTTPException(422, "예약할 수 없는 시간입니다 (평일 09:00~16:00, 30분 단위)")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        used = con.execute(
            "SELECT COUNT(*) FROM tickets WHERE slot_at=? AND status IN ('reserved','waiting','serving','done')",
            (iso(s),)).fetchone()[0]
        if used >= SLOT_CAPACITY:
            raise HTTPException(409, "해당 시간은 마감되었습니다")
        dup = con.execute(
            "SELECT 1 FROM tickets WHERE phone=? AND status='reserved'", (b.phone,)).fetchone()
        if dup:
            raise HTTPException(409, "이미 예약된 건이 있습니다")
        tid = insert_ticket(con, service=b.service, kind="reservation", name=b.name,
                            phone=b.phone, account=b.account, slot_at=s, status="reserved")
        r = con.execute("SELECT number,code,slot_at FROM tickets WHERE id=?", (tid,)).fetchone()
    return {"number": r["number"], "code": r["code"], "slot": r["slot_at"]}


@app.post("/api/walkin", status_code=201)
def walkin(b: Person):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        tid = insert_ticket(con, service=b.service, kind="walkin", name=b.name,
                            phone=b.phone, account=b.account, status="waiting", arrived=now())
        r = con.execute("SELECT number FROM tickets WHERE id=?", (tid,)).fetchone()
        ahead = len(queue(con, b.service)) - 1
    return {"number": r["number"], "ahead": ahead}


@app.post("/api/checkin")
def checkin(b: CheckIn):
    with db() as con:
        sweep(con)
        r = con.execute("SELECT * FROM tickets WHERE code=? AND status='reserved'", (b.code.strip(),)).fetchone()
        if not r:
            raise HTTPException(404, "유효한 예약을 찾을 수 없습니다 (이미 접수/취소/노쇼 처리되었을 수 있습니다)")
        if datetime.fromisoformat(r["slot_at"]) - now() > timedelta(minutes=30):
            raise HTTPException(409, f"예약 30분 전부터 접수할 수 있습니다 (예약 {r['slot_at'][11:16]})")
        con.execute("UPDATE tickets SET status='waiting', arrived_at=? WHERE id=?", (iso(now()), r["id"]))
    return {"number": r["number"], "service": SERVICES[r["service"]][0]}


# ---------- 대기열 ----------
def queue(con, service=None, services=None):
    """예약 접수 고객이 항상 먼저, 같은 종류 안에서는 예약시각/도착 순."""
    sql = "SELECT * FROM tickets WHERE status='waiting'"
    args = []
    svcs = services or ([service] if service else None)
    if svcs:
        sql += f" AND service IN ({','.join('?' * len(svcs))})"
        args += svcs
    rows = con.execute(sql, args).fetchall()
    return sorted(rows, key=lambda r: (r["kind"] != "reservation",
                                       r["slot_at"] if r["kind"] == "reservation" else r["arrived_at"], r["id"]))


@app.get("/api/board")
def board():
    """고객 공용 모니터용: 번호표와 창구만. 이름·전화·계좌는 절대 포함하지 않는다."""
    with db() as con:
        sweep(con)
        serving = con.execute(
            "SELECT number,counter,service FROM tickets WHERE status='serving' ORDER BY called_at DESC").fetchall()
        last = {r["counter"]: r for r in serving}
        waiting = queue(con)
    return {
        "counters": [{"counter": c, "services": [SERVICES[s][0] for s in sv],
                      "number": last[c]["number"] if c in last else None} for c, sv in COUNTERS.items()],
        "waiting": [{"number": r["number"], "service": SERVICES[r["service"]][0],
                     "reservation": r["kind"] == "reservation"} for r in waiting[:12]],
        "waiting_total": len(waiting),
        "now": iso(now()),
    }


# ---------- 창구 직원 ----------
def current(con, counter):
    return con.execute("SELECT * FROM tickets WHERE status='serving' AND counter=?", (counter,)).fetchone()


def detail(r):
    if not r:
        return None
    return {"id": r["id"], "number": r["number"], "service": SERVICES[r["service"]][0],
            "kind": "예약" if r["kind"] == "reservation" else "현장", "name": r["name"], "phone": r["phone"],
            "account": r["account"], "slot_at": r["slot_at"], "arrived_at": r["arrived_at"], "called_at": r["called_at"]}


def check_counter(c):
    if c not in COUNTERS:
        raise HTTPException(404, "없는 창구입니다")


@app.get("/api/teller/{counter}", dependencies=[Depends(need("teller"))])
def teller_state(counter: int):
    check_counter(counter)
    with db() as con:
        sweep(con)
        q = queue(con, services=COUNTERS[counter])
        return {"counter": counter, "services": [SERVICES[s][0] for s in COUNTERS[counter]],
                "current": detail(current(con, counter)),
                "waiting": [{"number": r["number"], "service": SERVICES[r["service"]][0],
                             "reservation": r["kind"] == "reservation"} for r in q]}


@app.post("/api/teller/{counter}/call", dependencies=[Depends(need("teller"))])
def call_next(counter: int):
    check_counter(counter)
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        sweep(con)
        if current(con, counter):
            raise HTTPException(409, "처리 중인 고객이 있습니다. 먼저 완료하세요")
        q = queue(con, services=COUNTERS[counter])
        if not q:
            raise HTTPException(404, "대기 고객이 없습니다")
        r = q[0]
        con.execute("UPDATE tickets SET status='serving', counter=?, called_at=? WHERE id=?",
                    (counter, iso(now()), r["id"]))
        return detail(current(con, counter))


@app.post("/api/teller/{counter}/finish", dependencies=[Depends(need("teller"))])
def finish(counter: int, outcome: Literal["done", "noshow"] = "done"):
    """outcome=noshow: 호출했으나 창구에 나타나지 않은 고객."""
    check_counter(counter)
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        r = current(con, counter)
        if not r:
            raise HTTPException(404, "처리 중인 고객이 없습니다")
        con.execute("UPDATE tickets SET status=?, finished_at=? WHERE id=?", (outcome, iso(now()), r["id"]))
    return {"ok": True}


# ---------- 지점장 ----------
@app.get("/api/manager/summary", dependencies=[Depends(need("manager"))])
def summary():
    today = now().strftime("%Y-%m-%d")
    with db() as con:
        sweep(con)
        rows = con.execute("SELECT * FROM tickets WHERE substr(created_at,1,10)=? OR substr(slot_at,1,10)=?",
                           (today, today)).fetchall()
        waiting = queue(con)
        by = lambda st: [r for r in rows if r["status"] == st]
        done = by("done")
        waits = [(datetime.fromisoformat(r["called_at"]) - datetime.fromisoformat(r["arrived_at"])).total_seconds() / 60
                 for r in done if r["called_at"] and r["arrived_at"]]
        svc = {}
        for k, (label, _) in SERVICES.items():
            svc[label] = {"waiting": sum(1 for r in waiting if r["service"] == k),
                          "done": sum(1 for r in done if r["service"] == k)}
        res = [r for r in rows if r["kind"] == "reservation"]
        res_closed = [r for r in res if r["status"] in ("done", "noshow", "serving")]
        noshow = [r for r in rows if r["status"] == "noshow"]
        return {
            "waiting_total": len(waiting),
            "oldest_wait_min": round(max(((now() - datetime.fromisoformat(r["arrived_at"])).total_seconds() / 60
                                          for r in waiting), default=0)),
            "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else 0,
            "serving": len(by("serving")), "done": len(done),
            "reservations": len(res), "reserved_pending": len(by("reserved")),
            "noshow_count": len(noshow),
            "noshow_rate": round(100 * len([r for r in res if r["status"] == "noshow"]) / len(res_closed), 1)
            if res_closed else 0,
            "by_service": svc,
            "noshows": [{"number": r["number"], "service": SERVICES[r["service"]][0],
                         "slot_at": r["slot_at"], "name": mask_name(r["name"]),
                         "phone": mask_phone(r["phone"]), "account": mask_account(r["account"]),
                         "kind": "예약" if r["kind"] == "reservation" else "호출 후 미응답"}
                        for r in sorted(noshow, key=lambda r: r["slot_at"] or r["created_at"], reverse=True)],
            "waiting": [{"number": r["number"], "service": SERVICES[r["service"]][0],
                         "kind": "예약" if r["kind"] == "reservation" else "현장",
                         "name": mask_name(r["name"]),
                         "waited_min": round((now() - datetime.fromisoformat(r["arrived_at"])).total_seconds() / 60)}
                        for r in waiting],
        }


# ---------- 가상 데이터 ----------
NAMES = ["김민수", "이서연", "박지훈", "최유진", "정다은", "강현우", "조은지", "윤성호", "장미래", "임도현",
         "한소희", "오세훈", "서지안", "신재원", "권나영", "황보람"]


def seed(con):
    random.seed(7)
    t = now()
    base = t.replace(second=0, minute=(t.minute // 30) * 30)

    def person(i):
        return dict(name=NAMES[i % len(NAMES)],
                    phone=f"010-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
                    account="".join(random.choice("0123456789") for _ in range(12)))

    svc = ["deposit", "loan", "fx"]
    i = 0
    # 오늘 처리 완료 고객
    for k in range(8):
        s = svc[k % 3]
        arr = t - timedelta(minutes=120 - k * 8)
        insert_ticket(con, service=s, kind="walkin" if k % 2 else "reservation", **person(i),
                      slot_at=arr if k % 2 == 0 else None, status="done", created=arr, arrived=arr,
                      called=arr + timedelta(minutes=random.randint(3, 14)),
                      finished=arr + timedelta(minutes=20), counter=1 + k % 4)
        i += 1
    # 과거 예약 노쇼
    for k in range(3):
        s = base - timedelta(minutes=90 + 30 * k)
        insert_ticket(con, service=svc[k], kind="reservation", **person(i), slot_at=s, status="noshow",
                      created=t - timedelta(hours=5))
        i += 1
    # 현재 처리 중
    insert_ticket(con, service="deposit", kind="walkin", **person(i), status="serving", counter=1,
                  created=t - timedelta(minutes=18), arrived=t - timedelta(minutes=18),
                  called=t - timedelta(minutes=2))
    i += 1
    # 대기 중: 현장 + 접수 완료된 예약
    for k, s in enumerate(["deposit", "loan", "deposit", "fx", "deposit"]):
        a = t - timedelta(minutes=12 - k * 2)
        insert_ticket(con, service=s, kind="walkin", **person(i), status="waiting", created=a, arrived=a)
        i += 1
    for k, s in enumerate(["deposit", "fx"]):
        sl = t - timedelta(minutes=5 - k * 5)
        insert_ticket(con, service=s, kind="reservation", **person(i), slot_at=sl, status="waiting",
                      created=t - timedelta(days=1), arrived=t - timedelta(minutes=4 - k))
        i += 1
    # 앞으로의 예약 (체크인 데모용 코드는 /api/demo-codes 대신 DB에서 확인)
    for k, s in enumerate(["loan", "deposit", "fx"]):
        sl = base + timedelta(minutes=30 * (k + 1))
        insert_ticket(con, service=s, kind="reservation", **person(i), slot_at=sl, status="reserved",
                      created=t - timedelta(days=1))
        i += 1


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


for _p in ("kiosk", "board", "teller", "manager"):
    app.add_api_route(f"/{_p}", (lambda p=_p: FileResponse(BASE / "static" / f"{p}.html")),
                      methods=["GET"], include_in_schema=False)
