import csv
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.requests import Request

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "gym.db"
FMT = "%Y-%m-%d %H:%M"

app = FastAPI()
lock = threading.RLock()
db = None


def read_csv(name):
    with open(SEED / name, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def init_db():
    global db
    if db is not None:
        db.close()
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(str(DB_PATH) + suffix)
        except OSError:
            pass
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE gy_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE gy_passes(member_id TEXT PRIMARY KEY, kind TEXT, total INTEGER,
                               used INTEGER, expires_on TEXT);
        CREATE TABLE gy_slots(slot_id TEXT PRIMARY KEY, starts_at TEXT, trainer TEXT,
                              capacity INTEGER);
        CREATE TABLE gy_bookings(booking_id TEXT PRIMARY KEY, slot_id TEXT, member_id TEXT,
                                 status TEXT);
        CREATE TABLE gy_log(booking_id TEXT, at TEXT, by TEXT, action TEXT);
        """
    )
    for r in read_csv("users.csv"):
        db.execute("INSERT INTO gy_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("passes.csv"):
        db.execute("INSERT INTO gy_passes VALUES(?,?,?,?,?)",
                   (r["member_id"], r["kind"], int(r["total"]), int(r["used"]), r["expires_on"]))
    for r in read_csv("slots.csv"):
        db.execute("INSERT INTO gy_slots VALUES(?,?,?,?)",
                   (r["slot_id"], r["starts_at"], r["trainer"], int(r["capacity"])))
    for r in read_csv("bookings.csv"):
        db.execute("INSERT INTO gy_bookings VALUES(?,?,?,?)",
                   (r["booking_id"], r["slot_id"], r["member_id"], r["status"]))
    db.commit()


init_db()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def q1(sql, *args):
    return db.execute(sql, args).fetchone()


def qa(sql, *args):
    return db.execute(sql, args).fetchall()


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = None
    return data if isinstance(data, dict) else {}


def need_str(data, key, msg=None):
    v = data.get(key)
    if not isinstance(v, str) or not v:
        raise Reject(400, msg or "사용자를 확인하세요")
    return v


def pass_info(member_id):
    p = q1("SELECT * FROM gy_passes WHERE member_id=?", member_id)
    if p is None:
        raise Reject(404, "회원권을 찾을 수 없습니다")
    held = q1("SELECT COUNT(*) c FROM gy_bookings WHERE member_id=? AND status='booked'",
              member_id)["c"]
    left = p["total"] - p["used"]
    return {
        "member_id": member_id, "kind": p["kind"], "total": p["total"], "used": p["used"],
        "left": left, "held": held, "available": left - held, "expires_on": p["expires_on"],
        "expired": p["expires_on"] < datetime.now().strftime("%Y-%m-%d"),
    }


def booking_out(booking_id):
    r = q1(
        """SELECT b.booking_id, b.slot_id, s.starts_at, s.trainer, b.member_id,
                  u.name AS member_name, b.status
           FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
           LEFT JOIN gy_users u ON u.user_id=b.member_id WHERE b.booking_id=?""", booking_id)
    return dict(r)


def log(booking_id, by, action):
    db.execute("INSERT INTO gy_log VALUES(?,?,?,?)",
               (booking_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), by, action))


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in qa("SELECT user_id,name,role FROM gy_users ORDER BY rowid")]


@app.get("/api/slots")
def slots():
    with lock:
        rows = qa(
            """SELECT s.slot_id, s.starts_at, s.trainer, s.capacity,
                      (SELECT COUNT(*) FROM gy_bookings b
                        WHERE b.slot_id=s.slot_id AND b.status='booked') AS booked
               FROM gy_slots s ORDER BY s.starts_at, s.slot_id""")
        out = []
        for r in rows:
            d = dict(r)
            d["left"] = d["capacity"] - d["booked"]
            out.append(d)
        return out


@app.get("/api/passes/{member_id}")
def passes(member_id: str):
    with lock:
        return pass_info(member_id)


@app.get("/api/bookings")
def bookings(viewer: str = None):
    with lock:
        if not viewer:
            raise Reject(400, "사용자를 확인하세요")
        u = q1("SELECT * FROM gy_users WHERE user_id=?", viewer)
        if u is None:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        sql = """SELECT b.booking_id FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id"""
        args = ()
        if u["role"] != "desk":
            sql += " WHERE b.member_id=?"
            args = (viewer,)
        sql += " ORDER BY s.starts_at, b.booking_id"
        return [booking_out(r["booking_id"]) for r in qa(sql, *args)]


@app.post("/api/bookings", status_code=201)
async def create_booking(request: Request):
    data = await body_of(request)
    with lock:
        user = need_str(data, "user")
        member_id = need_str(data, "member_id", "회원을 확인하세요")
        slot_id = need_str(data, "slot_id", "수업을 확인하세요")
        u = q1("SELECT * FROM gy_users WHERE user_id=?", user)
        if u is None:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        m = q1("SELECT * FROM gy_users WHERE user_id=? AND role='member'", member_id)
        if m is None:
            raise Reject(404, "회원을 찾을 수 없습니다")
        slot = q1("SELECT * FROM gy_slots WHERE slot_id=?", slot_id)
        if slot is None:
            raise Reject(404, "수업을 찾을 수 없습니다")
        if u["role"] != "desk" and member_id != user:
            raise Reject(403, "본인 예약만 할 수 있습니다")
        now = datetime.now()
        start = datetime.strptime(slot["starts_at"], FMT)
        if start < now:
            raise Reject(409, "지난 수업입니다")
        p = q1("SELECT * FROM gy_passes WHERE member_id=?", member_id)
        if p is None:
            raise Reject(404, "회원권을 찾을 수 없습니다")
        if start.strftime("%Y-%m-%d") > p["expires_on"]:
            raise Reject(409, "회원권 유효기간이 지났습니다")
        since = (now - timedelta(days=29)).strftime("%Y-%m-%d")
        ns = q1(
            """SELECT COUNT(*) c FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
               WHERE b.member_id=? AND b.status='noshow' AND substr(s.starts_at,1,10)>=?""",
            member_id, since)["c"]
        if ns >= 3:
            raise Reject(409, "노쇼 3회 — 데스크에 문의하세요")
        if pass_info(member_id)["available"] < 1:
            raise Reject(409, "예약 가능 횟수가 없습니다")
        booked = q1("SELECT COUNT(*) c FROM gy_bookings WHERE slot_id=? AND status='booked'",
                    slot_id)["c"]
        if booked >= slot["capacity"]:
            raise Reject(409, "정원이 찼습니다")
        if q1("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'",
              slot_id, member_id):
            raise Reject(409, "이미 예약한 수업입니다")
        n = 1001
        for r in qa("SELECT booking_id FROM gy_bookings"):
            tail = r["booking_id"].split("-")[-1]
            if tail.isdigit():
                n = max(n, int(tail) + 1)
        bid = "B-%d" % n
        while q1("SELECT 1 FROM gy_bookings WHERE booking_id=?", bid):
            n += 1
            bid = "B-%d" % n
        db.execute("INSERT INTO gy_bookings VALUES(?,?,?,'booked')", (bid, slot_id, member_id))
        log(bid, user, "book")
        db.commit()
        return booking_out(bid)


@app.post("/api/bookings/{booking_id}/{action}")
async def act_booking(booking_id: str, action: str, request: Request):
    data = await body_of(request)
    with lock:
        user = need_str(data, "user")
        if action not in ("cancel", "attend", "noshow"):
            raise Reject(404, "알 수 없는 동작입니다")
        u = q1("SELECT * FROM gy_users WHERE user_id=?", user)
        b = q1("SELECT * FROM gy_bookings WHERE booking_id=?", booking_id)
        if u is None:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        if b is None:
            raise Reject(404, "예약을 찾을 수 없습니다")
        desk = u["role"] == "desk"
        if action == "cancel":
            if not desk and b["member_id"] != user:
                raise Reject(403, "본인 예약만 할 수 있습니다")
        elif not desk:
            raise Reject(403, "데스크만 할 수 있습니다")
        if b["status"] != "booked":
            raise Reject(409, "지금 상태에서는 할 수 없습니다")
        slot = q1("SELECT * FROM gy_slots WHERE slot_id=?", b["slot_id"])
        start = datetime.strptime(slot["starts_at"], FMT)
        now = datetime.now()
        if action == "cancel":
            if now > start - timedelta(hours=2):
                raise Reject(409, "취소 마감이 지났습니다 (시작 2시간 전까지)")
            status = "cancelled"
        else:
            if now < start:
                raise Reject(409, "아직 시작하지 않은 수업입니다")
            status = "attended" if action == "attend" else "noshow"
            db.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (b["member_id"],))
        db.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?", (status, booking_id))
        log(booking_id, user, action)
        db.commit()
        return booking_out(booking_id)
