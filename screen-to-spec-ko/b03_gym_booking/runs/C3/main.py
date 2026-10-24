import csv
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "gym.db")
FMT = "%Y-%m-%d %H:%M"
LOCK = threading.RLock()

app = FastAPI()


def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    c = conn()
    c.executescript("""
    CREATE TABLE gy_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE gy_passes(member_id TEXT PRIMARY KEY, kind TEXT, total INTEGER, used INTEGER, expires_on TEXT);
    CREATE TABLE gy_slots(slot_id TEXT PRIMARY KEY, starts_at TEXT, trainer TEXT, capacity INTEGER);
    CREATE TABLE gy_bookings(booking_id TEXT PRIMARY KEY, slot_id TEXT, member_id TEXT, status TEXT);
    CREATE TABLE gy_log(booking_id TEXT, at TEXT, by TEXT, action TEXT);
    """)
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
    c.close()


init_db()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def on_reject(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def need_str(b, key, detail):
    v = b.get(key)
    if not isinstance(v, str) or not v:
        raise Reject(400, detail)
    return v


def booking_row(c, bid):
    r = c.execute("""SELECT b.booking_id, b.slot_id, s.starts_at, s.trainer, b.member_id,
                     COALESCE(u.name,'') AS member_name, b.status
                     FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
                     LEFT JOIN gy_users u ON u.user_id=b.member_id WHERE b.booking_id=?""", (bid,)).fetchone()
    return dict(r) if r else None


def pass_info(c, member_id):
    p = c.execute("SELECT * FROM gy_passes WHERE member_id=?", (member_id,)).fetchone()
    if not p:
        return None
    held = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE member_id=? AND status='booked'",
                     (member_id,)).fetchone()[0]
    left = p["total"] - p["used"]
    return {"member_id": member_id, "kind": p["kind"], "total": p["total"], "used": p["used"],
            "left": left, "held": held, "available": left - held, "expires_on": p["expires_on"],
            "expired": p["expires_on"] < date.today().isoformat()}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with LOCK:
        c = conn()
        r = [dict(x) for x in c.execute("SELECT user_id,name,role FROM gy_users ORDER BY rowid")]
        c.close()
        return r


@app.get("/api/slots")
def slots():
    with LOCK:
        c = conn()
        r = []
        for s in c.execute("SELECT * FROM gy_slots ORDER BY starts_at, slot_id"):
            n = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'",
                          (s["slot_id"],)).fetchone()[0]
            r.append({"slot_id": s["slot_id"], "starts_at": s["starts_at"], "trainer": s["trainer"],
                      "capacity": s["capacity"], "booked": n, "left": s["capacity"] - n})
        c.close()
        return r


@app.get("/api/passes/{member_id}")
def passes(member_id: str):
    with LOCK:
        c = conn()
        p = pass_info(c, member_id)
        c.close()
        if not p:
            raise Reject(404, "회원권을 찾을 수 없습니다")
        return p


@app.get("/api/bookings")
def bookings(viewer: str = None):
    if not viewer:
        raise Reject(400, "사용자를 확인하세요")
    with LOCK:
        c = conn()
        u = c.execute("SELECT * FROM gy_users WHERE user_id=?", (viewer,)).fetchone()
        if not u:
            c.close()
            raise Reject(404, "사용자를 찾을 수 없습니다")
        ids = [x[0] for x in c.execute(
            "SELECT b.booking_id FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id "
            "WHERE (?='desk' OR b.member_id=?) ORDER BY s.starts_at, b.booking_id", (u["role"], viewer))]
        r = [booking_row(c, i) for i in ids]
        c.close()
        return r


@app.post("/api/bookings", status_code=201)
async def create_booking(request: Request):
    b = await body_of(request)
    user = need_str(b, "user", "사용자를 확인하세요")
    member_id = need_str(b, "member_id", "회원을 확인하세요")
    slot_id = need_str(b, "slot_id", "수업을 확인하세요")
    with LOCK:
        c = conn()
        try:
            u = c.execute("SELECT * FROM gy_users WHERE user_id=?", (user,)).fetchone()
            if not u:
                raise Reject(404, "사용자를 찾을 수 없습니다")
            m = c.execute("SELECT * FROM gy_users WHERE user_id=? AND role='member'", (member_id,)).fetchone()
            if not m:
                raise Reject(404, "회원을 찾을 수 없습니다")
            s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (slot_id,)).fetchone()
            if not s:
                raise Reject(404, "수업을 찾을 수 없습니다")
            if u["role"] != "desk" and user != member_id:
                raise Reject(403, "본인 예약만 할 수 있습니다")
            now = datetime.now()
            start = datetime.strptime(s["starts_at"], FMT)
            if start < now:
                raise Reject(409, "지난 수업입니다")
            p = pass_info(c, member_id)
            if not p:
                raise Reject(404, "회원권을 찾을 수 없습니다")
            if s["starts_at"][:10] > p["expires_on"]:
                raise Reject(409, "회원권 유효기간이 지났습니다")
            since = (date.today() - timedelta(days=29)).isoformat()
            ns = c.execute("""SELECT COUNT(*) FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
                              WHERE b.member_id=? AND b.status='noshow' AND substr(s.starts_at,1,10)>=?""",
                           (member_id, since)).fetchone()[0]
            if ns >= 3:
                raise Reject(409, "노쇼 3회 — 데스크에 문의하세요")
            if p["available"] < 1:
                raise Reject(409, "예약 가능 횟수가 없습니다")
            n = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'",
                          (slot_id,)).fetchone()[0]
            if n >= s["capacity"]:
                raise Reject(409, "정원이 찼습니다")
            if c.execute("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'",
                         (slot_id, member_id)).fetchone():
                raise Reject(409, "이미 예약한 수업입니다")
            nums = [int(x[0][2:]) for x in c.execute("SELECT booking_id FROM gy_bookings")
                    if x[0][2:].isdigit()]
            bid = "B-%d" % (max(nums + [1000]) + 1)
            c.execute("INSERT INTO gy_bookings VALUES(?,?,?,'booked')", (bid, slot_id, member_id))
            c.execute("INSERT INTO gy_log VALUES(?,?,?,?)", (bid, now.strftime("%Y-%m-%d %H:%M:%S"), user, "book"))
            c.commit()
            return booking_row(c, bid)
        finally:
            c.close()


@app.post("/api/bookings/{booking_id}/{action}")
async def booking_action(booking_id: str, action: str, request: Request):
    b = await body_of(request)
    user = need_str(b, "user", "사용자를 확인하세요")
    if action not in ("cancel", "attend", "noshow"):
        raise Reject(404, "알 수 없는 동작입니다")
    with LOCK:
        c = conn()
        try:
            u = c.execute("SELECT * FROM gy_users WHERE user_id=?", (user,)).fetchone()
            if not u:
                raise Reject(404, "사용자를 찾을 수 없습니다")
            bk = booking_row(c, booking_id)
            if not bk:
                raise Reject(404, "예약을 찾을 수 없습니다")
            if action == "cancel":
                if u["role"] != "desk" and bk["member_id"] != user:
                    raise Reject(403, "본인 예약만 취소할 수 있습니다")
            elif u["role"] != "desk":
                raise Reject(403, "데스크만 할 수 있습니다")
            if bk["status"] != "booked":
                raise Reject(409, "지금 상태에서는 할 수 없습니다")
            now = datetime.now()
            start = datetime.strptime(bk["starts_at"], FMT)
            if action == "cancel":
                if now > start - timedelta(hours=2):
                    raise Reject(409, "취소 마감이 지났습니다 (시작 2시간 전까지)")
                new = "cancelled"
            else:
                if start > now:
                    raise Reject(409, "아직 시작하지 않은 수업입니다")
                new = "attended" if action == "attend" else "noshow"
                c.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (bk["member_id"],))
            c.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?", (new, booking_id))
            c.execute("INSERT INTO gy_log VALUES(?,?,?,?)",
                      (booking_id, now.strftime("%Y-%m-%d %H:%M:%S"), user, action))
            c.commit()
            return booking_row(c, booking_id)
        finally:
            c.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
