import csv
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB = BASE / "leave.db"
app = FastAPI()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    if DB.exists():
        DB.unlink()
    c = conn()
    c.execute("CREATE TABLE lv_users (user TEXT PRIMARY KEY, team TEXT, role TEXT, manager TEXT, leave_total INTEGER)")
    c.execute("""CREATE TABLE lv_requests (req_id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, type TEXT,
        start TEXT, end TEXT, days INTEGER, reason TEXT, status TEXT, approver TEXT, reject_reason TEXT)""")
    with open(BASE / "seed" / "users.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO lv_users VALUES (?,?,?,?,?)",
                      (r["user"], r["team"], r["role"], r["manager"] or "", int(r["leave_total"])))
    with open(BASE / "seed" / "requests.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO lv_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (int(r["req_id"]), r["user"], r["type"], r["start"], r["end"], int(r["days"]),
                       r["reason"], r["status"], r["approver"], r["reject_reason"]))
    c.commit()
    c.close()


init_db()


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


def weekdays(s, e):
    n, d = 0, s
    while d <= e:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def balance(c, user):
    u = c.execute("SELECT * FROM lv_users WHERE user=?", (user,)).fetchone()
    if not u:
        return None
    q = "SELECT COALESCE(SUM(days),0) FROM lv_requests WHERE user=? AND type='연차' AND status=?"
    used = c.execute(q, (user, "승인")).fetchone()[0]
    pending = c.execute(q, (user, "신청")).fetchone()[0]
    total = u["leave_total"]
    return {"total": total, "used": used, "pending": pending, "remaining": total - used - pending}


async def body(request):
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


@app.get("/api/users")
def users():
    c = conn()
    out = [dict(r) for r in c.execute("SELECT * FROM lv_users ORDER BY rowid")]
    c.close()
    return out


@app.get("/api/balance")
def get_balance(user: str = ""):
    c = conn()
    b = balance(c, user)
    c.close()
    return b if b else err(404, "사용자를 찾을 수 없습니다")


@app.get("/api/requests")
def list_requests(user: str = "", approver: str = ""):
    c = conn()
    if approver:
        rows = c.execute("""SELECT r.* FROM lv_requests r JOIN lv_users u ON u.user=r.user
            WHERE u.manager=? AND r.status='신청' ORDER BY r.req_id DESC""", (approver,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM lv_requests WHERE user=? ORDER BY req_id DESC", (user,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@app.post("/api/requests")
async def create(request: Request):
    b = await body(request)
    user, typ = str(b.get("user") or "").strip(), str(b.get("type") or "").strip()
    start, end = str(b.get("start") or "").strip(), str(b.get("end") or "").strip()
    reason = str(b.get("reason") or "").strip()
    if not (user and typ and start and end and reason):
        return err(400, "모든 항목을 입력하세요")
    if typ not in ("연차", "출장"):
        return err(400, "종류는 연차 또는 출장이어야 합니다")
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return err(400, "날짜 형식이 올바르지 않습니다")
    if e < s:
        return err(400, "종료일이 시작일보다 빠릅니다")
    days = weekdays(s, e)
    if days == 0:
        return err(400, "주말만 선택할 수 없습니다")
    c = conn()
    try:
        bal = balance(c, user)
        if bal is None:
            return err(400, "사용자를 찾을 수 없습니다")
        if typ == "연차" and days > bal["remaining"]:
            return err(400, "잔여 연차가 부족합니다")
        hit = c.execute("""SELECT 1 FROM lv_requests WHERE user=? AND status IN ('신청','승인')
            AND start<=? AND end>=?""", (user, end, start)).fetchone()
        if hit:
            return err(409, "이미 신청한 기간과 겹칩니다")
        cur = c.execute("""INSERT INTO lv_requests (user,type,start,end,days,reason,status,approver,reject_reason)
            VALUES (?,?,?,?,?,?,'신청','','')""", (user, typ, start, end, days, reason))
        c.commit()
        r = c.execute("SELECT * FROM lv_requests WHERE req_id=?", (cur.lastrowid,)).fetchone()
        return JSONResponse(dict(r), status_code=201)
    finally:
        c.close()


def decide(req_id, approver, new_status, reason=None):
    c = conn()
    try:
        r = c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
        if not r:
            return err(404, "신청을 찾을 수 없습니다")
        u = c.execute("SELECT manager FROM lv_users WHERE user=?", (r["user"],)).fetchone()
        if not approver or not u or not u["manager"] or u["manager"] != approver or approver == r["user"]:
            return err(403, "결재 권한이 없습니다")
        if r["status"] != "신청":
            return err(409, "이미 처리된 신청입니다")
        if new_status == "반려" and not reason:
            return err(400, "반려 사유를 입력하세요")
        c.execute("UPDATE lv_requests SET status=?, approver=?, reject_reason=? WHERE req_id=?",
                  (new_status, approver, reason or "", req_id))
        c.commit()
        return dict(c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone())
    finally:
        c.close()


@app.post("/api/requests/{req_id}/approve")
async def approve(req_id: int, request: Request):
    b = await body(request)
    return decide(req_id, str(b.get("approver") or "").strip(), "승인")


@app.post("/api/requests/{req_id}/reject")
async def reject(req_id: int, request: Request):
    b = await body(request)
    return decide(req_id, str(b.get("approver") or "").strip(), "반려", str(b.get("reason") or "").strip())


@app.post("/api/requests/{req_id}/cancel")
async def cancel(req_id: int, request: Request):
    b = await body(request)
    user = str(b.get("user") or "").strip()
    c = conn()
    try:
        r = c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
        if not r:
            return err(404, "신청을 찾을 수 없습니다")
        if r["user"] != user:
            return err(403, "본인의 신청만 취소할 수 있습니다")
        if r["status"] != "신청":
            return err(409, "이미 처리된 신청입니다")
        c.execute("UPDATE lv_requests SET status='취소' WHERE req_id=?", (req_id,))
        c.commit()
        return dict(c.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone())
    finally:
        c.close()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
