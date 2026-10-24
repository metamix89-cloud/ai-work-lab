import csv
import os
import sqlite3
from datetime import date, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "leave.db")

app = FastAPI()


def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    c = conn()
    c.execute("CREATE TABLE lv_users (user TEXT PRIMARY KEY, team TEXT, role TEXT, manager TEXT, leave_total INTEGER)")
    c.execute("""CREATE TABLE lv_requests (req_id INTEGER PRIMARY KEY, user TEXT, type TEXT, start TEXT, end TEXT,
                 days INTEGER, reason TEXT, status TEXT, approver TEXT, reject_reason TEXT)""")
    with open(os.path.join(BASE, "seed", "users.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO lv_users VALUES (?,?,?,?,?)",
                      (r["user"], r["team"], r["role"], r["manager"] or "", int(r["leave_total"] or 0)))
    with open(os.path.join(BASE, "seed", "requests.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO lv_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (int(r["req_id"]), r["user"], r["type"], r["start"], r["end"], int(r["days"] or 0),
                       r["reason"], r["status"], r["approver"] or "", r["reject_reason"] or ""))
    c.commit()
    c.close()


init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


async def body_of(request: Request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def s(v):
    return v.strip() if isinstance(v, str) else ""


def parse_date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def weekdays(a, b):
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def calc_balance(c, user):
    u = c.execute("SELECT leave_total FROM lv_users WHERE user=?", (user,)).fetchone()
    if not u:
        return None
    def total(status):
        return c.execute("SELECT COALESCE(SUM(days),0) FROM lv_requests WHERE user=? AND type='연차' AND status=?",
                         (user, status)).fetchone()[0]
    used, pending = total("승인"), total("신청")
    return {"total": u["leave_total"], "used": used, "pending": pending,
            "remaining": u["leave_total"] - used - pending}


def row(c, req_id):
    r = c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
    return dict(r) if r else None


@app.get("/api/users")
def users():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT user, team, role, manager, leave_total FROM lv_users ORDER BY rowid")]
    finally:
        c.close()


@app.get("/api/balance")
def balance(user: str = ""):
    c = conn()
    try:
        b = calc_balance(c, user)
        return b if b else err(400, "알 수 없는 사용자입니다")
    finally:
        c.close()


@app.get("/api/requests")
def list_requests(user: str = "", approver: str = ""):
    c = conn()
    try:
        if approver:
            rows = c.execute("""SELECT r.* FROM lv_requests r JOIN lv_users u ON u.user=r.user
                                WHERE u.manager=? AND r.status='신청' ORDER BY r.req_id DESC""", (approver,))
        elif user:
            rows = c.execute("SELECT * FROM lv_requests WHERE user=? ORDER BY req_id DESC", (user,))
        else:
            return err(400, "user 또는 approver 가 필요합니다")
        return [dict(r) for r in rows]
    finally:
        c.close()


@app.post("/api/requests")
async def create_request(request: Request):
    b = await body_of(request)
    user, typ, start, end, reason = s(b.get("user")), s(b.get("type")), s(b.get("start")), s(b.get("end")), s(b.get("reason"))
    if not (user and typ and start and end and reason):
        return err(400, "빈 값이 있습니다")
    if typ not in ("연차", "출장"):
        return err(400, "종류는 연차 또는 출장이어야 합니다")
    a, z = parse_date(start), parse_date(end)
    if not a or not z:
        return err(400, "날짜 형식이 올바르지 않습니다")
    if z < a:
        return err(400, "종료일이 시작일보다 빠릅니다")
    days = weekdays(a, z)
    if days == 0:
        return err(400, "주말만 선택할 수 없습니다")
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        bal = calc_balance(c, user)
        if bal is None:
            return err(400, "알 수 없는 사용자입니다")
        if typ == "연차" and days > bal["remaining"]:
            return err(400, "잔여 연차가 부족합니다")
        overlap = c.execute("""SELECT 1 FROM lv_requests WHERE user=? AND status IN ('신청','승인')
                               AND start<=? AND end>=? LIMIT 1""", (user, end, start)).fetchone()
        if overlap:
            return err(409, "이미 신청한 기간과 겹칩니다")
        nid = c.execute("SELECT COALESCE(MAX(req_id),0)+1 FROM lv_requests").fetchone()[0]
        c.execute("INSERT INTO lv_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (nid, user, typ, start, end, days, reason, "신청", "", ""))
        c.commit()
        return JSONResponse(row(c, nid), status_code=201)
    finally:
        c.close()


def decide(req_id, approver, new_status, reason=""):
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        r = row(c, req_id)
        if not r:
            return err(404, "신청을 찾을 수 없습니다")
        u = c.execute("SELECT manager FROM lv_users WHERE user=?", (r["user"],)).fetchone()
        mgr = u["manager"] if u else ""
        if not approver or not mgr or approver != mgr:
            return err(403, "결재 권한이 없습니다")
        if new_status == "반려" and not reason:
            return err(400, "반려 사유를 입력하세요")
        if r["status"] != "신청":
            return err(409, "이미 처리된 신청입니다")
        c.execute("UPDATE lv_requests SET status=?, approver=?, reject_reason=? WHERE req_id=?",
                  (new_status, approver, reason, req_id))
        c.commit()
        return row(c, req_id)
    finally:
        c.close()


@app.post("/api/requests/{req_id}/approve")
async def approve(req_id: int, request: Request):
    b = await body_of(request)
    return decide(req_id, s(b.get("approver")), "승인")


@app.post("/api/requests/{req_id}/reject")
async def reject(req_id: int, request: Request):
    b = await body_of(request)
    return decide(req_id, s(b.get("approver")), "반려", s(b.get("reason")))


@app.post("/api/requests/{req_id}/cancel")
async def cancel(req_id: int, request: Request):
    b = await body_of(request)
    user = s(b.get("user"))
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        r = row(c, req_id)
        if not r:
            return err(404, "신청을 찾을 수 없습니다")
        if not user or r["user"] != user:
            return err(403, "본인의 신청만 취소할 수 있습니다")
        if r["status"] != "신청":
            return err(409, "이미 처리된 신청입니다")
        c.execute("UPDATE lv_requests SET status='취소' WHERE req_id=?", (req_id,))
        c.commit()
        return row(c, req_id)
    finally:
        c.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
