import csv
import os
import sqlite3
import threading
from datetime import datetime, timedelta, date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
SEED = BASE / "seed"
DB_PATH = BASE / "gym.db"
FMT = "%Y-%m-%d %H:%M"
LOCK = threading.RLock()

app = FastAPI()
_conn = None


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def init_db():
    global _conn
    if _conn:
        _conn.close()
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(str(DB_PATH) + suffix)
        except OSError:
            pass
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE gy_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE gy_passes(member_id TEXT PRIMARY KEY, kind TEXT, total INTEGER, used INTEGER, expires_on TEXT);
        CREATE TABLE gy_slots(slot_id TEXT PRIMARY KEY, starts_at TEXT, trainer TEXT, capacity INTEGER);
        CREATE TABLE gy_bookings(booking_id TEXT PRIMARY KEY, slot_id TEXT, member_id TEXT, status TEXT);
        CREATE TABLE gy_log(booking_id TEXT, at TEXT, by TEXT, action TEXT);
        """
    )
    for r in read_csv("users.csv"):
        c.execute("INSERT INTO gy_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("passes.csv"):
        c.execute("INSERT INTO gy_passes VALUES(?,?,?,?,?)",
                  (r["member_id"], r["kind"], int(r["total"]), int(r["used"]), r["expires_on"]))
    for r in read_csv("slots.csv"):
        c.execute("INSERT INTO gy_slots VALUES(?,?,?,?)",
                  (r["slot_id"], r["starts_at"], r["trainer"], int(r["capacity"])))
    for r in read_csv("bookings.csv"):
        c.execute("INSERT INTO gy_bookings VALUES(?,?,?,?)",
                  (r["booking_id"], r["slot_id"], r["member_id"], r["status"]))
    c.commit()
    _conn = c


@app.on_event("startup")
def startup():
    init_db()


def q(sql, args=()):
    return _conn.execute(sql, args).fetchall()


def q1(sql, args=()):
    return _conn.execute(sql, args).fetchone()


def parse_dt(s):
    return datetime.strptime(s, FMT)


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = None
    return data if isinstance(data, dict) else {}


def need_user(body):
    u = body.get("user")
    if not isinstance(u, str) or not u:
        raise Reject(400, "사용자를 확인하세요")
    return u


def booking_view(b):
    s = q1("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],))
    m = q1("SELECT name FROM gy_users WHERE user_id=?", (b["member_id"],))
    return {
        "booking_id": b["booking_id"], "slot_id": b["slot_id"],
        "starts_at": s["starts_at"] if s else None, "trainer": s["trainer"] if s else None,
        "member_id": b["member_id"], "member_name": m["name"] if m else None,
        "status": b["status"],
    }


def booked_count(slot_id):
    return q1("SELECT COUNT(*) n FROM gy_bookings WHERE slot_id=? AND status='booked'", (slot_id,))["n"]


def pass_view(member_id):
    p = q1("SELECT * FROM gy_passes WHERE member_id=?", (member_id,))
    if not p:
        return None
    held = q1("SELECT COUNT(*) n FROM gy_bookings WHERE member_id=? AND status='booked'", (member_id,))["n"]
    left = p["total"] - p["used"]
    return {
        "member_id": member_id, "kind": p["kind"], "total": p["total"], "used": p["used"],
        "left": left, "held": held, "available": left - held, "expires_on": p["expires_on"],
        "expired": p["expires_on"] < date.today().isoformat(),
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/users")
def users():
    with LOCK:
        return [dict(r) for r in q("SELECT user_id,name,role FROM gy_users ORDER BY rowid")]


@app.get("/api/slots")
def slots():
    with LOCK:
        out = []
        for s in q("SELECT * FROM gy_slots ORDER BY starts_at, slot_id"):
            n = booked_count(s["slot_id"])
            out.append({"slot_id": s["slot_id"], "starts_at": s["starts_at"], "trainer": s["trainer"],
                        "capacity": s["capacity"], "booked": n, "left": s["capacity"] - n})
        return out


@app.get("/api/passes/{member_id}")
def passes(member_id: str):
    with LOCK:
        v = pass_view(member_id)
        if not v:
            raise Reject(404, "회원권을 찾을 수 없습니다")
        return v


@app.get("/api/bookings")
def bookings(viewer: str = ""):
    with LOCK:
        u = q1("SELECT * FROM gy_users WHERE user_id=?", (viewer,))
        if not u:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        rows = q("""SELECT b.* FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
                    ORDER BY s.starts_at, b.booking_id""")
        if u["role"] != "desk":
            rows = [r for r in rows if r["member_id"] == viewer]
        return [booking_view(r) for r in rows]


@app.post("/api/bookings", status_code=201)
async def create_booking(request: Request):
    body = await body_of(request)
    user = need_user(body)
    member_id, slot_id = body.get("member_id"), body.get("slot_id")
    if not isinstance(member_id, str) or not member_id:
        raise Reject(400, "회원을 확인하세요")
    if not isinstance(slot_id, str) or not slot_id:
        raise Reject(400, "수업을 확인하세요")
    with LOCK:
        u = q1("SELECT * FROM gy_users WHERE user_id=?", (user,))
        if not u:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        m = q1("SELECT * FROM gy_users WHERE user_id=? AND role='member'", (member_id,))
        if not m or not q1("SELECT 1 FROM gy_passes WHERE member_id=?", (member_id,)):
            raise Reject(404, "회원을 찾을 수 없습니다")
        s = q1("SELECT * FROM gy_slots WHERE slot_id=?", (slot_id,))
        if not s:
            raise Reject(404, "수업을 찾을 수 없습니다")
        if u["role"] != "desk" and member_id != user:
            raise Reject(403, "본인 예약만 할 수 있습니다")
        start = parse_dt(s["starts_at"])
        now = datetime.now()
        if start < now:
            raise Reject(409, "지난 수업입니다")
        pv = pass_view(member_id)
        if start.date().isoformat() > pv["expires_on"]:
            raise Reject(409, "회원권 유효기간이 지났습니다")
        since = (date.today() - timedelta(days=29)).isoformat()
        ns = sum(1 for r in q("""SELECT s.starts_at FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
                                 WHERE b.member_id=? AND b.status='noshow'""", (member_id,))
                 if r["starts_at"][:10] >= since)
        if ns >= 3:
            raise Reject(409, "노쇼 3회 — 데스크에 문의하세요")
        if pv["available"] < 1:
            raise Reject(409, "예약 가능 횟수가 없습니다")
        if booked_count(slot_id) >= s["capacity"]:
            raise Reject(409, "정원이 찼습니다")
        if q1("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'", (slot_id, member_id)):
            raise Reject(409, "이미 예약한 수업입니다")
        ids = [int(r["booking_id"][2:]) for r in q("SELECT booking_id FROM gy_bookings")
               if r["booking_id"].startswith("B-") and r["booking_id"][2:].isdigit()]
        bid = "B-%d" % (max(ids, default=1000) + 1)
        while q1("SELECT 1 FROM gy_bookings WHERE booking_id=?", (bid,)):
            bid = "B-%d" % (int(bid[2:]) + 1)
        _conn.execute("INSERT INTO gy_bookings VALUES(?,?,?,'booked')", (bid, slot_id, member_id))
        _conn.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (bid, now.strftime(FMT), user, "book"))
        _conn.commit()
        return booking_view(q1("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)))


@app.post("/api/bookings/{booking_id}/{action}")
async def act(booking_id: str, action: str, request: Request):
    body = await body_of(request)
    user = need_user(body)
    with LOCK:
        u = q1("SELECT * FROM gy_users WHERE user_id=?", (user,))
        if not u:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        b = q1("SELECT * FROM gy_bookings WHERE booking_id=?", (booking_id,))
        if not b or action not in ("cancel", "attend", "noshow"):
            raise Reject(404, "예약을 찾을 수 없습니다")
        desk = u["role"] == "desk"
        if action == "cancel":
            if not desk and b["member_id"] != user:
                raise Reject(403, "본인 예약만 할 수 있습니다")
        elif not desk:
            raise Reject(403, "데스크만 할 수 있습니다")
        if b["status"] != "booked":
            raise Reject(409, "지금 상태에서는 할 수 없습니다")
        s = q1("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],))
        start, now = parse_dt(s["starts_at"]), datetime.now()
        if action == "cancel":
            if now > start - timedelta(hours=2):
                raise Reject(409, "취소 마감이 지났습니다 (시작 2시간 전까지)")
            new = "cancelled"
        else:
            if now < start:
                raise Reject(409, "아직 시작하지 않은 수업입니다")
            new = "attended" if action == "attend" else "noshow"
            _conn.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (b["member_id"],))
        _conn.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?", (new, booking_id))
        _conn.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (booking_id, now.strftime(FMT), user, action))
        _conn.commit()
        return booking_view(q1("SELECT * FROM gy_bookings WHERE booking_id=?", (booking_id,)))
