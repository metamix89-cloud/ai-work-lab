import csv
import os
import sqlite3
import threading
from datetime import date, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "leave.db")
LOCK = threading.Lock()


def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE lv_users (user TEXT PRIMARY KEY, team TEXT, role TEXT, manager TEXT, leave_total INTEGER)")
    con.execute("CREATE TABLE lv_requests (req_id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, type TEXT, start TEXT, "
                "end TEXT, days INTEGER, reason TEXT, status TEXT, approver TEXT, reject_reason TEXT)")
    with open(os.path.join(BASE, "seed", "users.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            con.execute("INSERT INTO lv_users VALUES (?,?,?,?,?)",
                        (r["user"], r["team"], r["role"], r.get("manager") or "", int(r["leave_total"] or 0)))
    with open(os.path.join(BASE, "seed", "requests.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            con.execute("INSERT INTO lv_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (int(r["req_id"]), r["user"], r["type"], r["start"], r["end"], int(r["days"] or 0),
                         r.get("reason") or "", r["status"], r.get("approver") or "", r.get("reject_reason") or ""))
    con.commit()
    con.close()


init_db()
app = FastAPI()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def s(v):
    return v.strip() if isinstance(v, str) else ""


def count_weekdays(start, end):
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def balance_of(con, user):
    u = con.execute("SELECT leave_total FROM lv_users WHERE user=?", (user,)).fetchone()
    if not u:
        return None

    def total(status):
        return con.execute("SELECT COALESCE(SUM(days),0) FROM lv_requests WHERE user=? AND type='연차' AND status=?",
                           (user, status)).fetchone()[0]

    used, pending = total("승인"), total("신청")
    return {"total": u["leave_total"], "used": used, "pending": pending, "remaining": u["leave_total"] - used - pending}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html")


@app.get("/api/users")
def users():
    with LOCK, db() as con:
        return [dict(r) for r in con.execute("SELECT user,team,role,manager,leave_total FROM lv_users ORDER BY rowid")]


@app.get("/api/balance")
def balance(user: str = ""):
    with LOCK, db() as con:
        b = balance_of(con, user)
    return b if b else err(404, "사용자를 찾을 수 없습니다")


@app.get("/api/requests")
def list_requests(user: str = "", approver: str = ""):
    with LOCK, db() as con:
        if approver:
            rows = con.execute("SELECT r.* FROM lv_requests r JOIN lv_users u ON u.user=r.user "
                               "WHERE u.manager=? AND r.status='신청' ORDER BY r.req_id", (approver,))
        else:
            rows = con.execute("SELECT * FROM lv_requests WHERE user=? ORDER BY req_id DESC", (user,))
        return [dict(r) for r in rows]


@app.post("/api/requests")
async def create(request: Request):
    b = await body_of(request)
    user, typ, reason = s(b.get("user")), s(b.get("type")), s(b.get("reason"))
    start_s, end_s = s(b.get("start")), s(b.get("end"))
    if not user or not typ or not start_s or not end_s or not reason:
        return err(400, "빈 값이 있습니다")
    if typ not in ("연차", "출장"):
        return err(400, "종류는 연차 또는 출장이어야 합니다")
    try:
        start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
    except ValueError:
        return err(400, "날짜 형식이 올바르지 않습니다")
    if end < start:
        return err(400, "종료일이 시작일보다 빠릅니다")
    days = count_weekdays(start, end)
    if days < 1:
        return err(400, "주말만 선택할 수 없습니다")
    with LOCK, db() as con:
        bal = balance_of(con, user)
        if bal is None:
            return err(400, "사용자를 찾을 수 없습니다")
        if typ == "연차" and days > bal["remaining"]:
            return err(400, "잔여 연차가 부족합니다")
        clash = con.execute("SELECT 1 FROM lv_requests WHERE user=? AND status IN ('신청','승인') AND start<=? AND end>=?",
                            (user, end_s, start_s)).fetchone()
        if clash:
            return err(409, "이미 신청한 기간과 겹칩니다")
        cur = con.execute("INSERT INTO lv_requests (user,type,start,end,days,reason,status,approver,reject_reason) "
                          "VALUES (?,?,?,?,?,?,'신청','','')", (user, typ, start_s, end_s, days, reason))
        row = con.execute("SELECT * FROM lv_requests WHERE req_id=?", (cur.lastrowid,)).fetchone()
    return JSONResponse(dict(row), status_code=201)


def decide(con, req_id, approver, new_status, reason=""):
    r = con.execute("SELECT r.*, u.manager AS mgr FROM lv_requests r LEFT JOIN lv_users u ON u.user=r.user "
                    "WHERE r.req_id=?", (req_id,)).fetchone()
    if not r:
        return err(404, "신청을 찾을 수 없습니다")
    if not approver or approver == r["user"] or approver != r["mgr"]:
        return err(403, "결재 권한이 없습니다")
    if new_status == "반려" and not reason:
        return err(400, "반려 사유를 입력하세요")
    if r["status"] != "신청":
        return err(409, "이미 처리된 신청입니다")
    con.execute("UPDATE lv_requests SET status=?, approver=?, reject_reason=? WHERE req_id=?",
                (new_status, approver, reason, req_id))
    return dict(con.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone())


@app.post("/api/requests/{req_id}/approve")
async def approve(req_id: int, request: Request):
    b = await body_of(request)
    with LOCK, db() as con:
        return decide(con, req_id, s(b.get("approver")), "승인")


@app.post("/api/requests/{req_id}/reject")
async def reject(req_id: int, request: Request):
    b = await body_of(request)
    with LOCK, db() as con:
        return decide(con, req_id, s(b.get("approver")), "반려", s(b.get("reason")))


@app.post("/api/requests/{req_id}/cancel")
async def cancel(req_id: int, request: Request):
    b = await body_of(request)
    user = s(b.get("user"))
    with LOCK, db() as con:
        r = con.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
        if not r:
            return err(404, "신청을 찾을 수 없습니다")
        if user != r["user"]:
            return err(403, "본인의 신청만 취소할 수 있습니다")
        if r["status"] != "신청":
            return err(409, "이미 처리된 신청입니다")
        con.execute("UPDATE lv_requests SET status='취소' WHERE req_id=?", (req_id,))
        return dict(con.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone())
