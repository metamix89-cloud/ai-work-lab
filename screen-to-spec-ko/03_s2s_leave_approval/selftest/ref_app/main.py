# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R8 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "leave.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE lv_users(user TEXT PRIMARY KEY, team TEXT, role TEXT, manager TEXT, leave_total INTEGER);
    CREATE TABLE lv_requests(req_id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, type TEXT, start TEXT, end TEXT, days INTEGER,
                             reason TEXT, status TEXT, approver TEXT, reject_reason TEXT);""")
    for name, table, n in (("users.csv", "lv_users", 5), ("requests.csv", "lv_requests", 10)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def business_days(start, end):
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    n, d = 0, d0
    while d <= d1:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


class ReqIn(BaseModel):
    user: str
    type: str
    start: str
    end: str
    reason: str = ""


class Approver(BaseModel):
    approver: str
    reason: str = ""


class Who(BaseModel):
    user: str


def user_row(c, name):
    r = c.execute("SELECT * FROM lv_users WHERE user=?", (name,)).fetchone()
    if not r:
        raise HTTPException(400, "존재하지 않는 사용자입니다")
    return r


def calc_balance(c, name):
    u = user_row(c, name)
    used = c.execute("SELECT COALESCE(SUM(days),0) FROM lv_requests WHERE user=? AND type='연차' AND status='승인'", (name,)).fetchone()[0]
    pending = c.execute("SELECT COALESCE(SUM(days),0) FROM lv_requests WHERE user=? AND type='연차' AND status='신청'", (name,)).fetchone()[0]
    return {"total": u["leave_total"], "used": used, "pending": pending, "remaining": u["leave_total"] - used - pending}


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(r) for r in con().execute("SELECT * FROM lv_users")]


@app.get("/api/balance")
def balance(user: str):
    return calc_balance(con(), user)


@app.get("/api/requests")
def requests(user: str = "", approver: str = ""):
    c = con()
    if user:
        return [dict(r) for r in c.execute("SELECT * FROM lv_requests WHERE user=? ORDER BY req_id DESC", (user,))]
    if approver:
        return [dict(r) for r in c.execute("""SELECT r.* FROM lv_requests r JOIN lv_users u ON u.user=r.user
                                              WHERE u.manager=? AND r.status='신청' ORDER BY r.req_id""", (approver,))]
    raise HTTPException(400, "user 또는 approver 가 필요합니다")


@app.post("/api/requests", status_code=201)
def create(r: ReqIn):
    c = con()
    user_row(c, r.user)
    if r.type not in ("연차", "출장"):
        raise HTTPException(400, "종류는 연차 또는 출장입니다")
    try:
        if r.end < r.start or dt.date.fromisoformat(r.end) < dt.date.fromisoformat(r.start):
            raise HTTPException(400, "종료일이 시작일보다 빠릅니다")
    except ValueError:
        raise HTTPException(400, "날짜 형식은 YYYY-MM-DD 입니다")
    days = business_days(r.start, r.end)
    if days == 0:
        raise HTTPException(400, "주말만 포함된 기간입니다")
    clash = c.execute("""SELECT 1 FROM lv_requests WHERE user=? AND status IN ('신청','승인') AND start<=? AND end>=?""",
                      (r.user, r.end, r.start)).fetchone()
    if clash:
        raise HTTPException(409, "이미 신청한 기간과 겹칩니다")
    if r.type == "연차" and days > calc_balance(c, r.user)["remaining"]:
        raise HTTPException(400, "잔여 연차가 부족합니다")
    cur = c.execute("INSERT INTO lv_requests(user,type,start,end,days,reason,status,approver,reject_reason) VALUES (?,?,?,?,?,?,'신청','','')",
                    (r.user, r.type, r.start, r.end, days, r.reason))
    c.commit()
    return dict(c.execute("SELECT * FROM lv_requests WHERE req_id=?", (cur.lastrowid,)).fetchone())


def decide(req_id, approver, new_status, reason=""):
    c = con()
    row = c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
    if not row:
        raise HTTPException(404, "신청이 없습니다")
    owner = user_row(c, row["user"])
    if not approver or approver != owner["manager"]:
        raise HTTPException(403, "결재 권한이 없습니다")
    if new_status == "반려" and not reason.strip():
        raise HTTPException(400, "반려 사유를 입력하세요")
    if row["status"] != "신청":
        raise HTTPException(409, "이미 처리된 신청입니다")
    c.execute("UPDATE lv_requests SET status=?, approver=?, reject_reason=? WHERE req_id=?", (new_status, approver, reason.strip(), req_id))
    c.commit()
    return dict(c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone())


@app.post("/api/requests/{req_id}/approve")
def approve(req_id: int, a: Approver):
    return decide(req_id, a.approver, "승인")


@app.post("/api/requests/{req_id}/reject")
def reject(req_id: int, a: Approver):
    return decide(req_id, a.approver, "반려", a.reason)


@app.post("/api/requests/{req_id}/cancel")
def cancel(req_id: int, w: Who):
    c = con()
    row = c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
    if not row:
        raise HTTPException(404, "신청이 없습니다")
    if row["user"] != w.user:
        raise HTTPException(403, "본인 신청만 취소할 수 있습니다")
    if row["status"] != "신청":
        raise HTTPException(409, "이미 처리된 신청입니다")
    c.execute("UPDATE lv_requests SET status='취소' WHERE req_id=?", (req_id,))
    c.commit()
    return dict(c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone())
