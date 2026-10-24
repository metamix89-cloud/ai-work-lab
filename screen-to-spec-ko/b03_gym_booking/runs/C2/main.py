import csv
import os
import sqlite3
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "gym.db")
FMT = "%Y-%m-%d %H:%M"
LOCK = threading.RLock()

app = FastAPI()


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE gy_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE gy_passes(member_id TEXT PRIMARY KEY, kind TEXT, total INTEGER, used INTEGER, expires_on TEXT);
    CREATE TABLE gy_slots(slot_id TEXT PRIMARY KEY, starts_at TEXT, trainer TEXT, capacity INTEGER);
    CREATE TABLE gy_bookings(booking_id TEXT PRIMARY KEY, slot_id TEXT, member_id TEXT, status TEXT);
    CREATE TABLE gy_log(booking_id TEXT, at TEXT, by TEXT, action TEXT);
    """)
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO gy_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("passes.csv"):
        con.execute("INSERT INTO gy_passes VALUES(?,?,?,?,?)",
                    (r["member_id"], r["kind"], int(r["total"]), int(r["used"]), r["expires_on"]))
    for r in read_csv("slots.csv"):
        con.execute("INSERT INTO gy_slots VALUES(?,?,?,?)",
                    (r["slot_id"], r["starts_at"], r["trainer"], int(r["capacity"])))
    for r in read_csv("bookings.csv"):
        con.execute("INSERT INTO gy_bookings VALUES(?,?,?,?)",
                    (r["booking_id"], r["slot_id"], r["member_id"], r["status"]))
    con.commit()
    return con


con = init_db()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


def now():
    return datetime.now().replace(second=0, microsecond=0)


def parse(s):
    return datetime.strptime(s, FMT)


async def body_of(request: Request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def need_user(body):
    u = body.get("user")
    if not isinstance(u, str) or not u:
        raise Reject(400, "사용자를 확인하세요")
    return u


def get_user(uid):
    r = con.execute("SELECT * FROM gy_users WHERE user_id=?", (uid,)).fetchone()
    if not r:
        raise Reject(404, "없는 사용자입니다")
    return r


def pass_info(member_id):
    p = con.execute("SELECT * FROM gy_passes WHERE member_id=?", (member_id,)).fetchone()
    if not p:
        return None
    held = con.execute("SELECT COUNT(*) FROM gy_bookings WHERE member_id=? AND status='booked'",
                       (member_id,)).fetchone()[0]
    left = p["total"] - p["used"]
    return {"member_id": member_id, "kind": p["kind"], "total": p["total"], "used": p["used"],
            "left": left, "held": held, "available": left - held, "expires_on": p["expires_on"],
            "expired": p["expires_on"] < now().date().isoformat()}


def booking_out(bid):
    r = con.execute("""SELECT b.booking_id, b.slot_id, s.starts_at, s.trainer, b.member_id,
        COALESCE(u.name, b.member_id) AS member_name, b.status
        FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
        LEFT JOIN gy_users u ON u.user_id=b.member_id WHERE b.booking_id=?""", (bid,)).fetchone()
    return dict(r)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with LOCK:
        return [dict(r) for r in con.execute("SELECT user_id, name, role FROM gy_users")]


@app.get("/api/slots")
def slots():
    with LOCK:
        rows = con.execute("""SELECT s.slot_id, s.starts_at, s.trainer, s.capacity,
            (SELECT COUNT(*) FROM gy_bookings b WHERE b.slot_id=s.slot_id AND b.status='booked') AS booked
            FROM gy_slots s ORDER BY s.starts_at, s.slot_id""").fetchall()
        return [dict(r, left=r["capacity"] - r["booked"]) for r in rows]


@app.get("/api/passes/{member_id}")
def passes(member_id: str):
    with LOCK:
        info = pass_info(member_id)
    if not info:
        raise Reject(404, "회원권을 찾을 수 없습니다")
    return info


@app.get("/api/bookings")
def bookings(viewer: str = ""):
    with LOCK:
        u = con.execute("SELECT * FROM gy_users WHERE user_id=?", (viewer,)).fetchone()
        if not u:
            raise Reject(404, "없는 사용자입니다")
        q = """SELECT b.booking_id FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id"""
        args = ()
        if u["role"] != "desk":
            q += " WHERE b.member_id=?"
            args = (viewer,)
        q += " ORDER BY s.starts_at, b.booking_id"
        return [booking_out(r[0]) for r in con.execute(q, args).fetchall()]


@app.post("/api/bookings", status_code=201)
async def create_booking(request: Request):
    body = await body_of(request)
    uid = need_user(body)
    member_id, slot_id = body.get("member_id"), body.get("slot_id")
    if not isinstance(member_id, str) or not member_id or not isinstance(slot_id, str) or not slot_id:
        raise Reject(400, "회원과 수업을 확인하세요")
    with LOCK:
        user = get_user(uid)
        member = con.execute("SELECT * FROM gy_users WHERE user_id=? AND role='member'", (member_id,)).fetchone()
        if not member:
            raise Reject(404, "없는 회원입니다")
        slot = con.execute("SELECT * FROM gy_slots WHERE slot_id=?", (slot_id,)).fetchone()
        if not slot:
            raise Reject(404, "없는 수업입니다")
        if user["role"] != "desk" and member_id != uid:
            raise Reject(403, "본인 예약만 할 수 있습니다")
        n = now()
        start = parse(slot["starts_at"])
        if start < n:
            raise Reject(409, "지난 수업입니다")
        info = pass_info(member_id)
        if info is None or start.date().isoformat() > info["expires_on"]:
            raise Reject(409, "회원권 유효기간이 지났습니다")
        since = (n.date() - timedelta(days=29)).isoformat()
        ns = con.execute("""SELECT COUNT(*) FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
            WHERE b.member_id=? AND b.status='noshow' AND substr(s.starts_at,1,10)>=?""",
                         (member_id, since)).fetchone()[0]
        if ns >= 3:
            raise Reject(409, "노쇼 3회 — 데스크에 문의하세요")
        if info["available"] < 1:
            raise Reject(409, "예약 가능 횟수가 없습니다")
        booked = con.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'",
                             (slot_id,)).fetchone()[0]
        if booked >= slot["capacity"]:
            raise Reject(409, "정원이 찼습니다")
        if con.execute("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'",
                       (slot_id, member_id)).fetchone():
            raise Reject(409, "이미 예약한 수업입니다")
        nums = [int(r[0][2:]) for r in con.execute("SELECT booking_id FROM gy_bookings")
                if r[0].startswith("B-") and r[0][2:].isdigit()]
        bid = "B-%d" % (max(nums, default=1000) + 1)
        con.execute("INSERT INTO gy_bookings VALUES(?,?,?,'booked')", (bid, slot_id, member_id))
        con.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (bid, n.strftime(FMT), uid, "book"))
        con.commit()
        return booking_out(bid)


@app.post("/api/bookings/{booking_id}/{action}")
async def act_booking(booking_id: str, action: str, request: Request):
    body = await body_of(request)
    uid = need_user(body)
    if action not in ("cancel", "attend", "noshow"):
        raise Reject(404, "없는 동작입니다")
    with LOCK:
        user = get_user(uid)
        b = con.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (booking_id,)).fetchone()
        if not b:
            raise Reject(404, "없는 예약입니다")
        slot = con.execute("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],)).fetchone()
        desk = user["role"] == "desk"
        if action == "cancel":
            if not desk and b["member_id"] != uid:
                raise Reject(403, "본인 예약만 할 수 있습니다")
        elif not desk:
            raise Reject(403, "데스크만 할 수 있습니다")
        if b["status"] != "booked":
            raise Reject(409, "지금 상태에서는 할 수 없습니다")
        n = now()
        start = parse(slot["starts_at"])
        if action == "cancel":
            if n > start - timedelta(hours=2):
                raise Reject(409, "취소 마감이 지났습니다 (시작 2시간 전까지)")
            new = "cancelled"
        else:
            if start > n:
                raise Reject(409, "아직 시작하지 않은 수업입니다")
            new = "attended" if action == "attend" else "noshow"
            con.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (b["member_id"],))
        con.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?", (new, booking_id))
        con.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (booking_id, n.strftime(FMT), uid, action))
        con.commit()
        return booking_out(booking_id)
