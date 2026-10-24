"""으랏차차헬스 - PT 수업 예약 · 회원권 차감"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "gym.db"

# ---- 정책 ----
CANCEL_DEADLINE_HOURS = 2      # 수업 시작 N시간 전까지만 무료 취소
NOSHOW_LIMIT = 3               # 최근 기간 내 노쇼 N회 이상이면 차단
NOSHOW_WINDOW_DAYS = 30
BLOCK_DAYS = 14                # 차단 기간
CHECKIN_OPEN_MIN = 30          # 시작 N분 전부터 출석/노쇼 처리 가능
CLASS_MINUTES = 50
DESK_PIN = "1234"

SCHEMA = """
CREATE TABLE IF NOT EXISTS members(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, blocked_until TEXT);
CREATE TABLE IF NOT EXISTS memberships(
  id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id),
  name TEXT NOT NULL, total INTEGER NOT NULL, remaining INTEGER NOT NULL CHECK(remaining>=0),
  starts_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS classes(
  id INTEGER PRIMARY KEY, trainer TEXT NOT NULL, title TEXT NOT NULL,
  start_at TEXT NOT NULL, capacity INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id),
  member_id INTEGER NOT NULL REFERENCES members(id),
  membership_id INTEGER NOT NULL REFERENCES memberships(id),
  status TEXT NOT NULL CHECK(status IN ('booked','attended','noshow','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_booking ON bookings(class_id, member_id)
  WHERE status!='cancelled';
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY, membership_id INTEGER NOT NULL, booking_id INTEGER,
  delta INTEGER NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL);
"""


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


@contextmanager
def tx():
    """쓰기 트랜잭션. BEGIN IMMEDIATE 로 정원/잔여횟수 경쟁 상태를 막는다."""
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


def rows(sql, args=()):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


app = FastAPI(title="으랏차차헬스 PT 예약")


def desk(x_desk_pin: str = Header(default="")):
    if x_desk_pin != DESK_PIN:
        raise HTTPException(401, "데스크 PIN이 올바르지 않습니다.")


# ---- 공통 로직 ----
def reserved_count(con, membership_id) -> int:
    return con.execute("SELECT COUNT(*) FROM bookings WHERE membership_id=? AND status='booked'",
                       (membership_id,)).fetchone()[0]


def noshow_count(con, member_id) -> int:
    since = iso(now() - timedelta(days=NOSHOW_WINDOW_DAYS))
    return con.execute(
        """SELECT COUNT(*) FROM bookings b JOIN classes c ON c.id=b.class_id
           WHERE b.member_id=? AND b.status='noshow' AND c.start_at>=?""", (member_id, since)).fetchone()[0]


def is_blocked(member) -> bool:
    return bool(member["blocked_until"]) and parse(member["blocked_until"]) > now()


def adjust(con, membership_id, booking_id, delta, reason):
    m = con.execute("SELECT remaining,total FROM memberships WHERE id=?", (membership_id,)).fetchone()
    new = m["remaining"] + delta
    if new < 0:
        raise HTTPException(409, "회원권 잔여 횟수가 부족해 차감할 수 없습니다.")
    if new > m["total"]:
        raise HTTPException(409, "회원권 총 횟수를 초과해 복구할 수 없습니다.")
    con.execute("UPDATE memberships SET remaining=? WHERE id=?", (new, membership_id))
    con.execute("INSERT INTO ledger(membership_id,booking_id,delta,reason,at) VALUES(?,?,?,?,?)",
                (membership_id, booking_id, delta, reason, iso(now())))


def membership_view(con, m):
    m = dict(m)
    m["reserved"] = reserved_count(con, m["id"])
    m["available"] = max(m["remaining"] - m["reserved"], 0)
    m["expired"] = parse(m["expires_at"]) < now()
    m["state"] = "만료" if m["expired"] else ("소진" if m["remaining"] == 0 else "사용중")
    return m


# ---- 조회 ----
@app.get("/api/config")
def config():
    return dict(cancel_deadline_hours=CANCEL_DEADLINE_HOURS, noshow_limit=NOSHOW_LIMIT,
                noshow_window_days=NOSHOW_WINDOW_DAYS, block_days=BLOCK_DAYS, now=iso(now()))


@app.get("/api/members")
def members():
    out = rows("SELECT * FROM members ORDER BY id")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    for m in out:
        m["blocked"] = is_blocked(m)
        m["noshows"] = noshow_count(con, m["id"])
        ms = [membership_view(con, r) for r in con.execute(
            "SELECT * FROM memberships WHERE member_id=? ORDER BY expires_at", (m["id"],))]
        m["memberships"] = ms
        m["available"] = sum(x["available"] for x in ms if not x["expired"])
    con.close()
    return out


@app.get("/api/members/{mid}")
def member_detail(mid: int):
    ms = [m for m in members() if m["id"] == mid]
    if not ms:
        raise HTTPException(404, "회원을 찾을 수 없습니다.")
    m = ms[0]
    m["bookings"] = rows(
        """SELECT b.id,b.status,b.membership_id,c.start_at,c.trainer,c.title FROM bookings b
           JOIN classes c ON c.id=b.class_id WHERE b.member_id=? ORDER BY c.start_at DESC LIMIT 30""", (mid,))
    for b in m["bookings"]:
        b["can_cancel"] = b["status"] == "booked" and parse(b["start_at"]) - now() >= timedelta(hours=CANCEL_DEADLINE_HOURS)
    return m


@app.get("/api/classes")
def classes(days: int = 7, member_id: Optional[int] = None):
    start = iso(now() - timedelta(hours=1))
    end = iso((now() + timedelta(days=days)).replace(hour=23, minute=59, second=59))
    out = rows("""SELECT c.*, (SELECT COUNT(*) FROM bookings b WHERE b.class_id=c.id AND b.status!='cancelled') AS booked
                  FROM classes c WHERE c.start_at BETWEEN ? AND ? ORDER BY c.start_at""", (start, end))
    mine = {}
    if member_id:
        for b in rows("SELECT id,class_id,status FROM bookings WHERE member_id=? AND status!='cancelled'", (member_id,)):
            mine[b["class_id"]] = b
    for c in out:
        c["full"] = c["booked"] >= c["capacity"]
        c["started"] = parse(c["start_at"]) <= now()
        c["mine"] = mine.get(c["id"])
    return out


# ---- 회원: 예약 / 취소 ----
class BookReq(BaseModel):
    member_id: int
    class_id: int


class CancelReq(BaseModel):
    member_id: int


@app.post("/api/bookings")
def book(req: BookReq):
    with tx() as con:
        mem = con.execute("SELECT * FROM members WHERE id=?", (req.member_id,)).fetchone()
        cls = con.execute("SELECT * FROM classes WHERE id=?", (req.class_id,)).fetchone()
        if not mem or not cls:
            raise HTTPException(404, "회원 또는 수업을 찾을 수 없습니다.")
        start = parse(cls["start_at"])
        if start <= now():
            raise HTTPException(409, "이미 시작했거나 지난 수업입니다.")
        if is_blocked(mem):
            raise HTTPException(403, f"노쇼 누적으로 {mem['blocked_until'][:10]}까지 예약이 제한됩니다. 데스크에 문의하세요.")
        if con.execute("SELECT 1 FROM bookings WHERE class_id=? AND member_id=? AND status!='cancelled'",
                       (cls["id"], mem["id"])).fetchone():
            raise HTTPException(409, "이미 예약한 수업입니다.")
        lo, hi = iso(start - timedelta(minutes=60)), iso(start + timedelta(minutes=60))
        if con.execute("""SELECT 1 FROM bookings b JOIN classes c ON c.id=b.class_id
                          WHERE b.member_id=? AND b.status='booked' AND c.start_at>? AND c.start_at<?""",
                       (mem["id"], lo, hi)).fetchone():
            raise HTTPException(409, "같은 시간대에 이미 다른 예약이 있습니다.")
        booked = con.execute("SELECT COUNT(*) FROM bookings WHERE class_id=? AND status!='cancelled'",
                             (cls["id"],)).fetchone()[0]
        if booked >= cls["capacity"]:
            raise HTTPException(409, "정원이 마감된 수업입니다.")
        # 수업 시작일까지 유효하고, 예약분을 뺀 잔여가 있는 회원권 중 만료가 가장 임박한 것
        chosen = None
        for m in con.execute("SELECT * FROM memberships WHERE member_id=? AND expires_at>=? AND starts_at<=? ORDER BY expires_at",
                             (mem["id"], cls["start_at"], cls["start_at"])):
            if m["remaining"] - reserved_count(con, m["id"]) > 0:
                chosen = m
                break
        if not chosen:
            raise HTTPException(409, "사용 가능한 회원권이 없습니다(만료/소진, 또는 예약분 포함 잔여 0회).")
        t = iso(now())
        cur = con.execute("INSERT INTO bookings(class_id,member_id,membership_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                          (cls["id"], mem["id"], chosen["id"], "booked", t, t))
        return {"id": cur.lastrowid, "membership": chosen["name"], "message": "예약되었습니다. 횟수는 출석 처리 시 차감됩니다."}


@app.post("/api/bookings/{bid}/cancel")
def cancel(bid: int, req: CancelReq):
    with tx() as con:
        b = con.execute("SELECT b.*, c.start_at FROM bookings b JOIN classes c ON c.id=b.class_id WHERE b.id=?", (bid,)).fetchone()
        if not b or b["member_id"] != req.member_id:
            raise HTTPException(404, "예약을 찾을 수 없습니다.")
        if b["status"] != "booked":
            raise HTTPException(409, "취소할 수 없는 상태의 예약입니다.")
        left = parse(b["start_at"]) - now()
        if left < timedelta(hours=CANCEL_DEADLINE_HOURS):
            raise HTTPException(409, f"수업 {CANCEL_DEADLINE_HOURS}시간 전까지만 취소할 수 있습니다. 불가피하면 데스크에 문의하세요(미취소 시 노쇼 처리 시 1회 차감).")
        con.execute("UPDATE bookings SET status='cancelled', updated_at=? WHERE id=?", (iso(now()), bid))
        return {"message": "취소되었습니다. 회원권 횟수는 차감되지 않습니다."}


# ---- 데스크 ----
@app.get("/api/desk/classes", dependencies=[Depends(desk)])
def desk_classes(date: Optional[str] = None):
    if date:
        cl = rows("SELECT * FROM classes WHERE substr(start_at,1,10)=? ORDER BY start_at", (date,))
    else:  # 기본: 최근 12시간 + 오늘 남은 수업 (자정 직후에도 어제 밤 수업 처리 가능)
        cl = rows("SELECT * FROM classes WHERE start_at>=? AND substr(start_at,1,10)<=? ORDER BY start_at",
                  (iso(now() - timedelta(hours=12)), now().date().isoformat()))
    for c in cl:
        c["roster"] = rows(
            """SELECT b.id,b.status,b.membership_id,m.id AS member_id,m.name,ms.name AS membership,ms.remaining
               FROM bookings b JOIN members m ON m.id=b.member_id JOIN memberships ms ON ms.id=b.membership_id
               WHERE b.class_id=? AND b.status!='cancelled' ORDER BY b.id""", (c["id"],))
        c["checkin_open"] = parse(c["start_at"]) - now() <= timedelta(minutes=CHECKIN_OPEN_MIN)
    return cl


def load_booking(con, bid):
    b = con.execute("SELECT b.*, c.start_at FROM bookings b JOIN classes c ON c.id=b.class_id WHERE b.id=?", (bid,)).fetchone()
    if not b:
        raise HTTPException(404, "예약을 찾을 수 없습니다.")
    return b


@app.post("/api/desk/bookings/{bid}/attend", dependencies=[Depends(desk)])
def attend(bid: int):
    with tx() as con:
        b = load_booking(con, bid)
        if b["status"] != "booked":
            raise HTTPException(409, f"이미 '{b['status']}' 처리된 예약입니다.")
        if parse(b["start_at"]) - now() > timedelta(minutes=CHECKIN_OPEN_MIN):
            raise HTTPException(409, f"수업 시작 {CHECKIN_OPEN_MIN}분 전부터 처리할 수 있습니다.")
        adjust(con, b["membership_id"], bid, -1, "출석 차감")
        con.execute("UPDATE bookings SET status='attended', updated_at=? WHERE id=?", (iso(now()), bid))
        return {"message": "출석 처리: 회원권 1회 차감"}


@app.post("/api/desk/bookings/{bid}/noshow", dependencies=[Depends(desk)])
def noshow(bid: int):
    with tx() as con:
        b = load_booking(con, bid)
        if b["status"] != "booked":
            raise HTTPException(409, f"이미 '{b['status']}' 처리된 예약입니다.")
        if parse(b["start_at"]) > now():
            raise HTTPException(409, "수업이 시작된 후에 노쇼 처리할 수 있습니다.")
        adjust(con, b["membership_id"], bid, -1, "노쇼 차감")
        con.execute("UPDATE bookings SET status='noshow', updated_at=? WHERE id=?", (iso(now()), bid))
        cnt, msg = noshow_count(con, b["member_id"]), "노쇼 처리: 회원권 1회 차감"
        if cnt >= NOSHOW_LIMIT:
            until = iso(now() + timedelta(days=BLOCK_DAYS))
            con.execute("UPDATE members SET blocked_until=? WHERE id=?", (until, b["member_id"]))
            msg += f" · 최근 {NOSHOW_WINDOW_DAYS}일 노쇼 {cnt}회 → {until[:10]}까지 예약 제한"
        return {"message": msg}


@app.post("/api/desk/bookings/{bid}/revert", dependencies=[Depends(desk)])
def revert(bid: int):
    """오처리 정정: 출석/노쇼를 예약 상태로 되돌리고 차감한 횟수를 복구."""
    with tx() as con:
        b = load_booking(con, bid)
        if b["status"] not in ("attended", "noshow"):
            raise HTTPException(409, "되돌릴 수 있는 상태가 아닙니다.")
        adjust(con, b["membership_id"], bid, +1, f"{b['status']} 정정 복구")
        con.execute("UPDATE bookings SET status='booked', updated_at=? WHERE id=?", (iso(now()), bid))
        if b["status"] == "noshow" and noshow_count(con, b["member_id"]) < NOSHOW_LIMIT:
            con.execute("UPDATE members SET blocked_until=NULL WHERE id=?", (b["member_id"],))
        return {"message": "정정 완료: 횟수 복구, 예약 상태로 되돌림"}


@app.post("/api/desk/members/{mid}/unblock", dependencies=[Depends(desk)])
def unblock(mid: int):
    with tx() as con:
        con.execute("UPDATE members SET blocked_until=NULL WHERE id=?", (mid,))
    return {"message": "예약 제한을 해제했습니다."}


class MembershipReq(BaseModel):
    name: str = "PT 10회권"
    total: int = 10
    days: int = 90


@app.post("/api/desk/members/{mid}/memberships", dependencies=[Depends(desk)])
def add_membership(mid: int, req: MembershipReq):
    if not (1 <= req.total <= 100 and 1 <= req.days <= 730):
        raise HTTPException(422, "횟수(1~100)/유효일수(1~730)를 확인하세요.")
    with tx() as con:
        if not con.execute("SELECT 1 FROM members WHERE id=?", (mid,)).fetchone():
            raise HTTPException(404, "회원을 찾을 수 없습니다.")
        s = now()
        cur = con.execute("INSERT INTO memberships(member_id,name,total,remaining,starts_at,expires_at) VALUES(?,?,?,?,?,?)",
                          (mid, req.name, req.total, req.total, iso(s), iso(s + timedelta(days=req.days))))
        con.execute("INSERT INTO ledger(membership_id,booking_id,delta,reason,at) VALUES(?,?,?,?,?)",
                    (cur.lastrowid, None, req.total, "회원권 등록", iso(s)))
    return {"message": f"{req.name} 등록 완료"}


@app.get("/api/desk/ledger", dependencies=[Depends(desk)])
def ledger(member_id: Optional[int] = None, limit: int = 50):
    sql = """SELECT l.*, m.name AS member, ms.name AS membership FROM ledger l
             JOIN memberships ms ON ms.id=l.membership_id JOIN members m ON m.id=ms.member_id"""
    args = []
    if member_id:
        sql += " WHERE m.id=?"
        args.append(member_id)
    return rows(sql + " ORDER BY l.id DESC LIMIT ?", (*args, limit))


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.on_event("startup")
def startup():
    from seed import ensure_db
    ensure_db()
