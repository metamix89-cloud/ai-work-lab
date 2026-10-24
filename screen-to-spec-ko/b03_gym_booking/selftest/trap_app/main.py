# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수만 모았다. T1 · T4 · T5 만 통과해야 채점기가 맞다.
실수: 예약 가능 = 잔여(예약 중을 안 뺌) · 예약할 때 차감하고 취소하면 돌려줌 · 취소 마감 없음 · 아직 안 시작한 수업도 출석 처리 ·
      누구나 출석 · 노쇼 처리 · 노쇼 누적 규칙 없음 · 예약을 본문보다 먼저 찾음 · 화면 없음."""
import csv
import os
import sqlite3
from datetime import date, datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "gym.db")
app = FastAPI()
FMT = "%Y-%m-%d %H:%M"


def load():
    if os.path.exists(DB):
        os.remove(DB)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE gy_users(user_id TEXT, name TEXT, role TEXT);
    CREATE TABLE gy_passes(member_id TEXT, kind TEXT, total INTEGER, used INTEGER, expires_on TEXT);
    CREATE TABLE gy_slots(slot_id TEXT, starts_at TEXT, trainer TEXT, capacity INTEGER);
    CREATE TABLE gy_bookings(booking_id TEXT, slot_id TEXT, member_id TEXT, status TEXT);""")
    for name, table, n in (("users.csv", "gy_users", 3), ("passes.csv", "gy_passes", 5), ("slots.csv", "gy_slots", 4), ("bookings.csv", "gy_bookings", 4)):
        with open(os.path.join(SEED, name), encoding="utf-8") as f:
            c.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    c.commit()
    c.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def bview(c, b):
    s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (b["slot_id"],)).fetchone()
    m = c.execute("SELECT name FROM gy_users WHERE user_id=?", (b["member_id"],)).fetchone()
    return {"booking_id": b["booking_id"], "slot_id": b["slot_id"], "starts_at": s["starts_at"], "trainer": s["trainer"],
            "member_id": b["member_id"], "member_name": m["name"] if m else "", "status": b["status"]}


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>수업 예약</h1></body></html>"


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM gy_users")]


@app.get("/api/slots")
def slots():
    c = con()
    out = []
    for s in c.execute("SELECT * FROM gy_slots ORDER BY starts_at"):
        n = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'", (s["slot_id"],)).fetchone()[0]
        out.append({"slot_id": s["slot_id"], "starts_at": s["starts_at"], "trainer": s["trainer"], "capacity": int(s["capacity"]), "booked": n, "left": int(s["capacity"]) - n})
    return out


@app.get("/api/passes/{mid}")
def passes(mid: str):
    c = con()
    p = c.execute("SELECT * FROM gy_passes WHERE member_id=?", (mid,)).fetchone()
    if not p:
        raise HTTPException(404, "회원권이 없습니다")
    held = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE member_id=? AND status='booked'", (mid,)).fetchone()[0]
    left = int(p["total"]) - int(p["used"])
    return {"member_id": mid, "kind": p["kind"], "total": int(p["total"]), "used": int(p["used"]), "left": left, "held": held,
            "available": left, "expires_on": p["expires_on"], "expired": p["expires_on"] < date.today().isoformat()}   # 실수: 예약 중을 안 뺌


@app.get("/api/bookings")
def bookings(viewer: str = ""):
    c = con()
    return [bview(c, b) for b in c.execute("SELECT b.* FROM gy_bookings b JOIN gy_slots s ON s.slot_id=b.slot_id ORDER BY s.starts_at")]   # 실수: 누구나 전부


@app.post("/api/bookings", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    c = con()
    mid, sid = body.get("member_id"), body.get("slot_id")
    p = c.execute("SELECT * FROM gy_passes WHERE member_id=?", (mid,)).fetchone()
    s = c.execute("SELECT * FROM gy_slots WHERE slot_id=?", (sid,)).fetchone()
    if not p or not s:
        raise HTTPException(404, "회원 또는 수업이 없습니다")
    if datetime.strptime(s["starts_at"], FMT) < datetime.now():
        raise HTTPException(409, "지난 수업입니다")
    if s["starts_at"][:10] > p["expires_on"]:
        raise HTTPException(409, "회원권 유효기간이 지났습니다")
    if int(p["total"]) - int(p["used"]) < 1:
        raise HTTPException(409, "예약 가능 횟수가 없습니다")                 # 실수: 예약 중을 안 뺌 · 노쇼 누적 없음
    n = c.execute("SELECT COUNT(*) FROM gy_bookings WHERE slot_id=? AND status='booked'", (sid,)).fetchone()[0]
    if n >= int(s["capacity"]):
        raise HTTPException(409, "정원이 찼습니다")
    if c.execute("SELECT 1 FROM gy_bookings WHERE slot_id=? AND member_id=? AND status='booked'", (sid, mid)).fetchone():
        raise HTTPException(409, "이미 예약한 수업입니다")
    bid = "B-%d" % (1000 + c.execute("SELECT COUNT(*) FROM gy_bookings").fetchone()[0] + 1)
    c.execute("INSERT INTO gy_bookings VALUES (?,?,?,?)", (bid, sid, mid, "booked"))
    c.execute("UPDATE gy_passes SET used=used+1 WHERE member_id=?", (mid,))            # 실수: 예약할 때 차감
    c.commit()
    return bview(c, c.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)).fetchone())


@app.post("/api/bookings/{bid}/{action}")
def do(bid: str, action: str, body: dict[str, Any] = Body(default={})):
    c = con()
    b = c.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)).fetchone()
    if not b:
        raise HTTPException(404, "예약이 없습니다")                             # 실수: 본문(400)보다 먼저
    if b["status"] != "booked":
        raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
    if action == "cancel":                                                     # 실수: 마감 없음 · 취소하면 돌려줌 · 누구나
        c.execute("UPDATE gy_bookings SET status='cancelled' WHERE booking_id=?", (bid,))
        c.execute("UPDATE gy_passes SET used=used-1 WHERE member_id=?", (b["member_id"],))
    elif action in ("attend", "noshow"):                                       # 실수: 누구나 · 시작 전에도 · 차감은 이미 했으니 안 함
        c.execute("UPDATE gy_bookings SET status=? WHERE booking_id=?", ("attended" if action == "attend" else "noshow", bid))
    else:
        raise HTTPException(404, "없는 동작입니다")
    c.commit()
    return bview(c, c.execute("SELECT * FROM gy_bookings WHERE booking_id=?", (bid,)).fetchone())
