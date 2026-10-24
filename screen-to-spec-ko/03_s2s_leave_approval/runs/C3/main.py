import csv
import os
import sqlite3
import threading
from datetime import date, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "leave.db")
LOCK = threading.RLock()


def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE lv_users (user TEXT PRIMARY KEY, team TEXT, role TEXT, manager TEXT, leave_total INTEGER)")
    conn.execute("CREATE TABLE lv_requests (req_id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, type TEXT, "
                 "start TEXT, end TEXT, days INTEGER, reason TEXT, status TEXT, approver TEXT, reject_reason TEXT)")
    with open(os.path.join(BASE, "seed", "users.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            conn.execute("INSERT INTO lv_users VALUES (?,?,?,?,?)",
                         (r["user"], r["team"], r["role"], r["manager"] or "", int(r["leave_total"] or 0)))
    with open(os.path.join(BASE, "seed", "requests.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            conn.execute("INSERT INTO lv_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (int(r["req_id"]), r["user"], r["type"], r["start"], r["end"], int(r["days"] or 0),
                          r["reason"], r["status"], r["approver"] or "", r["reject_reason"] or ""))
    conn.commit()
    return conn


DB = init_db()
app = FastAPI()


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
        data = None
    return data if isinstance(data, dict) else {}


def s(v):
    return v.strip() if isinstance(v, str) else ""


def rows(sql, args=()):
    return [dict(r) for r in DB.execute(sql, args).fetchall()]


def get_user(name):
    r = DB.execute("SELECT * FROM lv_users WHERE user=?", (name,)).fetchone()
    return dict(r) if r else None


def get_req(req_id):
    r = DB.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
    if not r:
        raise Reject(404, "신청을 찾을 수 없습니다")
    return dict(r)


def parse_date(v):
    try:
        if len(v) != 10:
            raise ValueError
        return date.fromisoformat(v)
    except ValueError:
        raise Reject(400, "날짜는 YYYY-MM-DD 형식이어야 합니다")


def weekdays(a, b):
    return sum(1 for i in range((b - a).days + 1) if (a + timedelta(days=i)).weekday() < 5)


def calc_balance(user):
    u = get_user(user)
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")

    def total(status):
        return DB.execute("SELECT COALESCE(SUM(days),0) FROM lv_requests WHERE user=? AND type='연차' AND status=?",
                          (user, status)).fetchone()[0]
    used, pending = total("승인"), total("신청")
    return {"total": u["leave_total"], "used": used, "pending": pending, "remaining": u["leave_total"] - used - pending}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with LOCK:
        return rows("SELECT user, team, role, manager, leave_total FROM lv_users ORDER BY rowid")


@app.get("/api/balance")
def balance(user: str = ""):
    with LOCK:
        return calc_balance(user)


@app.get("/api/requests")
def list_requests(user: str = "", approver: str = ""):
    with LOCK:
        if approver:
            return rows("SELECT r.* FROM lv_requests r JOIN lv_users u ON u.user=r.user "
                        "WHERE u.manager=? AND r.status='신청' ORDER BY r.req_id DESC", (approver,))
        if user:
            return rows("SELECT * FROM lv_requests WHERE user=? ORDER BY req_id DESC", (user,))
        raise Reject(400, "user 또는 approver 가 필요합니다")


@app.post("/api/requests", status_code=201)
async def create_request(request: Request):
    b = await body_of(request)
    user, typ, start, end, reason = s(b.get("user")), s(b.get("type")), s(b.get("start")), s(b.get("end")), s(b.get("reason"))
    with LOCK:
        if not get_user(user):
            raise Reject(400, "사용자를 선택하세요")
        if typ not in ("연차", "출장"):
            raise Reject(400, "종류는 연차 또는 출장이어야 합니다")
        if not start or not end:
            raise Reject(400, "시작일과 종료일을 입력하세요")
        if not reason:
            raise Reject(400, "사유를 입력하세요")
        a, z = parse_date(start), parse_date(end)
        if z < a:
            raise Reject(400, "종료일이 시작일보다 빠릅니다")
        days = weekdays(a, z)
        if days == 0:
            raise Reject(400, "평일이 포함된 기간을 선택하세요")
        if typ == "연차" and days > calc_balance(user)["remaining"]:
            raise Reject(400, "잔여 연차가 부족합니다")
        if DB.execute("SELECT 1 FROM lv_requests WHERE user=? AND status IN ('신청','승인') AND start<=? AND end>=?",
                      (user, end, start)).fetchone():
            raise Reject(409, "이미 신청한 기간과 겹칩니다")
        cur = DB.execute("INSERT INTO lv_requests (user,type,start,end,days,reason,status,approver,reject_reason) "
                         "VALUES (?,?,?,?,?,?,'신청','','')", (user, typ, start, end, days, reason))
        DB.commit()
        return get_req(cur.lastrowid)


def check_manager(req, approver):
    u = get_user(req["user"])
    if not approver or not u or not u["manager"] or u["manager"] != approver:
        raise Reject(403, "결재 권한이 없습니다")


def already_done():
    return Reject(409, "이미 처리된 신청입니다")


@app.post("/api/requests/{req_id}/approve")
async def approve(req_id: int, request: Request):
    b = await body_of(request)
    approver = s(b.get("approver"))
    with LOCK:
        req = get_req(req_id)
        check_manager(req, approver)
        if req["status"] != "신청":
            raise already_done()
        DB.execute("UPDATE lv_requests SET status='승인', approver=? WHERE req_id=?", (approver, req_id))
        DB.commit()
        return get_req(req_id)


@app.post("/api/requests/{req_id}/reject")
async def reject(req_id: int, request: Request):
    b = await body_of(request)
    approver, reason = s(b.get("approver")), s(b.get("reason"))
    with LOCK:
        req = get_req(req_id)
        check_manager(req, approver)
        if not reason:
            raise Reject(400, "반려 사유를 입력하세요")
        if req["status"] != "신청":
            raise already_done()
        DB.execute("UPDATE lv_requests SET status='반려', approver=?, reject_reason=? WHERE req_id=?",
                   (approver, reason, req_id))
        DB.commit()
        return get_req(req_id)


@app.post("/api/requests/{req_id}/cancel")
async def cancel(req_id: int, request: Request):
    b = await body_of(request)
    with LOCK:
        req = get_req(req_id)
        if s(b.get("user")) != req["user"]:
            raise Reject(403, "본인의 신청만 취소할 수 있습니다")
        if req["status"] != "신청":
            raise already_done()
        DB.execute("UPDATE lv_requests SET status='취소' WHERE req_id=?", (req_id,))
        DB.commit()
        return get_req(req_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
