import csv
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "gym.db")
FMT = "%Y-%m-%d %H:%M"
LOCK = threading.RLock()

app = FastAPI()


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
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


DB = init_db()


def q(sql, args=()):
    return DB.execute(sql, args).fetchall()


def q1(sql, args=()):
    return DB.execute(sql, args).fetchone()


def err(code, detail):
    return HTTPException(status_code=code, detail=detail)


async def body_of(request: Request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def need_user(body):
    u = body.get("user")
    if not isinstance(u, str) or not u:
        raise err(400, "사용자를 확인하세요")
    return u


def get_user(uid):
    u = q1("SELECT * FROM gy_users WHERE user_id=?", (uid,))
    if not u:
        raise err(404, "사용자를 찾을 수 없습니다")
    return u


def pass_info(member_id):
    p = q1("SELECT * FROM gy_passes WHERE member_id=?", (member_id,))
    if not p:
        return None
    held = q1("SELECT COUNT(*) c FROM gy_bookings WHERE member_id=? AND status='booked'", (member_id,))["c"]
    left = p["total"] - p["used"]
    return {"member_id": member_id, "kind": p["kind"], "total": p["total"], "used": p["used"],
            "left": left, "held": held, "available": left - held, "expires_on": p["expires_on"],
            "expired": p["expires_on"] < date.today().isoformat()}


def booking_row(b):
    s = q1("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],))
    m = q1("SELECT name FROM gy_users WHERE user_id=?", (b["member_id"],))
    return {"booking_id": b["booking_id"], "slot_id": b["slot_id"],
            "starts_at": s["starts_at"] if s else None, "trainer": s["trainer"] if s else None,
            "member_id": b["member_id"], "member_name": m["name"] if m else b["member_id"],
            "status": b["status"]}


def log(bid, by, action):
    DB.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (bid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), by, action))


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with LOCK:
        return [dict(r) for r in q("SELECT user_id,name,role FROM gy_users")]


@app.get("/api/slots")
def slots():
    with LOCK:
        out = []
        for s in q("SELECT * FROM gy_slots ORDER BY starts_at, slot_id"):
            n = q1("SELECT COUNT(*) c FROM gy_bookings WHERE slot_id=? AND status='booked'", (s["slot_id"],))["c"]
            out.append({"slot_id": s["slot_id"], "starts_at": s["starts_at"], "trainer": s["trainer"],
                        "capacity": s["capacity"], "booked": n, "left": s["capacity"] - n})
        return out


@app.get("/api/passes/{member_id}")
def passes(member_id: str):
    with LOCK:
        p = pass_info(member_id)
        if not p:
            raise err(404, "회원권을 찾을 수 없습니다")
        return p


@app.get("/api/bookings")
def bookings(viewer: str = ""):
    if not viewer:
        raise err(400, "사용자를 확인하세요")
    with LOCK:
        u = get_user(viewer)
        rows = q("SELECT b.* FROM gy_bookings b LEFT JOIN gy_slots s ON s.slot_id=b.slot_id "
                 "ORDER BY s.starts_at, b.booking_id")
        if u["role"] != "desk":
            rows = [r for r in rows if r["member_id"] == viewer]
        return [booking_row(r) for r in rows]


@app.post("/api/bookings", status_code=201)
async def create_booking(request: Request):
    body = await body_of(request)
    uid = need_user(body)
    member_id, slot_id = body.get("member_id"), body.get("slot_id")
    if not isinstance(member_id, str) or not member_id or not isinstance(slot_id, str) or not slot_id:
        raise err(400, "회원과 수업을 확인하세요")
    with LOCK:
        user = get_user(uid)
        member = q1("SELECT * FROM gy_users WHERE user_id=? AND role='member'", (member_id,))
        if not member:
            raise err(404, "회원을 찾을 수 없습니다")
        slot = q1("SELECT * FROM gy_slots WHERE slot_id=?", (slot_id,))
        if not slot:
            raise err(404, "수업을 찾을 수 없습니다")
        if user["role"] != "desk" and uid != member_id:
            raise err(403, "본인 예약만 할 수 있습니다")
        start = datetime.strptime(slot["starts_at"], FMT)
        if start < datetime.now():
            raise err(409, "지난 수업입니다")
        p = pass_info(member_id)
        if not p or start.date().isoformat() > p["expires_on"]:
            raise err(409, "회원권 유효기간이 지났습니다")
        since = (date.today() - timedelta(days=29)).isoformat()
        ns = q1("SELECT COUNT(*) c FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id "
                "WHERE b.member_id=? AND b.status='noshow' AND substr(s.starts_at,1,10)>=?", (member_id, since))["c"]
        if ns >= 3:
            raise err(409, "노쇼 3회 — 데스크에 문의하세요")
        if p["available"] < 1:
            raise err(409, "예약 가능 횟수가 없습니다")
        n = q1("SELECT COUNT(*) c FROM gy_bookings WHERE slot_id=? AND status='booked'", (slot_id,))["c"]
        if n >= slot["capacity"]:
            raise err(409, "정원이 찼습니다")
        if q1("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'", (slot_id, member_id)):
            raise err(409, "이미 예약한 수업입니다")
        nums = [int(r["booking_id"][2:]) for r in q("SELECT booking_id FROM gy_bookings") if r["booking_id"][2:].isdigit()]
        bid = "B-%d" % (max(nums + [1000]) + 1)
        while q1("SELECT 1 FROM gy_bookings WHERE booking_id=?", (bid,)):
            bid += "x"
        DB.execute("INSERT INTO gy_bookings VALUES(?,?,?,'booked')", (bid, slot_id, member_id))
        log(bid, uid, "book")
        DB.commit()
        return booking_row(q1("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)))


@app.post("/api/bookings/{booking_id}/{action}")
async def act(booking_id: str, action: str, request: Request):
    body = await body_of(request)
    uid = need_user(body)
    with LOCK:
        user = get_user(uid)
        if action not in ("cancel", "attend", "noshow"):
            raise err(404, "알 수 없는 동작입니다")
        b = q1("SELECT * FROM gy_bookings WHERE booking_id=?", (booking_id,))
        if not b:
            raise err(404, "예약을 찾을 수 없습니다")
        if action == "cancel":
            if user["role"] != "desk" and b["member_id"] != uid:
                raise err(403, "본인 예약만 취소할 수 있습니다")
        elif user["role"] != "desk":
            raise err(403, "데스크만 할 수 있습니다")
        if b["status"] != "booked":
            raise err(409, "지금 상태에서는 할 수 없습니다")
        slot = q1("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],))
        start = datetime.strptime(slot["starts_at"], FMT)
        now = datetime.now()
        if action == "cancel":
            if now > start - timedelta(hours=2):
                raise err(409, "취소 마감이 지났습니다 (시작 2시간 전까지)")
            DB.execute("UPDATE gy_bookings SET status='cancelled' WHERE booking_id=?", (booking_id,))
        else:
            if now < start:
                raise err(409, "아직 시작하지 않은 수업입니다")
            DB.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?",
                       ("attended" if action == "attend" else "noshow", booking_id))
            DB.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (b["member_id"],))
        log(booking_id, uid, action)
        DB.commit()
        return booking_row(q1("SELECT * FROM gy_bookings WHERE booking_id=?", (booking_id,)))
