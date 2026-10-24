import csv
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).parent
SEED = ROOT / "seed"
DB = ROOT / "gym.db"
FMT = "%Y-%m-%d %H:%M"
LOCK = threading.RLock()

app = FastAPI()


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    with LOCK:
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = Path(str(DB) + suffix)
            if p.exists():
                p.unlink()
        c = sqlite3.connect(DB)
        c.executescript(
            """
            CREATE TABLE gy_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
            CREATE TABLE gy_passes(member_id TEXT PRIMARY KEY, kind TEXT, total INTEGER, used INTEGER, expires_on TEXT);
            CREATE TABLE gy_slots(slot_id TEXT PRIMARY KEY, starts_at TEXT, trainer TEXT, capacity INTEGER);
            CREATE TABLE gy_bookings(booking_id TEXT PRIMARY KEY, slot_id TEXT, member_id TEXT, status TEXT, seq INTEGER);
            CREATE TABLE gy_log(booking_id TEXT, at TEXT, by TEXT, action TEXT);
            """
        )
        for r in read_csv("users.csv"):
            c.execute("INSERT INTO gy_users VALUES(?,?,?)", (r["user_id"].strip(), r["name"].strip(), r["role"].strip()))
        for r in read_csv("passes.csv"):
            c.execute("INSERT INTO gy_passes VALUES(?,?,?,?,?)",
                      (r["member_id"].strip(), r["kind"].strip(), int(r["total"]), int(r["used"]), r["expires_on"].strip()))
        for r in read_csv("slots.csv"):
            c.execute("INSERT INTO gy_slots VALUES(?,?,?,?)",
                      (r["slot_id"].strip(), r["starts_at"].strip(), r["trainer"].strip(), int(r["capacity"])))
        for i, r in enumerate(read_csv("bookings.csv")):
            c.execute("INSERT INTO gy_bookings VALUES(?,?,?,?,?)",
                      (r["booking_id"].strip(), r["slot_id"].strip(), r["member_id"].strip(), r["status"].strip(), i))
        c.commit()
        c.close()


init_db()


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def need_str(data, key, detail):
    v = data.get(key)
    if not isinstance(v, str) or not v.strip():
        raise Reject(400, detail)
    return v


def parse_dt(s):
    return datetime.strptime(s, FMT)


def pass_info(c, member_id):
    p = c.execute("SELECT * FROM gy_passes WHERE member_id=?", (member_id,)).fetchone()
    if p is None:
        return None
    held = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE member_id=? AND status='booked'", (member_id,)).fetchone()[0]
    left = p["total"] - p["used"]
    return {
        "member_id": member_id, "kind": p["kind"], "total": p["total"], "used": p["used"],
        "left": left, "held": held, "available": left - held, "expires_on": p["expires_on"],
        "expired": p["expires_on"] < datetime.now().strftime("%Y-%m-%d"),
    }


def booking_out(c, booking_id):
    r = c.execute(
        """SELECT b.booking_id, b.slot_id, s.starts_at, s.trainer, b.member_id,
                  COALESCE(u.name, b.member_id) AS member_name, b.status
           FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
           LEFT JOIN gy_users u ON u.user_id=b.member_id WHERE b.booking_id=?""", (booking_id,)).fetchone()
    return dict(r)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/users")
def users():
    with LOCK, db() as c:
        return [dict(r) for r in c.execute("SELECT user_id,name,role FROM gy_users ORDER BY rowid")]


@app.get("/api/slots")
def slots():
    with LOCK, db() as c:
        rows = c.execute(
            """SELECT s.slot_id, s.starts_at, s.trainer, s.capacity,
                      (SELECT COUNT(*) FROM gy_bookings b WHERE b.slot_id=s.slot_id AND b.status='booked') AS booked
               FROM gy_slots s ORDER BY s.starts_at, s.slot_id""").fetchall()
        return [dict(r, left=r["capacity"] - r["booked"]) for r in rows]


@app.get("/api/passes/{member_id}")
def passes(member_id: str):
    with LOCK, db() as c:
        info = pass_info(c, member_id)
        if info is None:
            raise Reject(404, "회원권을 찾을 수 없습니다")
        return info


@app.get("/api/bookings")
def bookings(viewer: str = ""):
    with LOCK, db() as c:
        u = c.execute("SELECT * FROM gy_users WHERE user_id=?", (viewer,)).fetchone()
        if u is None:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        sql = """SELECT b.booking_id FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id"""
        args = ()
        if u["role"] != "desk":
            sql += " WHERE b.member_id=?"
            args = (viewer,)
        sql += " ORDER BY s.starts_at, b.seq"
        return [booking_out(c, r[0]) for r in c.execute(sql, args).fetchall()]


@app.post("/api/bookings", status_code=201)
async def create_booking(request: Request):
    data = await body_of(request)
    with LOCK, db() as c:
        user = need_str(data, "user", "사용자를 확인하세요")
        member_id = need_str(data, "member_id", "회원을 확인하세요")
        slot_id = need_str(data, "slot_id", "수업을 확인하세요")
        u = c.execute("SELECT * FROM gy_users WHERE user_id=?", (user,)).fetchone()
        if u is None:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        m = c.execute("SELECT * FROM gy_users WHERE user_id=? AND role='member'", (member_id,)).fetchone()
        if m is None:
            raise Reject(404, "회원을 찾을 수 없습니다")
        s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (slot_id,)).fetchone()
        if s is None:
            raise Reject(404, "수업을 찾을 수 없습니다")
        if u["role"] != "desk" and member_id != user:
            raise Reject(403, "본인 예약만 할 수 있습니다")
        info = pass_info(c, member_id)
        if info is None:
            raise Reject(404, "회원권을 찾을 수 없습니다")

        now = datetime.now()
        start = parse_dt(s["starts_at"])
        if start < now:
            raise Reject(409, "지난 수업입니다")
        if start.strftime("%Y-%m-%d") > info["expires_on"]:
            raise Reject(409, "회원권 유효기간이 지났습니다")
        since = (now.date() - timedelta(days=29)).strftime("%Y-%m-%d")
        noshows = c.execute(
            """SELECT COUNT(*) FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
               WHERE b.member_id=? AND b.status='noshow' AND substr(s.starts_at,1,10)>=?""",
            (member_id, since)).fetchone()[0]
        if noshows >= 3:
            raise Reject(409, "노쇼 3회 — 데스크에 문의하세요")
        if info["available"] < 1:
            raise Reject(409, "예약 가능 횟수가 없습니다")
        booked = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'", (slot_id,)).fetchone()[0]
        if booked >= s["capacity"]:
            raise Reject(409, "정원이 찼습니다")
        dup = c.execute("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'",
                        (slot_id, member_id)).fetchone()
        if dup:
            raise Reject(409, "이미 예약한 수업입니다")

        ids = {r[0] for r in c.execute("SELECT booking_id FROM gy_bookings")}
        n = len(ids) + 1001
        while f"B-{n}" in ids:
            n += 1
        bid = f"B-{n}"
        seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM gy_bookings").fetchone()[0]
        c.execute("INSERT INTO gy_bookings VALUES(?,?,?,?,?)", (bid, slot_id, member_id, "booked", seq))
        c.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (bid, now.strftime("%Y-%m-%d %H:%M:%S"), user, "book"))
        c.commit()
        return booking_out(c, bid)


@app.post("/api/bookings/{booking_id}/{action}")
async def act_booking(booking_id: str, action: str, request: Request):
    data = await body_of(request)
    with LOCK, db() as c:
        user = need_str(data, "user", "사용자를 확인하세요")
        if action not in ("cancel", "attend", "noshow"):
            raise Reject(404, "알 수 없는 동작입니다")
        u = c.execute("SELECT * FROM gy_users WHERE user_id=?", (user,)).fetchone()
        if u is None:
            raise Reject(404, "사용자를 찾을 수 없습니다")
        b = c.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (booking_id,)).fetchone()
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
        s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],)).fetchone()
        start = parse_dt(s["starts_at"])
        now = datetime.now()
        if action == "cancel":
            if now > start - timedelta(hours=2):
                raise Reject(409, "취소 마감이 지났습니다 (시작 2시간 전까지)")
            new = "cancelled"
        else:
            if now < start:
                raise Reject(409, "아직 시작하지 않은 수업입니다")
            new = "attended" if action == "attend" else "noshow"
            c.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (b["member_id"],))
        c.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?", (new, booking_id))
        c.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (booking_id, now.strftime("%Y-%m-%d %H:%M:%S"), user, action))
        c.commit()
        return booking_out(c, booking_id)
