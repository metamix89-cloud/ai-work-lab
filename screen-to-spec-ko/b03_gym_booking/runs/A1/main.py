"""으랏차차헬스 PT 수업 예약 · 회원권 차감 (FastAPI + SQLite)

규칙
- 예약: 잔여 횟수(= 남은 횟수 - 예약 중인 수업 수) 1회 이상, 회원권 만료일 이내, 정원 이내,
        시간이 겹치는 예약 없음, 노쇼 제한 중이 아닐 것
- 차감: 예약 시점이 아니라 데스크가 '출석' 또는 '노쇼' 처리할 때 1회 차감 (원장 ledger 기록)
- 취소: 수업 시작 CANCEL_DEADLINE_HOURS 시간 전까지만 회원이 직접 가능. 이후는 데스크만 (차감 없음)
- 노쇼 제한: 최근 NOSHOW_WINDOW_DAYS 일 안에 노쇼 NOSHOW_LIMIT 회 이상이면 예약 차단
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PT_DB", os.path.join(BASE, "pt.db"))

CANCEL_DEADLINE_HOURS = 24
NOSHOW_LIMIT = 3
NOSHOW_WINDOW_DAYS = 30
ATTEND_OPEN_MIN = 30      # 수업 시작 30분 전부터 출석 처리 가능
NOSHOW_AFTER_MIN = 10     # 수업 시작 10분 후부터 노쇼 처리 가능
CHARGED = ("attended", "noshow")  # 회원권 1회가 차감되는 상태

FMT = "%Y-%m-%dT%H:%M"


def now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT)


# ---------------------------------------------------------------- DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS members(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trainers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(
  id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id),
  name TEXT NOT NULL, total INTEGER NOT NULL CHECK(total > 0),
  remaining INTEGER NOT NULL CHECK(remaining >= 0),
  expires_on TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS slots(
  id INTEGER PRIMARY KEY, trainer_id INTEGER NOT NULL REFERENCES trainers(id),
  start_at TEXT NOT NULL, end_at TEXT NOT NULL,
  capacity INTEGER NOT NULL CHECK(capacity > 0));
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES slots(id),
  member_id INTEGER NOT NULL REFERENCES members(id),
  membership_id INTEGER NOT NULL REFERENCES memberships(id),
  status TEXT NOT NULL CHECK(status IN ('booked','attended','noshow','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_booking
  ON bookings(slot_id, member_id) WHERE status != 'cancelled';
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY, membership_id INTEGER NOT NULL REFERENCES memberships(id),
  booking_id INTEGER, delta INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
"""


@contextmanager
def tx():
    """쓰기 트랜잭션. BEGIN IMMEDIATE 로 동시 예약 시 정원/잔여 검사가 깨지지 않게 직렬화."""
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


@contextmanager
def ro():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def err(code: int, msg: str):
    raise HTTPException(code, msg)


# ---------------------------------------------------------------- 도메인 로직
def reserved(con, membership_id: int) -> int:
    return con.execute("SELECT COUNT(*) FROM bookings WHERE membership_id=? AND status='booked'",
                       (membership_id,)).fetchone()[0]


def noshow_state(con, member_id: int) -> dict:
    """최근 N일 노쇼 횟수와 제한 해제일."""
    since = (now() - timedelta(days=NOSHOW_WINDOW_DAYS)).strftime(FMT)
    rows = con.execute(
        "SELECT s.start_at FROM bookings b JOIN slots s ON s.id=b.slot_id "
        "WHERE b.member_id=? AND b.status='noshow' AND s.start_at>=? ORDER BY s.start_at DESC",
        (member_id, since)).fetchall()
    cnt = len(rows)
    blocked_until = None
    if cnt >= NOSHOW_LIMIT:
        # 가장 최근 LIMIT 건 중 가장 오래된 노쇼가 윈도우 밖으로 나가는 시점
        blocked_until = (parse(rows[NOSHOW_LIMIT - 1]["start_at"]) + timedelta(days=NOSHOW_WINDOW_DAYS)).strftime(FMT)
    return {"count": cnt, "limit": NOSHOW_LIMIT, "blocked": cnt >= NOSHOW_LIMIT, "blocked_until": blocked_until}


def apply_status(con, b, new: str, reason: str):
    """예약 상태 변경 + 회원권 차감/복구를 한 곳에서 처리 (변경 전후 차감 여부의 차이만 반영 → 멱등)."""
    old = b["status"]
    delta = -(new in CHARGED) + (old in CHARGED)
    if delta:
        m = con.execute("SELECT remaining FROM memberships WHERE id=?", (b["membership_id"],)).fetchone()
        if m["remaining"] + delta < 0:
            err(409, "회원권 잔여 횟수가 부족해 차감할 수 없습니다.")
        con.execute("UPDATE memberships SET remaining=remaining+? WHERE id=?", (delta, b["membership_id"]))
        con.execute("INSERT INTO ledger(membership_id,booking_id,delta,reason,created_at) VALUES(?,?,?,?,?)",
                    (b["membership_id"], b["id"], delta, reason, now().strftime(FMT)))
    con.execute("UPDATE bookings SET status=?, updated_at=? WHERE id=?", (new, now().strftime(FMT), b["id"]))


def get_booking(con, bid: int):
    b = con.execute("SELECT b.*, s.start_at, s.end_at FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.id=?",
                    (bid,)).fetchone()
    if not b:
        err(404, "예약을 찾을 수 없습니다.")
    return b


# ---------------------------------------------------------------- API
app = FastAPI(title="으랏차차헬스 PT 예약")


class BookIn(BaseModel):
    member_id: int
    slot_id: int


class CancelIn(BaseModel):
    by: Literal["member", "desk"] = "member"


class SellIn(BaseModel):
    name: str
    total: int
    valid_days: int = 90


class SlotIn(BaseModel):
    trainer_id: int
    start_at: str
    minutes: int = 50
    capacity: int = 1


class MemberIn(BaseModel):
    name: str
    phone: str


@app.get("/api/config")
def config():
    return {"cancel_deadline_hours": CANCEL_DEADLINE_HOURS, "noshow_limit": NOSHOW_LIMIT,
            "noshow_window_days": NOSHOW_WINDOW_DAYS, "attend_open_min": ATTEND_OPEN_MIN,
            "noshow_after_min": NOSHOW_AFTER_MIN, "now": now().strftime(FMT)}


@app.get("/api/trainers")
def trainers():
    with ro() as con:
        return [dict(r) for r in con.execute("SELECT * FROM trainers")]


@app.get("/api/members")
def members():
    with ro() as con:
        out = []
        for m in con.execute("SELECT * FROM members ORDER BY name"):
            d = dict(m)
            d["noshow"] = noshow_state(con, m["id"])
            d["remaining"] = con.execute(
                "SELECT COALESCE(SUM(remaining),0) FROM memberships WHERE member_id=? AND expires_on>=?",
                (m["id"], now().strftime("%Y-%m-%d"))).fetchone()[0]
            out.append(d)
        return out


@app.post("/api/members")
def add_member(p: MemberIn):
    with tx() as con:
        cur = con.execute("INSERT INTO members(name,phone) VALUES(?,?)", (p.name.strip(), p.phone.strip()))
        return {"id": cur.lastrowid}


@app.get("/api/members/{mid}")
def member_detail(mid: int):
    with ro() as con:
        m = con.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
        if not m:
            err(404, "회원을 찾을 수 없습니다.")
        today = now().strftime("%Y-%m-%d")
        ms = []
        for r in con.execute("SELECT * FROM memberships WHERE member_id=? ORDER BY expires_on", (mid,)):
            d = dict(r)
            d["reserved"] = reserved(con, r["id"])
            d["available"] = r["remaining"] - d["reserved"]
            d["expired"] = r["expires_on"] < today
            ms.append(d)
        bk = [dict(r) for r in con.execute(
            "SELECT b.id,b.status,b.slot_id,b.membership_id,s.start_at,s.end_at,t.name trainer "
            "FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN trainers t ON t.id=s.trainer_id "
            "WHERE b.member_id=? ORDER BY s.start_at DESC", (mid,))]
        limit = now() + timedelta(hours=CANCEL_DEADLINE_HOURS)
        for b in bk:
            b["can_cancel"] = b["status"] == "booked" and parse(b["start_at"]) >= limit
        led = [dict(r) for r in con.execute(
            "SELECT l.*, ms.name membership FROM ledger l JOIN memberships ms ON ms.id=l.membership_id "
            "WHERE ms.member_id=? ORDER BY l.id DESC LIMIT 30", (mid,))]
        return {"member": dict(m), "memberships": ms, "bookings": bk, "ledger": led,
                "noshow": noshow_state(con, mid)}


@app.post("/api/members/{mid}/memberships")
def sell_membership(mid: int, p: SellIn):
    if p.total <= 0 or p.valid_days <= 0:
        err(422, "횟수와 유효기간은 1 이상이어야 합니다.")
    with tx() as con:
        if not con.execute("SELECT 1 FROM members WHERE id=?", (mid,)).fetchone():
            err(404, "회원을 찾을 수 없습니다.")
        exp = (now() + timedelta(days=p.valid_days)).strftime("%Y-%m-%d")
        cur = con.execute("INSERT INTO memberships(member_id,name,total,remaining,expires_on,created_at) "
                          "VALUES(?,?,?,?,?,?)", (mid, p.name, p.total, p.total, exp, now().strftime(FMT)))
        con.execute("INSERT INTO ledger(membership_id,booking_id,delta,reason,created_at) VALUES(?,?,?,?,?)",
                    (cur.lastrowid, None, p.total, "회원권 등록", now().strftime(FMT)))
        return {"id": cur.lastrowid}


def slot_rows(con, where="", args=()):
    rows = con.execute(
        "SELECT s.*, t.name trainer, "
        "(SELECT COUNT(*) FROM bookings b WHERE b.slot_id=s.id AND b.status!='cancelled') taken "
        f"FROM slots s JOIN trainers t ON t.id=s.trainer_id {where} ORDER BY s.start_at", args).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/slots")
def slots(days: int = 7, member_id: Optional[int] = None):
    """앞으로 days 일간의 수업. member_id 를 주면 그 회원의 예약 여부/예약 가능 여부 사유를 함께 반환."""
    with ro() as con:
        start = now().strftime(FMT)
        end = (now() + timedelta(days=days)).strftime(FMT)
        out = slot_rows(con, "WHERE s.start_at>=? AND s.start_at<=?", (start, end))
        if member_id:
            blocked = noshow_state(con, member_id)["blocked"]
            mine = {r["slot_id"]: r["id"] for r in con.execute(
                "SELECT id,slot_id FROM bookings WHERE member_id=? AND status='booked'", (member_id,))}
            for s in out:
                s["my_booking_id"] = mine.get(s["id"])
                s["reason"] = None
                if s["id"] in mine:
                    s["reason"] = "예약됨"
                elif s["taken"] >= s["capacity"]:
                    s["reason"] = "정원 마감"
                elif blocked:
                    s["reason"] = "노쇼 제한"
        return out


@app.post("/api/slots")
def add_slot(p: SlotIn):
    try:
        st = parse(p.start_at)
    except ValueError:
        err(422, "시작 시각 형식은 YYYY-MM-DDTHH:MM 입니다.")
    if p.capacity < 1 or p.minutes < 10:
        err(422, "정원/시간 값이 올바르지 않습니다.")
    with tx() as con:
        if not con.execute("SELECT 1 FROM trainers WHERE id=?", (p.trainer_id,)).fetchone():
            err(404, "트레이너를 찾을 수 없습니다.")
        end = (st + timedelta(minutes=p.minutes)).strftime(FMT)
        clash = con.execute("SELECT 1 FROM slots WHERE trainer_id=? AND start_at<? AND end_at>?",
                            (p.trainer_id, end, st.strftime(FMT))).fetchone()
        if clash:
            err(409, "해당 트레이너의 다른 수업과 시간이 겹칩니다.")
        cur = con.execute("INSERT INTO slots(trainer_id,start_at,end_at,capacity) VALUES(?,?,?,?)",
                          (p.trainer_id, st.strftime(FMT), end, p.capacity))
        return {"id": cur.lastrowid}


@app.post("/api/bookings")
def book(p: BookIn):
    with tx() as con:
        m = con.execute("SELECT * FROM members WHERE id=?", (p.member_id,)).fetchone()
        s = con.execute("SELECT * FROM slots WHERE id=?", (p.slot_id,)).fetchone()
        if not m or not s:
            err(404, "회원 또는 수업을 찾을 수 없습니다.")
        if parse(s["start_at"]) <= now():
            err(409, "이미 시작했거나 지난 수업입니다.")
        ns = noshow_state(con, p.member_id)
        if ns["blocked"]:
            err(403, f"최근 {NOSHOW_WINDOW_DAYS}일 내 노쇼 {ns['count']}회로 예약이 제한되었습니다. "
                     f"({ns['blocked_until'].replace('T', ' ')} 이후 가능, 급하면 데스크 문의)")
        if con.execute("SELECT 1 FROM bookings WHERE slot_id=? AND member_id=? AND status!='cancelled'",
                       (p.slot_id, p.member_id)).fetchone():
            err(409, "이미 예약한 수업입니다.")
        if con.execute(
                "SELECT 1 FROM bookings b JOIN slots o ON o.id=b.slot_id WHERE b.member_id=? AND b.status='booked' "
                "AND o.start_at<? AND o.end_at>?", (p.member_id, s["end_at"], s["start_at"])).fetchone():
            err(409, "같은 시간대에 이미 예약한 수업이 있습니다.")
        taken = con.execute("SELECT COUNT(*) FROM bookings WHERE slot_id=? AND status!='cancelled'",
                            (p.slot_id,)).fetchone()[0]
        if taken >= s["capacity"]:
            err(409, "정원이 가득 찼습니다.")
        # 수업일 기준 유효한 회원권 중 만료가 가장 빠른 것부터 사용
        pick = None
        for ms in con.execute("SELECT * FROM memberships WHERE member_id=? AND expires_on>=? "
                              "ORDER BY expires_on, id", (p.member_id, s["start_at"][:10])):
            if ms["remaining"] - reserved(con, ms["id"]) > 0:
                pick = ms
                break
        if not pick:
            err(409, "사용 가능한 회원권(잔여 횟수 · 유효기간)이 없습니다.")
        t = now().strftime(FMT)
        cur = con.execute("INSERT INTO bookings(slot_id,member_id,membership_id,status,created_at,updated_at) "
                          "VALUES(?,?,?,'booked',?,?)", (p.slot_id, p.member_id, pick["id"], t, t))
        return {"id": cur.lastrowid, "membership": pick["name"]}


@app.post("/api/bookings/{bid}/cancel")
def cancel(bid: int, p: CancelIn):
    with tx() as con:
        b = get_booking(con, bid)
        if b["status"] != "booked":
            err(409, "예약 상태가 아니라 취소할 수 없습니다.")
        if p.by == "member" and parse(b["start_at"]) < now() + timedelta(hours=CANCEL_DEADLINE_HOURS):
            err(409, f"수업 {CANCEL_DEADLINE_HOURS}시간 전까지만 취소할 수 있습니다. 데스크로 문의해 주세요.")
        apply_status(con, b, "cancelled", "예약 취소")
        return {"ok": True}


def desk_action(bid: int, new: str):
    with tx() as con:
        b = get_booking(con, bid)
        if b["status"] != "booked":
            err(409, "예약 상태인 건만 처리할 수 있습니다. (정정은 '되돌리기' 후 다시 처리)")
        st = parse(b["start_at"])
        if new == "attended" and now() < st - timedelta(minutes=ATTEND_OPEN_MIN):
            err(409, f"출석은 수업 {ATTEND_OPEN_MIN}분 전부터 처리할 수 있습니다.")
        if new == "noshow" and now() < st + timedelta(minutes=NOSHOW_AFTER_MIN):
            err(409, f"노쇼는 수업 시작 {NOSHOW_AFTER_MIN}분 후부터 처리할 수 있습니다.")
        apply_status(con, b, new, "출석 차감" if new == "attended" else "노쇼 차감")
        return {"ok": True}


@app.post("/api/bookings/{bid}/attend")
def attend(bid: int):
    return desk_action(bid, "attended")


@app.post("/api/bookings/{bid}/noshow")
def noshow(bid: int):
    return desk_action(bid, "noshow")


@app.post("/api/bookings/{bid}/revert")
def revert(bid: int):
    """오처리 정정: 출석/노쇼 → 예약 상태로 되돌리고 차감분 복구."""
    with tx() as con:
        b = get_booking(con, bid)
        if b["status"] not in CHARGED:
            err(409, "출석/노쇼 처리된 건만 되돌릴 수 있습니다.")
        apply_status(con, b, "booked", "처리 취소(복구)")
        return {"ok": True}


@app.get("/api/desk")
def desk(date: Optional[str] = None):
    with ro() as con:
        if date:
            out = slot_rows(con, "WHERE substr(s.start_at,1,10)=?", (date,))
        else:  # 기본: 최근 6시간 이내에 시작한 수업부터 오늘 끝까지 (자정 직후에도 방금 수업이 보이도록)
            lo = (now() - timedelta(hours=6)).strftime(FMT)
            hi = (now().replace(hour=0, minute=0) + timedelta(days=1)).strftime(FMT)
            out = slot_rows(con, "WHERE s.start_at>=? AND s.start_at<?", (lo, hi))
        for s in out:
            s["bookings"] = [dict(r) for r in con.execute(
                "SELECT b.id,b.status,m.id member_id,m.name,m.phone,ms.name membership,ms.remaining "
                "FROM bookings b JOIN members m ON m.id=b.member_id JOIN memberships ms ON ms.id=b.membership_id "
                "WHERE b.slot_id=? AND b.status!='cancelled' ORDER BY b.id", (s["id"],))]
            st = parse(s["start_at"])
            s["attend_open"] = now() >= st - timedelta(minutes=ATTEND_OPEN_MIN)
            s["noshow_open"] = now() >= st + timedelta(minutes=NOSHOW_AFTER_MIN)
        return out


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


# ---------------------------------------------------------------- 가상 데이터
def seed(con):
    t0 = now()

    def at(days=0, hours=0, minutes=0):
        return (t0 + timedelta(days=days, hours=hours, minutes=minutes)).strftime(FMT)

    def day(offset, hh, mm=0):
        return (t0 + timedelta(days=offset)).replace(hour=hh, minute=mm).strftime(FMT)

    for n in ("김민준 트레이너", "이서연 트레이너", "박지훈 트레이너"):
        con.execute("INSERT INTO trainers(name) VALUES(?)", (n,))
    people = [("최유리", "010-0000-4161"), ("정하늘", "010-0000-1788"), ("오세훈", "010-0000-6249"),
              ("한지민", "010-0000-4088"), ("윤도현", "010-0000-7349"), ("강나래", "010-0000-5939")]
    for n, p in people:
        con.execute("INSERT INTO members(name,phone) VALUES(?,?)", (n, p))

    def sell(mid, name, total, remaining, days_left, ago=40):
        cur = con.execute("INSERT INTO memberships(member_id,name,total,remaining,expires_on,created_at) "
                          "VALUES(?,?,?,?,?,?)",
                          (mid, name, total, remaining, (t0 + timedelta(days=days_left)).strftime("%Y-%m-%d"),
                           at(-ago)))
        con.execute("INSERT INTO ledger(membership_id,booking_id,delta,reason,created_at) VALUES(?,?,?,?,?)",
                    (cur.lastrowid, None, total, "회원권 등록", at(-ago)))
        return cur.lastrowid

    ms = {1: sell(1, "PT 10회권", 10, 10, 80), 2: sell(2, "PT 20회권", 20, 20, 150),
          3: sell(3, "PT 10회권", 10, 10, 60), 4: sell(4, "PT 10회권", 10, 10, 5),  # 한지민: 곧 만료
          5: sell(5, "PT 5회권", 5, 5, 60), 6: sell(6, "PT 10회권", 10, 10, 60)}

    def slot(tr, start, cap=1, mins=50):
        st = datetime.strptime(start, FMT)
        return con.execute("INSERT INTO slots(trainer_id,start_at,end_at,capacity) VALUES(?,?,?,?)",
                           (tr, start, (st + timedelta(minutes=mins)).strftime(FMT), cap)).lastrowid

    def bk(slot_id, mid, status):
        cur = con.execute("INSERT INTO bookings(slot_id,member_id,membership_id,status,created_at,updated_at) "
                          "VALUES(?,?,?,?,?,?)", (slot_id, mid, ms[mid], status, at(-9), at(-9)))
        if status in CHARGED:
            con.execute("UPDATE memberships SET remaining=remaining-1 WHERE id=?", (ms[mid],))
            con.execute("INSERT INTO ledger(membership_id,booking_id,delta,reason,created_at) VALUES(?,?,?,?,?)",
                        (ms[mid], cur.lastrowid, -1, "출석 차감" if status == "attended" else "노쇼 차감", at(-9)))

    # 과거 이력 — 회원별 출석, 강나래(6)는 최근 노쇼 3회 → 예약 제한 상태
    for i, d in enumerate((-20, -18, -14, -11, -7), 1):
        bk(slot(1 + i % 3, day(d, 10)), 1, "attended")
    for d in (-16, -9):
        bk(slot(2, day(d, 19)), 2, "attended")
    bk(slot(3, day(-12, 20)), 3, "noshow")           # 오세훈: 노쇼 1회
    for d in (-21, -13, -5):
        bk(slot(1, day(d, 18)), 6, "noshow")         # 강나래: 노쇼 3회
    bk(slot(2, day(-10, 11)), 5, "attended")
    bk(slot(2, day(-8, 11)), 5, "attended")
    bk(slot(2, day(-6, 11)), 5, "attended")
    bk(slot(2, day(-4, 11)), 5, "attended")           # 윤도현 5회권 → 잔여 1

    # 데스크 시연용: 방금 시작한 수업(노쇼/출석 처리 가능), 곧 시작할 수업
    s_now = slot(1, at(minutes=-20))
    bk(s_now, 1, "booked")
    s_now2 = slot(2, at(minutes=-15), cap=2)
    bk(s_now2, 2, "booked")
    bk(s_now2, 3, "booked")
    s_soon = slot(3, at(hours=2))
    bk(s_soon, 4, "booked")

    # 앞으로 일주일 수업 (정원 1~3, 일부는 이미 만석)
    for d in range(1, 8):
        for tr, hh, cap in ((1, 10, 1), (2, 14, 2), (3, 19, 3), (1, 20, 1)):
            sid = slot(tr, day(d, hh), cap)
            if (d, hh) == (2, 10):
                bk(sid, 2, "booked")                 # 만석(정원 1) 시연
            if (d, hh) == (3, 19):
                for mid in (1, 2, 3):
                    bk(sid, mid, "booked")           # 정원 3 만석 시연
            if (d, hh) == (1, 14):
                bk(sid, 1, "booked")


def init_db():
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0:
        con.execute("BEGIN")
        seed(con)
        con.execute("COMMIT")
    con.close()


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
