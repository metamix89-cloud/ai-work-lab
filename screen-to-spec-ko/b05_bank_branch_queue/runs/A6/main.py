import hmac
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

import db

BASE = os.path.dirname(os.path.abspath(__file__))
TELLER_PIN = os.environ.get("DUDUK_TELLER_PIN", "1111")
MANAGER_PIN = os.environ.get("DUDUK_MANAGER_PIN", "9999")
COUNTERS = [1, 2, 3, 4]
SERVICES = {"예금": "D", "대출": "L", "외환": "F"}
NOSHOW_GRACE_MIN = 15      # minutes after reserved time before a reservation becomes a no-show
CHECKIN_EARLY_MIN = 30     # how early a reservation may check in
SLOT_TIMES = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)] + ["16:00"]
SLOT_CAPACITY = 3          # reservations per slot (any service)
MAX_DAYS_AHEAD = 7

app = FastAPI(title="두둑은행 방문 예약 · 대기 현황판")
db.init()


# ---------- helpers ----------
@contextmanager
def tx():
    """Transaction; BEGIN IMMEDIATE serialises writers so numbering and calls are atomic.
    Also lazily flips overdue reservations to no-show, so every request sees fresh state."""
    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        expire_noshows(conn)
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


read = tx  # reads also run expire_noshows, which writes


def expire_noshows(conn):
    now = db.now()
    limit = db.iso(now - timedelta(minutes=NOSHOW_GRACE_MIN))
    conn.execute("UPDATE tickets SET status='noshow', finished_at=? "
                 "WHERE status='reserved' AND reserved_at < ?", (db.iso(now), limit))


def mask_name(n):
    if len(n) <= 1:
        return n
    if len(n) == 2:
        return n[0] + "*"
    return n[0] + "*" * (len(n) - 2) + n[-1]


def mask_phone(p):
    return re.sub(r"^(\d{3})-\d{3,4}-(\d{4})$", r"\1-****-\2", p)


def check_pin(expected, given):
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "PIN이 올바르지 않습니다.")


def teller_auth(x_pin: str = Header(default="")):
    check_pin(TELLER_PIN, x_pin)


def manager_auth(x_pin: str = Header(default="")):
    check_pin(MANAGER_PIN, x_pin)


# reservations (by reserved time) go before walk-ins (by arrival time)
QUEUE_ORDER = ("ORDER BY CASE kind WHEN 'reservation' THEN 0 ELSE 1 END, "
               "CASE kind WHEN 'reservation' THEN reserved_at ELSE checked_in_at END, id")


def waiting(conn):
    return conn.execute(f"SELECT * FROM tickets WHERE status='waiting' {QUEUE_ORDER}").fetchall()


def next_ticket_no(conn, service, day):
    n = conn.execute("SELECT COUNT(*) FROM tickets WHERE service=? AND date(COALESCE(reserved_at,created_at))=?",
                     (service, day)).fetchone()[0]
    return f"{SERVICES[service]}{n + 1:03d}"


def position_of(conn, row):
    if row["status"] != "waiting":
        return None
    for i, w in enumerate(waiting(conn), 1):
        if w["id"] == row["id"]:
            return i


def digits(s):
    return re.sub(r"\D", "", s)


# ---------- models ----------
class Person(BaseModel):
    name: str
    phone: str
    account: str
    service: str

    @field_validator("name")
    @classmethod
    def v_name(cls, v):
        v = v.strip()
        if not 1 <= len(v) <= 20:
            raise ValueError("이름은 1~20자로 입력하세요.")
        return v

    @field_validator("phone")
    @classmethod
    def v_phone(cls, v):
        d = digits(v)
        if not re.fullmatch(r"01\d{8,9}", d):
            raise ValueError("휴대전화 번호 형식이 올바르지 않습니다.")
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"

    @field_validator("account")
    @classmethod
    def v_account(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[\d-]+", v) or not 10 <= len(digits(v)) <= 16:
            raise ValueError("계좌번호는 숫자 10~16자리로 입력하세요.")
        return v

    @field_validator("service")
    @classmethod
    def v_service(cls, v):
        if v not in SERVICES:
            raise ValueError("업무 종류는 예금·대출·외환 중 하나입니다.")
        return v


class Reservation(Person):
    date: str
    time: str


class TicketRef(BaseModel):
    ticket_no: str
    phone: str


class CounterReq(BaseModel):
    counter: int


# ---------- customer ----------
def public_ticket(conn, r):
    """What the customer sees about their own ticket (name masked, no phone/account)."""
    return {"ticket_no": r["ticket_no"], "service": r["service"], "kind": r["kind"], "status": r["status"],
            "reserved_at": r["reserved_at"], "counter": r["counter"], "position": position_of(conn, r),
            "name": mask_name(r["name"])}


def slot_used(conn, at):
    return conn.execute("SELECT COUNT(*) FROM tickets WHERE kind='reservation' AND reserved_at=? "
                        "AND status IN ('reserved','waiting','called','serving')", (db.iso(at),)).fetchone()[0]


def bookable_day(d):
    today = datetime.now().date()
    return today <= d <= today + timedelta(days=MAX_DAYS_AHEAD) and d.weekday() < 5


@app.get("/api/slots")
def slots(date: str):
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, "날짜 형식이 올바르지 않습니다.")
    if not bookable_day(d):
        return {"slots": []}
    out = []
    with read() as conn:
        for t in SLOT_TIMES:
            at = datetime.strptime(f"{date} {t}", "%Y-%m-%d %H:%M")
            if at > datetime.now():
                out.append({"time": t, "available": slot_used(conn, at) < SLOT_CAPACITY})
    return {"slots": out}


@app.post("/api/reservations")
def reserve(r: Reservation):
    try:
        at = datetime.strptime(f"{r.date} {r.time}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(422, "날짜/시간 형식이 올바르지 않습니다.")
    if r.time not in SLOT_TIMES or at <= datetime.now() or not bookable_day(at.date()):
        raise HTTPException(422, "예약할 수 없는 시간입니다.")
    with tx() as conn:
        if slot_used(conn, at) >= SLOT_CAPACITY:
            raise HTTPException(409, "해당 시간은 예약이 마감되었습니다.")
        if conn.execute("SELECT 1 FROM tickets WHERE phone=? AND kind='reservation' AND status='reserved'",
                        (r.phone,)).fetchone():
            raise HTTPException(409, "이미 진행 중인 예약이 있습니다.")
        no = next_ticket_no(conn, r.service, r.date)
        conn.execute("INSERT INTO tickets(ticket_no,name,phone,account,service,kind,status,reserved_at,created_at) "
                     "VALUES(?,?,?,?,?,'reservation','reserved',?,?)",
                     (no, r.name, r.phone, r.account, r.service, db.iso(at), db.iso(db.now())))
    return {"ticket_no": no, "reserved_at": db.iso(at), "service": r.service,
            "message": f"예약 완료. 방문 시 예약번호 {no} 와 전화번호로 도착 확인을 해 주세요."}


@app.post("/api/walkin")
def walkin(p: Person):
    with tx() as conn:
        n = db.now()
        no = next_ticket_no(conn, p.service, n.date().isoformat())
        cur = conn.execute("INSERT INTO tickets(ticket_no,name,phone,account,service,kind,status,created_at,checked_in_at) "
                           "VALUES(?,?,?,?,?,'walkin','waiting',?,?)",
                           (no, p.name, p.phone, p.account, p.service, db.iso(n), db.iso(n)))
        row = conn.execute("SELECT * FROM tickets WHERE id=?", (cur.lastrowid,)).fetchone()
        return public_ticket(conn, row)


def find_own(conn, ref, today_only=False):
    sql = "SELECT * FROM tickets WHERE ticket_no=?"
    if today_only:
        sql += " AND kind='reservation' AND date(reserved_at)=date('now','localtime')"
    rows = conn.execute(sql + " ORDER BY id DESC", (ref.ticket_no.strip().upper(),)).fetchall()
    # ticket number alone is guessable, so the phone number must match too
    return next((r for r in rows if digits(r["phone"]) == digits(ref.phone)), None)


@app.post("/api/checkin")
def checkin(ref: TicketRef):
    with tx() as conn:
        row = find_own(conn, ref, today_only=True)
        if not row:
            raise HTTPException(404, "일치하는 오늘 예약이 없습니다.")
        if row["status"] == "noshow":
            raise HTTPException(409, "예약 시간이 지나 노쇼 처리되었습니다. 현장 번호표를 뽑아 주세요.")
        if row["status"] == "reserved":
            if datetime.fromisoformat(row["reserved_at"]) - datetime.now() > timedelta(minutes=CHECKIN_EARLY_MIN):
                raise HTTPException(409, f"예약 시간 {CHECKIN_EARLY_MIN}분 전부터 도착 확인이 가능합니다.")
            conn.execute("UPDATE tickets SET status='waiting', checked_in_at=? WHERE id=?",
                         (db.iso(db.now()), row["id"]))
            row = conn.execute("SELECT * FROM tickets WHERE id=?", (row["id"],)).fetchone()
        return public_ticket(conn, row)


@app.post("/api/ticket/lookup")
def lookup(ref: TicketRef):
    with read() as conn:
        row = find_own(conn, ref)
        if not row:
            raise HTTPException(404, "일치하는 번호표가 없습니다.")
        return public_ticket(conn, row)


# ---------- public waiting-room display (no personal data at all) ----------
@app.get("/api/display")
def display():
    with read() as conn:
        active = {r["counter"]: r for r in conn.execute(
            "SELECT ticket_no,counter,status FROM tickets WHERE status IN ('called','serving')")}
        w = waiting(conn)
        return {
            "counters": [{"counter": n, "ticket_no": active[n]["ticket_no"] if n in active else None,
                          "status": active[n]["status"] if n in active else "idle"} for n in COUNTERS],
            "waiting": [{"ticket_no": r["ticket_no"], "service": r["service"], "kind": r["kind"]} for r in w[:12]],
            "waiting_total": len(w),
        }


# ---------- teller ----------
def full_ticket(r):
    return {k: r[k] for k in ("ticket_no", "name", "phone", "account", "service", "kind", "status",
                              "reserved_at", "checked_in_at", "called_at", "started_at", "counter")}


def valid_counter(c):
    if c not in COUNTERS:
        raise HTTPException(422, "창구 번호가 올바르지 않습니다.")


def current_for(conn, counter):
    return conn.execute("SELECT * FROM tickets WHERE counter=? AND status IN ('called','serving')",
                        (counter,)).fetchone()


@app.get("/api/teller/state", dependencies=[Depends(teller_auth)])
def teller_state(counter: int):
    valid_counter(counter)
    with read() as conn:
        cur = current_for(conn, counter)
        w = waiting(conn)
        return {"current": full_ticket(cur) if cur else None, "waiting_total": len(w),
                "next_preview": [{"ticket_no": r["ticket_no"], "service": r["service"], "kind": r["kind"]}
                                 for r in w[:5]]}


@app.post("/api/teller/call", dependencies=[Depends(teller_auth)])
def teller_call(c: CounterReq):
    valid_counter(c.counter)
    with tx() as conn:
        if current_for(conn, c.counter):
            raise HTTPException(409, "처리 중인 고객이 있습니다. 먼저 완료하거나 노쇼 처리하세요.")
        w = waiting(conn)
        if not w:
            raise HTTPException(404, "대기 중인 고객이 없습니다.")
        conn.execute("UPDATE tickets SET status='called', counter=?, called_at=? WHERE id=?",
                     (c.counter, db.iso(db.now()), w[0]["id"]))
        return {"current": full_ticket(conn.execute("SELECT * FROM tickets WHERE id=?", (w[0]["id"],)).fetchone())}


def transition(counter, allowed_from, set_sql):
    valid_counter(counter)
    with tx() as conn:
        cur = current_for(conn, counter)
        if not cur or cur["status"] not in allowed_from:
            raise HTTPException(409, "현재 상태에서는 할 수 없는 동작입니다.")
        conn.execute(f"UPDATE tickets SET {set_sql} WHERE id=?", (db.iso(db.now()), cur["id"]))
    return {"ok": True}


@app.post("/api/teller/start", dependencies=[Depends(teller_auth)])
def teller_start(c: CounterReq):
    return transition(c.counter, ("called",), "status='serving', started_at=?")


@app.post("/api/teller/complete", dependencies=[Depends(teller_auth)])
def teller_complete(c: CounterReq):
    return transition(c.counter, ("serving",), "status='done', finished_at=?")


@app.post("/api/teller/noshow", dependencies=[Depends(teller_auth)])
def teller_noshow(c: CounterReq):
    return transition(c.counter, ("called",), "status='noshow', finished_at=?")


# ---------- manager (personal data masked) ----------
@app.get("/api/manager/stats", dependencies=[Depends(manager_auth)])
def manager_stats():
    today = datetime.now().date().isoformat()
    with read() as conn:
        rows = conn.execute("SELECT * FROM tickets WHERE date(COALESCE(reserved_at,created_at))=? ORDER BY id",
                            (today,)).fetchall()
        counts = {s: 0 for s in ("reserved", "waiting", "called", "serving", "done", "noshow")}
        by_service = {s: {"waiting": 0, "done": 0, "noshow": 0} for s in SERVICES}
        waits = []
        for r in rows:
            counts[r["status"]] += 1
            if r["status"] in ("waiting", "done", "noshow"):
                by_service[r["service"]][r["status"]] += 1
            if r["called_at"] and r["checked_in_at"]:
                waits.append((datetime.fromisoformat(r["called_at"]) -
                              datetime.fromisoformat(r["checked_in_at"])).total_seconds())
        w = waiting(conn)
        # longest wait is measured from arrival, not queue position
        longest = int((datetime.now() - min(datetime.fromisoformat(r["checked_in_at"]) for r in w)).total_seconds() // 60) if w else None
        resv = [r for r in rows if r["kind"] == "reservation"]
        resv_noshow = len([r for r in resv if r["status"] == "noshow"])
        active = {r["counter"]: r for r in rows if r["status"] in ("called", "serving")}
        return {
            "counts": counts,
            "by_service": by_service,
            "avg_wait_min": round(sum(waits) / len(waits) / 60, 1) if waits else None,
            "longest_wait_min": longest,
            "reservations_total": len(resv),
            "noshow_count": resv_noshow + len([r for r in rows if r["kind"] == "walkin" and r["status"] == "noshow"]),
            "noshow_rate": round(resv_noshow / len(resv) * 100, 1) if resv else 0,
            "noshows": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"]), "phone": mask_phone(r["phone"]),
                         "service": r["service"], "kind": r["kind"], "reserved_at": r["reserved_at"]}
                        for r in rows if r["status"] == "noshow"],
            "upcoming": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"]), "service": r["service"],
                          "reserved_at": r["reserved_at"]} for r in rows if r["status"] == "reserved"],
            "queue": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"]), "service": r["service"],
                       "kind": r["kind"], "checked_in_at": r["checked_in_at"]} for r in w],
            "counters": [{"counter": n, "ticket_no": active[n]["ticket_no"] if n in active else None,
                          "status": active[n]["status"] if n in active else "idle"} for n in COUNTERS],
        }


# ---------- pages ----------
app.mount("/", StaticFiles(directory=os.path.join(BASE, "static"), html=True), name="static")
