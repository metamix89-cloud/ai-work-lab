# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R9 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
예약 가능 = 잔여 − 예약 중. 차감은 출석 · 노쇼 때. 취소 마감은 시작 2시간 전(그 시각은 됨)."""
import csv
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "gym.db")
LOCK = threading.Lock()
app = FastAPI()
FMT = "%Y-%m-%d %H:%M"


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE gy_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE gy_passes(member_id TEXT PRIMARY KEY, kind TEXT, total INTEGER, used INTEGER, expires_on TEXT);
    CREATE TABLE gy_slots(slot_id TEXT PRIMARY KEY, starts_at TEXT, trainer TEXT, capacity INTEGER);
    CREATE TABLE gy_bookings(booking_id TEXT PRIMARY KEY, slot_id TEXT, member_id TEXT, status TEXT);
    CREATE TABLE gy_log(booking_id TEXT, at TEXT, by TEXT, action TEXT);""")
    for name, table, n in (("users.csv", "gy_users", 3), ("passes.csv", "gy_passes", 5), ("slots.csv", "gy_slots", 4), ("bookings.csv", "gy_bookings", 4)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def need_user(uid):
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, "사용자를 확인하세요")


def find_user(c, uid):
    u = c.execute("SELECT * FROM gy_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    return u


def pass_view(c, mid):
    p = c.execute("SELECT * FROM gy_passes WHERE member_id=?", (mid,)).fetchone()
    if not p:
        raise HTTPException(404, "회원권이 없습니다")
    held = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE member_id=? AND status='booked'", (mid,)).fetchone()[0]
    left = int(p["total"]) - int(p["used"])
    return {"member_id": mid, "kind": p["kind"], "total": int(p["total"]), "used": int(p["used"]), "left": left, "held": held,
            "available": left - held, "expires_on": p["expires_on"], "expired": p["expires_on"] < date.today().isoformat()}


def booking_view(c, b):
    s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],)).fetchone()
    m = c.execute("SELECT name FROM gy_users WHERE user_id=?", (b["member_id"],)).fetchone()
    return {"booking_id": b["booking_id"], "slot_id": b["slot_id"], "starts_at": s["starts_at"] if s else None, "trainer": s["trainer"] if s else None,
            "member_id": b["member_id"], "member_name": m["name"] if m else b["member_id"], "status": b["status"]}


def noshows_30d(c, mid):
    since = (date.today() - timedelta(days=29)).isoformat()
    return c.execute("""SELECT COUNT(*) FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id
                        WHERE b.member_id=? AND b.status='noshow' AND substr(s.starts_at,1,10) >= ?""", (mid, since)).fetchone()[0]


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM gy_users ORDER BY rowid")]


@app.get("/api/slots")
def slots():
    c = con()
    out = []
    for s in c.execute("SELECT * FROM gy_slots ORDER BY starts_at, slot_id"):
        booked = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'", (s["slot_id"],)).fetchone()[0]
        out.append({"slot_id": s["slot_id"], "starts_at": s["starts_at"], "trainer": s["trainer"], "capacity": int(s["capacity"]),
                    "booked": booked, "left": int(s["capacity"]) - booked})
    return out


@app.get("/api/passes/{mid}")
def passes(mid: str):
    return pass_view(con(), mid)


@app.get("/api/bookings")
def bookings(viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    u = find_user(c, viewer)
    q = "SELECT b.* FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id"
    rows = c.execute(q + " WHERE b.member_id=? ORDER BY s.starts_at, b.booking_id", (viewer,)) if u["role"] == "member" else c.execute(q + " ORDER BY s.starts_at, b.booking_id")
    return [booking_view(c, b) for b in rows.fetchall()]


@app.post("/api/bookings", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    mid, sid = body.get("member_id"), body.get("slot_id")
    if not isinstance(mid, str) or not isinstance(sid, str):
        raise HTTPException(400, "입력을 확인하세요")
    with LOCK:
        c = con()
        u = find_user(c, body["user"])
        find_user(c, mid)
        p = pass_view(c, mid)
        s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404, "수업이 없습니다")
        if u["role"] == "member" and mid != u["user_id"]:
            raise HTTPException(403, "본인 예약만 할 수 있습니다")
        start = datetime.strptime(s["starts_at"], FMT)
        if start < datetime.now():
            raise HTTPException(409, "지난 수업입니다")
        if s["starts_at"][:10] > p["expires_on"]:
            raise HTTPException(409, "회원권 유효기간이 지났습니다")
        if noshows_30d(c, mid) >= 3:
            raise HTTPException(409, "노쇼 3회 — 데스크에 문의하세요")
        if p["available"] < 1:
            raise HTTPException(409, "예약 가능 횟수가 없습니다")
        booked = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'", (sid,)).fetchone()[0]
        if booked >= int(s["capacity"]):
            raise HTTPException(409, "정원이 찼습니다")
        if c.execute("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'", (sid, mid)).fetchone():
            raise HTTPException(409, "이미 예약한 수업입니다")
        nums = [int(r[0][2:]) for r in c.execute("SELECT booking_id FROM gy_bookings") if r[0][2:].isdigit()]
        bid = "B-%d" % (max(nums + [1000]) + 1)
        c.execute("INSERT INTO gy_bookings VALUES (?,?,?,?)", (bid, sid, mid, "booked"))
        c.execute("INSERT INTO gy_log VALUES (?,?,?,?)", (bid, datetime.now().strftime(FMT), u["user_id"], "book"))
        c.commit()
        return booking_view(c, c.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)).fetchone())


@app.post("/api/bookings/{bid}/{action}")
def do(bid: str, action: str, body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    with LOCK:
        c = con()
        b = c.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)).fetchone()
        if not b:
            raise HTTPException(404, "예약이 없습니다")
        u = find_user(c, body["user"])
        if action not in ("cancel", "attend", "noshow"):
            raise HTTPException(404, "없는 동작입니다")
        if action == "cancel":
            if u["role"] == "member" and b["member_id"] != u["user_id"]:
                raise HTTPException(403, "본인 예약만 취소할 수 있습니다")
        elif u["role"] != "desk":
            raise HTTPException(403, "데스크만 할 수 있습니다")
        if b["status"] != "booked":
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],)).fetchone()
        start = datetime.strptime(s["starts_at"], FMT)
        now = datetime.now()
        if action == "cancel":
            if now > start - timedelta(hours=2):
                raise HTTPException(409, "취소 마감이 지났습니다 (시작 2시간 전까지)")
            c.execute("UPDATE gy_bookings SET status='cancelled' WHERE booking_id=?", (bid,))
        else:
            if now < start:
                raise HTTPException(409, "아직 시작하지 않은 수업입니다")
            c.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?", ("attended" if action == "attend" else "noshow", bid))
            c.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (b["member_id"],))
        c.execute("INSERT INTO gy_log VALUES (?,?,?,?)", (bid, now.strftime(FMT), u["user_id"], action))
        c.commit()
        return booking_view(c, c.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)).fetchone())
