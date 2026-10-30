"""두둑은행 지점 방문 예약 · 대기 현황판 (FastAPI + SQLite)"""
import os
import re
import sqlite3
import random
from contextlib import contextmanager
from datetime import datetime, timedelta, date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DUDUK_DB", str(BASE / "duduk.db"))
TELLER_PIN = os.environ.get("TELLER_PIN", "1234")
MANAGER_PIN = os.environ.get("MANAGER_PIN", "9999")
COUNTERS = [1, 2, 3]
NOSHOW_GRACE_MIN = 15
SLOT_CAPACITY = 3
SERVICES = {"예금": "D", "대출": "L", "외환": "F"}
OPEN_H, CLOSE_H = 9, 16  # 마지막 슬롯 15:30

app = FastAPI(title="두둑은행 대기 현황판")


# ---------- DB ----------
@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS visits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, phone TEXT NOT NULL, account TEXT NOT NULL,
            service TEXT NOT NULL, kind TEXT NOT NULL,          -- reservation | walkin
            slot_at TEXT, status TEXT NOT NULL,                 -- reserved|waiting|called|serving|done|no_show
            ticket_no TEXT, day TEXT NOT NULL,
            created_at TEXT NOT NULL, checkin_at TEXT, called_at TEXT,
            started_at TEXT, done_at TEXT, counter INTEGER)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_day_status ON visits(day, status)")
        if c.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0:
            seed(c)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def next_ticket(c, service, day):
    prefix = SERVICES[service]
    n = c.execute("SELECT COUNT(*) FROM visits WHERE day=? AND ticket_no LIKE ?",
                  (day, prefix + "%")).fetchone()[0]
    return f"{prefix}{n + 1:03d}"


def seed(c):
    """가상 데이터: 현재 시각 기준으로 대기/호출/완료/노쇼/예약이 섞이게 생성"""
    rnd = random.Random(7)
    now = datetime.now()
    today = now.date().isoformat()
    sn = "김이박최정강조윤장임한오서신권황안송류홍"
    gn = ["민준", "서연", "도윤", "지우", "하준", "서윤", "예준", "지민", "수아", "시우",
          "하은", "주원", "채원", "지호", "유나", "건우", "다은", "현우", "소율", "태민",
          "나영", "준서", "은지", "성호", "민재", "보람", "동현", "혜진"]
    used = set()

    def person():
        while True:
            nm = rnd.choice(sn) + rnd.choice(gn)
            if nm not in used:
                used.add(nm)
                return (nm, f"010-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}",
                        f"{rnd.choice(['110','302','421'])}-{rnd.randint(100,999)}-{rnd.randint(100000,999999)}")

    def add(kind, service, status, slot=None, checkin=None, called=None, started=None,
            done=None, counter=None, day=today):
        nm, ph, ac = person()
        tno = None
        if status != "reserved" and (kind == "walkin" or checkin):
            tno = next_ticket(c, service, day)
        c.execute("""INSERT INTO visits(name,phone,account,service,kind,slot_at,status,ticket_no,day,
                     created_at,checkin_at,called_at,started_at,done_at,counter)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (nm, ph, ac, service, kind, slot and iso(slot), status, tno, day,
                   iso(now - timedelta(hours=3)), checkin and iso(checkin), called and iso(called),
                   started and iso(started), done and iso(done), counter))

    svc = lambda: rnd.choice(list(SERVICES))
    m = lambda x: now - timedelta(minutes=x)
    # 처리 완료 (오늘 아침)
    for i in range(8):
        k = "reservation" if i % 3 == 0 else "walkin"
        s = svc()
        ci = m(150 - i * 12)
        add(k, s, "done", slot=ci if k == "reservation" else None, checkin=ci,
            called=ci + timedelta(minutes=rnd.randint(2, 9)),
            started=ci + timedelta(minutes=rnd.randint(10, 12)),
            done=ci + timedelta(minutes=rnd.randint(16, 28)), counter=rnd.choice(COUNTERS))
    # 노쇼 (예약 후 미방문 / 호출 후 미응답)
    for off in (95, 70, 50):
        add("reservation", svc(), "no_show", slot=m(off))
    add("walkin", svc(), "no_show", checkin=m(60), called=m(45), counter=2)
    # 진행 중
    add("reservation", "대출", "serving", slot=m(30), checkin=m(32), called=m(8), started=m(6), counter=1)
    add("walkin", "예금", "called", checkin=m(25), called=m(1), counter=2)
    # 대기: 현장 + 예약 체크인 혼합
    for off in (22, 20, 17, 15, 12):
        add("walkin", svc(), "waiting", checkin=m(off))
    for off in (10, 6):
        add("reservation", svc(), "waiting", slot=m(off + 8), checkin=m(off))
    # 이후 예약(미도착)
    for mins in (10, 30, 60, 90, 120):
        slot = (now + timedelta(minutes=mins)).replace(second=0, microsecond=0)
        slot = slot.replace(minute=0 if slot.minute < 30 else 30)
        add("reservation", svc(), "reserved", slot=slot)
    # 내일 예약
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    for hh in (9, 11, 14):
        add("reservation", svc(), "reserved", day=tomorrow,
            slot=datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).replace(hour=hh))


# ---------- 공통 ----------
def sweep_noshow(c):
    """예약 시간 + 유예시간이 지나도록 체크인 안 한 예약은 노쇼 처리"""
    limit = iso(datetime.now() - timedelta(minutes=NOSHOW_GRACE_MIN))
    c.execute("UPDATE visits SET status='no_show' WHERE status='reserved' AND slot_at < ?", (limit,))


def today():
    return date.today().isoformat()


def mask_name(n):
    return n[0] + "*" * (len(n) - 2) + n[-1] if len(n) > 2 else n[0] + "*"


def mask_phone(p):
    d = p.split("-")
    return f"{d[0]}-****-{d[-1]}" if len(d) == 3 else p[:3] + "****" + p[-4:]


def mask_account(a):
    return re.sub(r"\d(?=\d*-?\d{4}$)", "*", a) if len(a) > 4 else a


QUEUE_ORDER = """ORDER BY (kind!='reservation'), COALESCE(slot_at, checkin_at), checkin_at, id"""


def waiting_list(c):
    return c.execute(f"SELECT * FROM visits WHERE day=? AND status='waiting' {QUEUE_ORDER}",
                     (today(),)).fetchall()


def require(pin_env):
    def dep(x_staff_pin: str = Header(default="")):
        if x_staff_pin != pin_env:
            raise HTTPException(401, "PIN이 올바르지 않습니다.")
    return dep


# ---------- 모델 ----------
class Customer(BaseModel):
    name: str
    phone: str
    account: str
    service: str

    def validate_fields(self):
        self.name = self.name.strip()
        if not (2 <= len(self.name) <= 20):
            raise HTTPException(422, "이름은 2~20자로 입력해 주세요.")
        digits = re.sub(r"\D", "", self.phone)
        if not re.fullmatch(r"01\d{8,9}", digits):
            raise HTTPException(422, "휴대전화 번호 형식이 올바르지 않습니다.")
        self.phone = f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"
        if not re.fullmatch(r"[\d-]{10,20}", self.account) or not 10 <= len(re.sub(r"\D", "", self.account)) <= 16:
            raise HTTPException(422, "계좌번호는 숫자 10~16자리로 입력해 주세요.")
        self.account = self.account.strip()
        if self.service not in SERVICES:
            raise HTTPException(422, "업무 종류를 선택해 주세요.")


class Reservation(Customer):
    slot_date: str
    slot_time: str


class CheckIn(BaseModel):
    phone: str


class CallReq(BaseModel):
    counter: int


# ---------- 고객 ----------
def slot_times():
    return [f"{h:02d}:{m:02d}" for h in range(OPEN_H, CLOSE_H) for m in (0, 30)]


@app.get("/api/slots")
def slots(d: str):
    try:
        day = date.fromisoformat(d)
    except ValueError:
        raise HTTPException(422, "날짜 형식 오류")
    now = datetime.now()
    if not now.date() <= day <= now.date() + timedelta(days=7):
        raise HTTPException(422, "오늘부터 7일 이내만 예약할 수 있습니다.")
    with db() as c:
        out = []
        for t in slot_times():
            at = datetime.fromisoformat(f"{d}T{t}:00")
            used = c.execute("SELECT COUNT(*) FROM visits WHERE kind='reservation' AND slot_at=? "
                             "AND status!='no_show'", (iso(at),)).fetchone()[0]
            left = SLOT_CAPACITY - used
            out.append({"time": t, "left": max(left, 0), "open": left > 0 and at > now})
        return out


@app.post("/api/reservations")
def reserve(r: Reservation):
    r.validate_fields()
    try:
        at = datetime.fromisoformat(f"{r.slot_date}T{r.slot_time}:00")
    except ValueError:
        raise HTTPException(422, "예약 일시 형식 오류")
    if r.slot_time not in slot_times() or at <= datetime.now() or at.date() > date.today() + timedelta(days=7):
        raise HTTPException(422, "예약할 수 없는 시간입니다.")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            used = c.execute("SELECT COUNT(*) FROM visits WHERE kind='reservation' AND slot_at=? "
                             "AND status!='no_show'", (iso(at),)).fetchone()[0]
            if used >= SLOT_CAPACITY:
                raise HTTPException(409, "해당 시간은 예약이 마감되었습니다.")
            dup = c.execute("SELECT 1 FROM visits WHERE phone=? AND day=? AND status IN ('reserved','waiting','called','serving')",
                            (r.phone, r.slot_date)).fetchone()
            if dup:
                raise HTTPException(409, "같은 날 이미 예약(또는 대기)이 있습니다.")
            cur = c.execute("""INSERT INTO visits(name,phone,account,service,kind,slot_at,status,day,created_at)
                               VALUES(?,?,?,?,'reservation',?,'reserved',?,?)""",
                            (r.name, r.phone, r.account, r.service, iso(at), r.slot_date, iso(datetime.now())))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return {"id": cur.lastrowid, "slot": f"{r.slot_date} {r.slot_time}",
            "message": "예약되었습니다. 방문 시 키오스크에서 '예약 확인'으로 번호표를 받으세요."}


def issue(c, v_id=None, cust: Customer = None):
    """대기열 진입 (번호표 발급). 트랜잭션은 호출자가 잡는다."""
    now = iso(datetime.now())
    if v_id:
        v = c.execute("SELECT * FROM visits WHERE id=?", (v_id,)).fetchone()
        tno = next_ticket(c, v["service"], v["day"])
        c.execute("UPDATE visits SET status='waiting', ticket_no=?, checkin_at=? WHERE id=?", (tno, now, v_id))
        return tno, v_id
    tno = next_ticket(c, cust.service, today())
    cur = c.execute("""INSERT INTO visits(name,phone,account,service,kind,status,ticket_no,day,created_at,checkin_at)
                       VALUES(?,?,?,?,'walkin','waiting',?,?,?,?)""",
                    (cust.name, cust.phone, cust.account, cust.service, tno, today(), now, now))
    return tno, cur.lastrowid


def ticket_response(c, tno, vid):
    ahead = [v for v in waiting_list(c)]
    pos = next((i for i, v in enumerate(ahead) if v["id"] == vid), 0)
    return {"ticket_no": tno, "ahead": pos, "kind": c.execute("SELECT kind FROM visits WHERE id=?", (vid,)).fetchone()[0]}


@app.post("/api/tickets")
def take_ticket(cust: Customer):
    cust.validate_fields()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            sweep_noshow(c)
            ex = c.execute("SELECT * FROM visits WHERE phone=? AND day=? AND status IN ('waiting','called','serving')",
                           (cust.phone, today())).fetchone()
            if ex:
                c.execute("COMMIT")
                return {**ticket_response(c, ex["ticket_no"], ex["id"]), "existing": True}
            res = c.execute("SELECT id FROM visits WHERE phone=? AND day=? AND status='reserved'",
                            (cust.phone, today())).fetchone()
            tno, vid = issue(c, v_id=res["id"]) if res else issue(c, cust=cust)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return {**ticket_response(c, tno, vid), "existing": False, "from_reservation": bool(res)}


@app.post("/api/checkin")
def checkin(req: CheckIn):
    digits = re.sub(r"\D", "", req.phone)
    if len(digits) < 10:
        raise HTTPException(422, "휴대전화 번호를 입력해 주세요.")
    phone = f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            sweep_noshow(c)
            ex = c.execute("SELECT * FROM visits WHERE phone=? AND day=? AND status IN ('waiting','called','serving')",
                           (phone, today())).fetchone()
            if ex:
                c.execute("COMMIT")
                return {**ticket_response(c, ex["ticket_no"], ex["id"]), "existing": True}
            res = c.execute("SELECT id FROM visits WHERE phone=? AND day=? AND status='reserved' AND kind='reservation' "
                            "ORDER BY slot_at LIMIT 1", (phone, today())).fetchone()
            if not res:
                nos = c.execute("SELECT 1 FROM visits WHERE phone=? AND day=? AND status='no_show' AND kind='reservation'",
                                (phone, today())).fetchone()
                c.execute("COMMIT")
                raise HTTPException(404, "예약 시간이 지나 노쇼 처리되었습니다. 현장 번호표를 뽑아 주세요."
                                    if nos else "오늘 날짜의 예약을 찾을 수 없습니다.")
            tno, vid = issue(c, v_id=res["id"])
            c.execute("COMMIT")
        except HTTPException:
            raise
        except Exception:
            c.execute("ROLLBACK")
            raise
        return {**ticket_response(c, tno, vid), "existing": False, "from_reservation": True}


# ---------- 대기 화면 ----------
@app.get("/api/board")
def board():
    with db() as c:
        sweep_noshow(c)
        active = c.execute("SELECT * FROM visits WHERE day=? AND status IN ('called','serving') "
                           "ORDER BY called_at DESC", (today(),)).fetchall()
        wait = waiting_list(c)
        by_counter = {a["counter"]: a for a in active}
        return {
            "now": iso(datetime.now()),
            "counters": [{"counter": n,
                          "ticket_no": by_counter[n]["ticket_no"] if n in by_counter else None,
                          "status": by_counter[n]["status"] if n in by_counter else "idle"} for n in COUNTERS],
            "waiting": [{"ticket_no": w["ticket_no"], "service": w["service"],
                         "priority": w["kind"] == "reservation"} for w in wait],
            "waiting_total": len(wait),
        }


# ---------- 창구 직원 ----------
def detail(v):
    return {"id": v["id"], "ticket_no": v["ticket_no"], "name": v["name"], "phone": v["phone"],
            "account": v["account"], "service": v["service"], "kind": v["kind"],
            "slot_at": v["slot_at"], "checkin_at": v["checkin_at"], "status": v["status"],
            "called_at": v["called_at"], "counter": v["counter"]}


@app.get("/api/teller/state", dependencies=[Depends(require(TELLER_PIN))])
def teller_state(counter: int):
    if counter not in COUNTERS:
        raise HTTPException(404, "없는 창구")
    with db() as c:
        sweep_noshow(c)
        cur = c.execute("SELECT * FROM visits WHERE day=? AND counter=? AND status IN ('called','serving')",
                        (today(), counter)).fetchone()
        wait = waiting_list(c)
        return {"current": detail(cur) if cur else None,
                "waiting": [{"ticket_no": w["ticket_no"], "service": w["service"],
                             "priority": w["kind"] == "reservation"} for w in wait]}


@app.post("/api/teller/call", dependencies=[Depends(require(TELLER_PIN))])
def teller_call(req: CallReq):
    if req.counter not in COUNTERS:
        raise HTTPException(404, "없는 창구")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            sweep_noshow(c)
            if c.execute("SELECT 1 FROM visits WHERE day=? AND counter=? AND status IN ('called','serving')",
                         (today(), req.counter)).fetchone():
                raise HTTPException(409, "처리 중인 고객이 있습니다. 완료 또는 노쇼 처리 후 호출하세요.")
            nxt = c.execute(f"SELECT * FROM visits WHERE day=? AND status='waiting' {QUEUE_ORDER} LIMIT 1",
                            (today(),)).fetchone()
            if not nxt:
                raise HTTPException(404, "대기 중인 고객이 없습니다.")
            c.execute("UPDATE visits SET status='called', counter=?, called_at=? WHERE id=?",
                      (req.counter, iso(datetime.now()), nxt["id"]))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return detail(c.execute("SELECT * FROM visits WHERE id=?", (nxt["id"],)).fetchone())


def transition(vid, counter, allowed, sets, label):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            v = c.execute("SELECT * FROM visits WHERE id=?", (vid,)).fetchone()
            if not v or v["counter"] != counter or v["status"] not in allowed:
                raise HTTPException(409, f"{label}할 수 없는 상태입니다.")
            c.execute(f"UPDATE visits SET {sets[0]} WHERE id=?", (*sets[1], vid))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return {"ok": True}


@app.post("/api/teller/{vid}/start", dependencies=[Depends(require(TELLER_PIN))])
def t_start(vid: int, req: CallReq):
    return transition(vid, req.counter, ("called",), ("status='serving', started_at=?", (iso(datetime.now()),)), "상담 시작")


@app.post("/api/teller/{vid}/done", dependencies=[Depends(require(TELLER_PIN))])
def t_done(vid: int, req: CallReq):
    return transition(vid, req.counter, ("serving",), ("status='done', done_at=?", (iso(datetime.now()),)), "완료")


@app.post("/api/teller/{vid}/noshow", dependencies=[Depends(require(TELLER_PIN))])
def t_noshow(vid: int, req: CallReq):
    return transition(vid, req.counter, ("called",), ("status='no_show', done_at=?", (iso(datetime.now()),)), "노쇼 처리")


@app.post("/api/teller/{vid}/recall", dependencies=[Depends(require(TELLER_PIN))])
def t_recall(vid: int, req: CallReq):
    return transition(vid, req.counter, ("called",), ("called_at=?", (iso(datetime.now()),)), "재호출")


# ---------- 지점장 ----------
@app.get("/api/manager/summary", dependencies=[Depends(require(MANAGER_PIN))])
def manager_summary():
    with db() as c:
        sweep_noshow(c)
        d = today()
        rows = c.execute("SELECT * FROM visits WHERE day=?", (d,)).fetchall()
        cnt = lambda st: sum(1 for r in rows if r["status"] in st)
        wait = [r for r in rows if r["status"] == "waiting"]
        now = datetime.now()
        waits = [(datetime.fromisoformat(r["called_at"]) - datetime.fromisoformat(r["checkin_at"])).total_seconds() / 60
                 for r in rows if r["called_at"] and r["checkin_at"]]
        durs = [(datetime.fromisoformat(r["done_at"]) - datetime.fromisoformat(r["started_at"])).total_seconds() / 60
                for r in rows if r["status"] == "done" and r["started_at"] and r["done_at"]]
        longest = max(((now - datetime.fromisoformat(r["checkin_at"])).total_seconds() / 60 for r in wait), default=0)
        resv = [r for r in rows if r["kind"] == "reservation"]
        resv_ns = [r for r in resv if r["status"] == "no_show"]
        noshows = [r for r in rows if r["status"] == "no_show"]
        return {
            "date": d,
            "waiting": len(wait),
            "waiting_by_service": {s: sum(1 for r in wait if r["service"] == s) for s in SERVICES},
            "waiting_priority": sum(1 for r in wait if r["kind"] == "reservation"),
            "in_progress": cnt(("called", "serving")),
            "done": cnt(("done",)),
            "upcoming_reservations": cnt(("reserved",)),
            "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else 0,
            "avg_service_min": round(sum(durs) / len(durs), 1) if durs else 0,
            "longest_wait_min": round(longest, 1),
            "no_show_count": len(noshows),
            "reservation_no_show_rate": round(100 * len(resv_ns) / len(resv)) if resv else 0,
            "no_shows": [{"ticket_no": r["ticket_no"], "name": mask_name(r["name"]), "phone": mask_phone(r["phone"]),
                          "service": r["service"], "kind": r["kind"],
                          "when": r["slot_at"] or r["called_at"],
                          "reason": "예약 후 미방문" if not r["checkin_at"] else "호출 후 미응답"}
                         for r in sorted(noshows, key=lambda r: r["slot_at"] or r["called_at"] or "", reverse=True)],
            "upcoming": [{"name": mask_name(r["name"]), "service": r["service"], "slot_at": r["slot_at"]}
                         for r in sorted((r for r in rows if r["status"] == "reserved"), key=lambda r: r["slot_at"])],
            "counters": [{"counter": n, **_counter_info(rows, n)} for n in COUNTERS],
        }


def _counter_info(rows, n):
    cur = next((r for r in rows if r["counter"] == n and r["status"] in ("called", "serving")), None)
    return {"ticket_no": cur["ticket_no"] if cur else None, "status": cur["status"] if cur else "idle",
            "done": sum(1 for r in rows if r["counter"] == n and r["status"] == "done")}


# ---------- 정적 페이지 ----------
@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
