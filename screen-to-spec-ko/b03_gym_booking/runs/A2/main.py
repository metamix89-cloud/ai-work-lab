"""으랏차차헬스 - PT 수업 예약 · 회원권 차감 (FastAPI + SQLite)

규칙
- 예약 시점에는 횟수를 차감하지 않고 '예약 보류'로 잡는다. 사용 가능 횟수 = 잔여 - 예약중 건수
- 출석 / 노쇼 처리 시 각각 1회 차감 (데스크만 처리, 한 예약은 한 번만 처리됨)
- 수업 시작 CANCEL_DEADLINE_HOURS 시간 전까지만 취소 가능 (이후엔 취소 불가 → 노쇼로 처리)
- 최근 NOSHOW_WINDOW_DAYS 일 내 노쇼가 NOSHOW_LIMIT 회 이상이면 신규 예약 차단
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "gym.db"

CANCEL_DEADLINE_HOURS = 2
CHECKIN_OPEN_MINUTES = 30
NOSHOW_LIMIT = 3
NOSHOW_WINDOW_DAYS = 30
FMT = "%Y-%m-%d %H:%M:%S"

app = FastAPI(title="으랏차차헬스 PT 예약")


# ---------------------------------------------------------------- DB
@contextmanager
def tx():
    """쓰기 트랜잭션: BEGIN IMMEDIATE 로 동시 요청을 직렬화(정원/차감 경쟁 방지)."""
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


SCHEMA = """
CREATE TABLE IF NOT EXISTS members(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(
  id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id),
  name TEXT NOT NULL, total INTEGER NOT NULL CHECK(total>0),
  remaining INTEGER NOT NULL CHECK(remaining>=0),
  starts_on TEXT NOT NULL, expires_on TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS classes(
  id INTEGER PRIMARY KEY, trainer TEXT NOT NULL, title TEXT NOT NULL,
  starts_at TEXT NOT NULL, minutes INTEGER NOT NULL DEFAULT 50,
  capacity INTEGER NOT NULL CHECK(capacity>0));
CREATE TABLE IF NOT EXISTS reservations(
  id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id),
  class_id INTEGER NOT NULL REFERENCES classes(id),
  membership_id INTEGER NOT NULL REFERENCES memberships(id),
  status TEXT NOT NULL CHECK(status IN('booked','attended','noshow','cancelled')),
  created_at TEXT NOT NULL, processed_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_res ON reservations(member_id, class_id)
  WHERE status<>'cancelled';
CREATE TABLE IF NOT EXISTS usage_log(
  id INTEGER PRIMARY KEY, membership_id INTEGER NOT NULL, reservation_id INTEGER NOT NULL UNIQUE,
  kind TEXT NOT NULL, delta INTEGER NOT NULL, at TEXT NOT NULL);
"""


def now():
    return datetime.now().replace(microsecond=0)


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    n = con.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    con.close()
    if n == 0:
        seed()


def seed():
    n = now()
    today = n.replace(hour=0, minute=0, second=0)
    d = lambda days: (today + timedelta(days=days)).strftime("%Y-%m-%d")
    t = lambda days, h, m=0: (today + timedelta(days=days, hours=h, minutes=m)).strftime(FMT)
    with tx() as c:
        members = [("김민수", "010-0000-1509"), ("이서연", "010-0000-6613"), ("박지훈", "010-0000-3144"),
                   ("최유진", "010-0000-6439"), ("정하늘", "010-0000-4398"), ("강도윤", "010-0000-7756"),
                   ("윤서아", "010-0000-4478"), ("임태양", "010-0000-8832")]
        c.executemany("INSERT INTO members(name,phone) VALUES(?,?)", members)
        # (member, 이름, 총, 시작, 만료)
        ms = [(1, "PT 10회권", 10, -30, 60), (2, "PT 20회권", 20, -20, 100), (3, "PT 10회권", 10, -25, 65),
              (4, "PT 5회권", 5, -10, 50), (5, "PT 10회권", 10, -40, 50), (6, "PT 10회권", 10, -120, -5),
              (7, "PT 10회권", 10, -15, 75), (7, "PT 5회권(추가)", 5, -2, 88), (8, "PT 10회권", 10, -35, 55)]
        for m, nm, tot, s, e in ms:
            c.execute("INSERT INTO memberships(member_id,name,total,remaining,starts_on,expires_on) VALUES(?,?,?,?,?,?)",
                      (m, nm, tot, tot, d(s), d(e)))
        tr = ["오지훈", "한소영", "백승호"]
        cls = []  # 과거 이력용 수업
        for i in range(1, 16):
            cls.append((tr[i % 3], "PT 1:1", t(-i, 10 + i % 5), 1))
        c.executemany("INSERT INTO classes(trainer,title,starts_at,capacity) VALUES(?,?,?,?)", cls)
        past_ids = [r[0] for r in c.execute("SELECT id FROM classes ORDER BY id")]

        def res(m, ms_id, cid, status):
            c.execute("INSERT INTO reservations(member_id,class_id,membership_id,status,created_at,processed_at) "
                      "VALUES(?,?,?,?,?,?)", (m, cid, ms_id, status, t(-20, 9), t(-1, 9) if status != "booked" else None))
        # 과거 이력: 박지훈(3) 최근 노쇼 3회 -> 차단, 정하늘(5) 노쇼 2회, 김민수(1) 출석 4회
        for k, (m, ms_id, st) in enumerate([(3, 3, "noshow"), (3, 3, "noshow"), (3, 3, "noshow"), (3, 3, "attended"),
                                            (5, 5, "noshow"), (5, 5, "noshow"), (5, 5, "attended"),
                                            (1, 1, "attended"), (1, 1, "attended"), (1, 1, "attended"), (1, 1, "attended"),
                                            (2, 2, "attended"), (2, 2, "attended"), (2, 2, "noshow"),
                                            (4, 4, "attended")]):
            res(m, ms_id, past_ids[k], st)
        # 예약 보류는 없으므로 잔여 = 총 - (출석+노쇼)
        c.execute("UPDATE memberships SET remaining = total - (SELECT COUNT(*) FROM reservations r "
                  "WHERE r.membership_id=memberships.id AND r.status IN('attended','noshow'))")
        for rid, mid in c.execute("SELECT id, membership_id FROM reservations WHERE status IN('attended','noshow')").fetchall():
            st = c.execute("SELECT status FROM reservations WHERE id=?", (rid,)).fetchone()[0]
            c.execute("INSERT INTO usage_log(membership_id,reservation_id,kind,delta,at) VALUES(?,?,?,?,?)",
                      (mid, rid, st, -1, t(-1, 9)))

        # 앞으로 7일간 수업 (오늘 이미 시작한 수업 1개 포함: 데스크 데모용)
        started = (n - timedelta(minutes=20)).strftime(FMT)
        soon = (n + timedelta(minutes=45)).strftime(FMT)
        upcoming = [("오지훈", "PT 1:1", started, 1), ("한소영", "PT 1:1", soon, 1),
                    ("백승호", "소그룹 PT (3인)", (n + timedelta(hours=1, minutes=30)).strftime(FMT), 3)]
        for day in range(1, 8):
            for h, trn, ttl, cap in [(10, "오지훈", "PT 1:1", 1), (14, "한소영", "PT 1:1", 1),
                                     (19, "백승호", "소그룹 PT (3인)", 3), (20, "한소영", "PT 1:1", 1)]:
                upcoming.append((trn, ttl, t(day, h), cap))
        c.executemany("INSERT INTO classes(trainer,title,starts_at,capacity) VALUES(?,?,?,?)", upcoming)
        first = c.execute("SELECT id FROM classes WHERE id>15 ORDER BY id").fetchall()
        live, nxt, grp = first[0][0], first[1][0], first[2][0]
        for m, ms_id, cid in [(7, 7, live), (1, 1, nxt), (2, 2, grp), (4, 4, grp), (8, 9, grp)]:
            c.execute("INSERT INTO reservations(member_id,class_id,membership_id,status,created_at) VALUES(?,?,?,?,?)",
                      (m, cid, ms_id, "booked", n.strftime(FMT)))
        # 내일 10시 오지훈 수업은 이미 마감(정원 1)
        tomorrow10 = c.execute("SELECT id FROM classes WHERE starts_at=?", (t(1, 10),)).fetchone()[0]
        c.execute("INSERT INTO reservations(member_id,class_id,membership_id,status,created_at) VALUES(?,?,?,?,?)",
                  (8, tomorrow10, 9, "booked", n.strftime(FMT)))
        # 취소 마감이 임박한(2시간 이내) 예약: 김민수 (nxt 수업, 45분 뒤) -> 취소 불가 시연


# ---------------------------------------------------------------- 공통 로직
def noshow_status(c, member_id):
    since = (now() - timedelta(days=NOSHOW_WINDOW_DAYS)).strftime(FMT)
    rows = c.execute("SELECT processed_at FROM reservations WHERE member_id=? AND status='noshow' "
                     "AND processed_at>=? ORDER BY processed_at DESC", (member_id, since)).fetchall()
    count = len(rows)
    blocked = count >= NOSHOW_LIMIT
    until = None
    if blocked:
        # 가장 최근 N건 중 가장 오래된 노쇼가 윈도우를 벗어나는 시점
        oldest_of_recent = datetime.strptime(rows[NOSHOW_LIMIT - 1]["processed_at"], FMT)
        until = (oldest_of_recent + timedelta(days=NOSHOW_WINDOW_DAYS)).strftime("%Y-%m-%d")
    return {"count": count, "limit": NOSHOW_LIMIT, "blocked": blocked, "blocked_until": until}


def membership_rows(c, member_id):
    today = now().strftime("%Y-%m-%d")
    rows = c.execute(
        "SELECT m.*, (SELECT COUNT(*) FROM reservations r WHERE r.membership_id=m.id AND r.status='booked') AS held "
        "FROM memberships m WHERE member_id=? ORDER BY expires_on", (member_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["available"] = max(d["remaining"] - d["held"], 0)
        d["expired"] = d["expires_on"] < today
        out.append(d)
    return out


def get_member(c, mid):
    m = c.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
    if not m:
        raise HTTPException(404, "회원을 찾을 수 없습니다.")
    return m


def class_end(row):
    return datetime.strptime(row["starts_at"], FMT) + timedelta(minutes=row["minutes"])


# ---------------------------------------------------------------- API
@app.get("/api/config")
def config():
    return {"cancel_deadline_hours": CANCEL_DEADLINE_HOURS, "checkin_open_minutes": CHECKIN_OPEN_MINUTES,
            "noshow_limit": NOSHOW_LIMIT, "noshow_window_days": NOSHOW_WINDOW_DAYS, "now": now().strftime(FMT)}


@app.get("/api/members")
def list_members():
    with tx() as c:
        out = []
        for m in c.execute("SELECT * FROM members ORDER BY id").fetchall():
            ns = noshow_status(c, m["id"])
            ms = [x for x in membership_rows(c, m["id"]) if not x["expired"]]
            out.append({**dict(m), "available": sum(x["available"] for x in ms), "remaining": sum(x["remaining"] for x in ms),
                        "noshow": ns})
        return out


@app.get("/api/members/{mid}")
def member_detail(mid: int):
    with tx() as c:
        m = get_member(c, mid)
        rs = c.execute(
            "SELECT r.*, c.starts_at, c.trainer, c.title, c.minutes FROM reservations r JOIN classes c ON c.id=r.class_id "
            "WHERE r.member_id=? ORDER BY c.starts_at DESC LIMIT 30", (mid,)).fetchall()
        deadline = timedelta(hours=CANCEL_DEADLINE_HOURS)
        res = []
        for r in rs:
            d = dict(r)
            start = datetime.strptime(r["starts_at"], FMT)
            d["can_cancel"] = r["status"] == "booked" and now() <= start - deadline
            res.append(d)
        return {**dict(m), "memberships": membership_rows(c, mid), "noshow": noshow_status(c, mid), "reservations": res}


class NewMembership(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    total: int = Field(gt=0, le=200)
    valid_days: int = Field(gt=0, le=1000)


@app.post("/api/members/{mid}/memberships")
def add_membership(mid: int, body: NewMembership):
    with tx() as c:
        get_member(c, mid)
        today = now()
        c.execute("INSERT INTO memberships(member_id,name,total,remaining,starts_on,expires_on) VALUES(?,?,?,?,?,?)",
                  (mid, body.name, body.total, body.total, today.strftime("%Y-%m-%d"),
                   (today + timedelta(days=body.valid_days)).strftime("%Y-%m-%d")))
    return {"ok": True}


@app.get("/api/classes")
def list_classes(member_id: int | None = None, days: int = 8):
    with tx() as c:
        start = now().replace(hour=0, minute=0, second=0).strftime(FMT)
        end = (now() + timedelta(days=days)).strftime(FMT)
        rows = c.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM reservations r WHERE r.class_id=c.id AND r.status<>'cancelled') AS booked "
            "FROM classes c WHERE starts_at>=? AND starts_at<? ORDER BY starts_at", (start, end)).fetchall()
        mine = {}
        if member_id:
            for r in c.execute("SELECT id, class_id FROM reservations WHERE member_id=? AND status<>'cancelled'", (member_id,)):
                mine[r["class_id"]] = r["id"]
        out = []
        for r in rows:
            d = dict(r)
            d["full"] = d["booked"] >= d["capacity"]
            d["my_reservation_id"] = mine.get(d["id"])
            d["past"] = datetime.strptime(d["starts_at"], FMT) <= now()
            out.append(d)
        return out


class Book(BaseModel):
    member_id: int
    class_id: int


@app.post("/api/reservations")
def book(body: Book):
    with tx() as c:
        get_member(c, body.member_id)
        cl = c.execute("SELECT * FROM classes WHERE id=?", (body.class_id,)).fetchone()
        if not cl:
            raise HTTPException(404, "수업을 찾을 수 없습니다.")
        start = datetime.strptime(cl["starts_at"], FMT)
        if start <= now():
            raise HTTPException(400, "이미 시작했거나 지난 수업입니다.")
        ns = noshow_status(c, body.member_id)
        if ns["blocked"]:
            raise HTTPException(403, f"최근 {NOSHOW_WINDOW_DAYS}일 내 노쇼 {ns['count']}회로 예약이 제한되었습니다. "
                                     f"{ns['blocked_until']} 이후 다시 예약할 수 있습니다.")
        if c.execute("SELECT 1 FROM reservations WHERE member_id=? AND class_id=? AND status<>'cancelled'",
                     (body.member_id, body.class_id)).fetchone():
            raise HTTPException(409, "이미 예약한 수업입니다.")
        booked = c.execute("SELECT COUNT(*) FROM reservations WHERE class_id=? AND status<>'cancelled'",
                           (body.class_id,)).fetchone()[0]
        if booked >= cl["capacity"]:
            raise HTTPException(409, "정원이 마감된 수업입니다.")
        # 수업일에 유효하고 예약 보류분을 뺀 잔여가 있는 회원권 중 만료가 가장 빠른 것
        day = start.strftime("%Y-%m-%d")
        ms = [m for m in membership_rows(c, body.member_id)
              if m["available"] > 0 and m["starts_on"] <= day <= m["expires_on"]]
        if not ms:
            raise HTTPException(400, "해당 수업일에 사용할 수 있는 회원권(잔여 횟수)이 없습니다.")
        cur = c.execute("INSERT INTO reservations(member_id,class_id,membership_id,status,created_at) VALUES(?,?,?,?,?)",
                        (body.member_id, body.class_id, ms[0]["id"], "booked", now().strftime(FMT)))
        return {"id": cur.lastrowid, "membership": ms[0]["name"]}


@app.post("/api/reservations/{rid}/cancel")
def cancel(rid: int, member_id: int):
    with tx() as c:
        r = c.execute("SELECT r.*, c.starts_at FROM reservations r JOIN classes c ON c.id=r.class_id WHERE r.id=?",
                      (rid,)).fetchone()
        if not r or r["member_id"] != member_id:
            raise HTTPException(404, "예약을 찾을 수 없습니다.")
        if r["status"] != "booked":
            raise HTTPException(409, "취소할 수 없는 상태의 예약입니다.")
        limit = datetime.strptime(r["starts_at"], FMT) - timedelta(hours=CANCEL_DEADLINE_HOURS)
        if now() > limit:
            raise HTTPException(400, f"수업 {CANCEL_DEADLINE_HOURS}시간 전까지만 취소할 수 있습니다. "
                                     f"(마감 {limit:%m/%d %H:%M}) 불참 시 노쇼로 처리되어 1회 차감됩니다.")
        c.execute("UPDATE reservations SET status='cancelled', processed_at=? WHERE id=? AND status='booked'",
                  (now().strftime(FMT), rid))
    return {"ok": True}


def desk_process(rid: int, outcome: str):
    with tx() as c:
        r = c.execute("SELECT r.*, c.starts_at FROM reservations r JOIN classes c ON c.id=r.class_id WHERE r.id=?",
                      (rid,)).fetchone()
        if not r:
            raise HTTPException(404, "예약을 찾을 수 없습니다.")
        if r["status"] != "booked":
            raise HTTPException(409, "이미 처리되었거나 취소된 예약입니다.")
        start = datetime.strptime(r["starts_at"], FMT)
        if outcome == "attended" and now() < start - timedelta(minutes=CHECKIN_OPEN_MINUTES):
            raise HTTPException(400, f"수업 {CHECKIN_OPEN_MINUTES}분 전부터 출석 처리할 수 있습니다.")
        if outcome == "noshow" and now() < start:
            raise HTTPException(400, "수업 시작 후에 노쇼 처리할 수 있습니다.")
        ok = c.execute("UPDATE memberships SET remaining=remaining-1 WHERE id=? AND remaining>0", (r["membership_id"],))
        if ok.rowcount != 1:
            raise HTTPException(409, "회원권 잔여 횟수가 없어 차감할 수 없습니다.")
        c.execute("UPDATE reservations SET status=?, processed_at=? WHERE id=? AND status='booked'",
                  (outcome, now().strftime(FMT), rid))
        c.execute("INSERT INTO usage_log(membership_id,reservation_id,kind,delta,at) VALUES(?,?,?,?,?)",
                  (r["membership_id"], rid, outcome, -1, now().strftime(FMT)))
        left = c.execute("SELECT remaining FROM memberships WHERE id=?", (r["membership_id"],)).fetchone()[0]
        ns = noshow_status(c, r["member_id"])
        return {"ok": True, "remaining": left, "noshow": ns}


@app.post("/api/desk/reservations/{rid}/attend")
def attend(rid: int):
    return desk_process(rid, "attended")


@app.post("/api/desk/reservations/{rid}/noshow")
def noshow(rid: int):
    return desk_process(rid, "noshow")


@app.get("/api/desk/today")
def desk_today():
    with tx() as c:
        lo = (now() - timedelta(hours=12)).strftime(FMT)
        hi = (now().replace(hour=0, minute=0, second=0) + timedelta(days=1)).strftime(FMT)
        rows = c.execute(
            "SELECT r.id, r.status, r.member_id, m.name AS member, c.trainer, c.title, c.starts_at, c.minutes, "
            "ms.name AS membership, ms.remaining FROM reservations r JOIN classes c ON c.id=r.class_id "
            "JOIN members m ON m.id=r.member_id JOIN memberships ms ON ms.id=r.membership_id "
            "WHERE c.starts_at>=? AND c.starts_at<? ORDER BY c.starts_at, r.id", (lo, hi)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            s = datetime.strptime(r["starts_at"], FMT)
            d["can_attend"] = r["status"] == "booked" and now() >= s - timedelta(minutes=CHECKIN_OPEN_MINUTES)
            d["can_noshow"] = r["status"] == "booked" and now() >= s
            out.append(d)
        return out


@app.get("/api/desk/blocked")
def desk_blocked():
    with tx() as c:
        out = []
        for m in c.execute("SELECT * FROM members").fetchall():
            ns = noshow_status(c, m["id"])
            if ns["count"] > 0:
                out.append({"id": m["id"], "name": m["name"], **ns})
        return sorted(out, key=lambda x: -x["count"])


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
