import csv
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "leave.db"
SEED = BASE / "seed"

app = FastAPI()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect()
    conn.execute(
        "CREATE TABLE lv_users (user TEXT PRIMARY KEY, team TEXT, role TEXT, manager TEXT, leave_total INTEGER)"
    )
    conn.execute(
        "CREATE TABLE lv_requests (req_id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, type TEXT, start TEXT, end TEXT,"
        " days INTEGER, reason TEXT, status TEXT, approver TEXT, reject_reason TEXT)"
    )
    with open(SEED / "users.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            conn.execute(
                "INSERT INTO lv_users VALUES (?,?,?,?,?)",
                (r["user"], r["team"], r["role"], r["manager"] or "", int(r["leave_total"] or 0)),
            )
    with open(SEED / "requests.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            conn.execute(
                "INSERT INTO lv_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    int(r["req_id"]), r["user"], r["type"], r["start"], r["end"], int(r["days"] or 0),
                    r["reason"], r["status"], r["approver"] or "", r["reject_reason"] or "",
                ),
            )
    conn.commit()
    conn.close()


init_db()


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


def count_weekdays(s, e):
    n = 0
    d = s
    while d <= e:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def balance(conn, user):
    u = conn.execute("SELECT * FROM lv_users WHERE user=?", (user,)).fetchone()
    if not u:
        return None
    q = "SELECT COALESCE(SUM(days),0) FROM lv_requests WHERE user=? AND type='연차' AND status=?"
    used = conn.execute(q, (user, "승인")).fetchone()[0]
    pending = conn.execute(q, (user, "신청")).fetchone()[0]
    total = u["leave_total"]
    return {"total": total, "used": used, "pending": pending, "remaining": total - used - pending}


def get_req(conn, req_id):
    return dict(conn.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone())


@app.get("/api/users")
def users():
    conn = connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM lv_users ORDER BY rowid")]
    conn.close()
    return rows


@app.get("/api/balance")
def get_balance(user: str = ""):
    conn = connect()
    b = balance(conn, user)
    conn.close()
    if b is None:
        return err(404, "사용자를 찾을 수 없습니다")
    return b


@app.get("/api/requests")
def list_requests(user: str = None, approver: str = None):
    conn = connect()
    try:
        if user is not None:
            rows = conn.execute("SELECT * FROM lv_requests WHERE user=? ORDER BY req_id DESC", (user,)).fetchall()
        elif approver is not None:
            rows = conn.execute(
                "SELECT r.* FROM lv_requests r JOIN lv_users u ON u.user=r.user"
                " WHERE u.manager=? AND r.status='신청' ORDER BY r.req_id DESC",
                (approver,),
            ).fetchall()
        else:
            return err(400, "user 또는 approver 가 필요합니다")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/requests")
def create_request(body: dict):
    user = str(body.get("user") or "").strip()
    typ = str(body.get("type") or "").strip()
    start = str(body.get("start") or "").strip()
    end = str(body.get("end") or "").strip()
    reason = str(body.get("reason") or "").strip()
    if not (user and typ and start and end and reason):
        return err(400, "모든 항목을 입력하세요")
    if typ not in ("연차", "출장"):
        return err(400, "종류는 연차 또는 출장이어야 합니다")
    try:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
    except ValueError:
        return err(400, "날짜 형식이 올바르지 않습니다")
    if e < s:
        return err(400, "종료일이 시작일보다 빠릅니다")
    days = count_weekdays(s, e)
    if days == 0:
        return err(400, "주말만 선택할 수 없습니다")
    conn = connect()
    try:
        b = balance(conn, user)
        if b is None:
            return err(400, "사용자를 찾을 수 없습니다")
        if conn.execute(
            "SELECT 1 FROM lv_requests WHERE user=? AND status IN ('신청','승인') AND start<=? AND end>=?",
            (user, end, start),
        ).fetchone():
            return err(409, "이미 신청한 기간과 겹칩니다")
        if typ == "연차" and days > b["remaining"]:
            return err(400, "잔여 연차가 부족합니다")
        cur = conn.execute(
            "INSERT INTO lv_requests (user,type,start,end,days,reason,status,approver,reject_reason)"
            " VALUES (?,?,?,?,?,?,'신청','','')",
            (user, typ, start, end, days, reason),
        )
        conn.commit()
        return JSONResponse(get_req(conn, cur.lastrowid), status_code=201)
    finally:
        conn.close()


def decide(req_id, approver, new_status, reason=""):
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
        if not r:
            return err(404, "신청을 찾을 수 없습니다")
        u = conn.execute("SELECT * FROM lv_users WHERE user=?", (r["user"],)).fetchone()
        if not approver or not u or not u["manager"] or approver != u["manager"] or approver == r["user"]:
            return err(403, "결재 권한이 없습니다")
        if r["status"] != "신청":
            return err(409, "이미 처리된 신청입니다")
        if new_status == "반려" and not reason:
            return err(400, "반려 사유를 입력하세요")
        conn.execute(
            "UPDATE lv_requests SET status=?, approver=?, reject_reason=? WHERE req_id=?",
            (new_status, approver, reason, req_id),
        )
        conn.commit()
        return get_req(conn, req_id)
    finally:
        conn.close()


@app.post("/api/requests/{req_id}/approve")
def approve(req_id: int, body: dict):
    return decide(req_id, str(body.get("approver") or "").strip(), "승인")


@app.post("/api/requests/{req_id}/reject")
def reject(req_id: int, body: dict):
    return decide(req_id, str(body.get("approver") or "").strip(), "반려", str(body.get("reason") or "").strip())


@app.post("/api/requests/{req_id}/cancel")
def cancel(req_id: int, body: dict):
    user = str(body.get("user") or "").strip()
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
        if not r:
            return err(404, "신청을 찾을 수 없습니다")
        if r["user"] != user:
            return err(403, "본인의 신청만 취소할 수 있습니다")
        if r["status"] != "신청":
            return err(409, "이미 처리된 신청입니다")
        conn.execute("UPDATE lv_requests SET status='취소' WHERE req_id=?", (req_id,))
        conn.commit()
        return get_req(conn, req_id)
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
