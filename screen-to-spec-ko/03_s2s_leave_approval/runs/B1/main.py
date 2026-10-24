import csv
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

BASE = Path(__file__).parent
DB_PATH = BASE / "leave.db"
SEED = BASE / "seed"

TYPES = ("연차", "출장")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    with closing(connect()) as db:
        db.execute(
            "CREATE TABLE lv_users (user TEXT PRIMARY KEY, team TEXT, role TEXT,"
            " manager TEXT, leave_total INTEGER)"
        )
        db.execute(
            "CREATE TABLE lv_requests (req_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " user TEXT, type TEXT, start TEXT, end TEXT, days INTEGER, reason TEXT,"
            " status TEXT, approver TEXT, reject_reason TEXT)"
        )
        for r in read_csv("users.csv"):
            db.execute(
                "INSERT INTO lv_users VALUES (?,?,?,?,?)",
                (r["user"], r["team"], r["role"], r["manager"] or "", int(r["leave_total"])),
            )
        for r in read_csv("requests.csv"):
            db.execute(
                "INSERT INTO lv_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    int(r["req_id"]), r["user"], r["type"], r["start"], r["end"],
                    int(r["days"]), r["reason"], r["status"],
                    r["approver"] or "", r["reject_reason"] or "",
                ),
            )
        db.commit()


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return JSONResponse({"detail": "요청 값이 올바르지 않습니다"}, status_code=400)


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise Reject(400, "요청 값이 올바르지 않습니다")
    if not isinstance(data, dict):
        raise Reject(400, "요청 값이 올바르지 않습니다")
    return data


def text(data, key):
    v = data.get(key)
    return v.strip() if isinstance(v, str) else ""


def parse_date(s):
    try:
        return date.fromisoformat(s) if len(s) == 10 else None
    except ValueError:
        return None


def weekdays(start, end):
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def balance_of(db, user):
    u = db.execute("SELECT * FROM lv_users WHERE user=?", (user,)).fetchone()
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")

    def total(status):
        return db.execute(
            "SELECT COALESCE(SUM(days),0) FROM lv_requests"
            " WHERE user=? AND type='연차' AND status=?",
            (user, status),
        ).fetchone()[0]

    used, pending = total("승인"), total("신청")
    return {
        "total": u["leave_total"],
        "used": used,
        "pending": pending,
        "remaining": u["leave_total"] - used - pending,
    }


def get_request(db, req_id):
    r = db.execute("SELECT * FROM lv_requests WHERE req_id=?", (req_id,)).fetchone()
    if not r:
        raise Reject(404, "신청을 찾을 수 없습니다")
    return r


def to_dict(r):
    return dict(r)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/users")
def users():
    with closing(connect()) as db:
        return [dict(r) for r in db.execute("SELECT * FROM lv_users ORDER BY rowid")]


@app.get("/api/balance")
def balance(user: str = ""):
    with closing(connect()) as db:
        return balance_of(db, user)


@app.get("/api/requests")
def list_requests(user: str = "", approver: str = ""):
    with closing(connect()) as db:
        if approver:
            rows = db.execute(
                "SELECT r.* FROM lv_requests r JOIN lv_users u ON u.user=r.user"
                " WHERE u.manager=? AND r.status='신청' ORDER BY r.req_id DESC",
                (approver,),
            )
        elif user:
            rows = db.execute(
                "SELECT * FROM lv_requests WHERE user=? ORDER BY req_id DESC", (user,)
            )
        else:
            raise Reject(400, "user 또는 approver 가 필요합니다")
        return [to_dict(r) for r in rows]


@app.post("/api/requests", status_code=201)
async def create_request(request: Request):
    data = await body_of(request)
    user, typ = text(data, "user"), text(data, "type")
    start_s, end_s, reason = text(data, "start"), text(data, "end"), text(data, "reason")
    if not (user and typ and start_s and end_s and reason):
        raise Reject(400, "모든 항목을 입력하세요")
    if typ not in TYPES:
        raise Reject(400, "종류는 연차 또는 출장이어야 합니다")
    start, end = parse_date(start_s), parse_date(end_s)
    if not start or not end:
        raise Reject(400, "날짜는 YYYY-MM-DD 형식이어야 합니다")
    if end < start:
        raise Reject(400, "종료일이 시작일보다 빠릅니다")
    days = weekdays(start, end)
    if days == 0:
        raise Reject(400, "주말만 선택할 수 없습니다")
    with closing(connect()) as db:
        bal = balance_of(db, user)
        if typ == "연차" and days > bal["remaining"]:
            raise Reject(400, "잔여 연차가 부족합니다")
        clash = db.execute(
            "SELECT 1 FROM lv_requests WHERE user=? AND status IN ('신청','승인')"
            " AND start<=? AND end>=?",
            (user, end_s, start_s),
        ).fetchone()
        if clash:
            raise Reject(409, "이미 신청한 기간과 겹칩니다")
        cur = db.execute(
            "INSERT INTO lv_requests (user,type,start,end,days,reason,status,approver,reject_reason)"
            " VALUES (?,?,?,?,?,?,'신청','','')",
            (user, typ, start_s, end_s, days, reason),
        )
        db.commit()
        return to_dict(get_request(db, cur.lastrowid))


def decide(db, req_id, approver, status, reason=""):
    r = get_request(db, req_id)
    owner = db.execute("SELECT manager FROM lv_users WHERE user=?", (r["user"],)).fetchone()
    manager = owner["manager"] if owner else ""
    if not approver or not manager or approver != manager:
        raise Reject(403, "결재 권한이 없습니다")
    if status == "반려" and not reason:
        raise Reject(400, "반려 사유를 입력하세요")
    if r["status"] != "신청":
        raise Reject(409, "이미 처리된 신청입니다")
    db.execute(
        "UPDATE lv_requests SET status=?, approver=?, reject_reason=? WHERE req_id=?",
        (status, approver, reason, req_id),
    )
    db.commit()
    return to_dict(get_request(db, req_id))


@app.post("/api/requests/{req_id}/approve")
async def approve(req_id: int, request: Request):
    data = await body_of(request)
    with closing(connect()) as db:
        return decide(db, req_id, text(data, "approver"), "승인")


@app.post("/api/requests/{req_id}/reject")
async def reject(req_id: int, request: Request):
    data = await body_of(request)
    with closing(connect()) as db:
        return decide(db, req_id, text(data, "approver"), "반려", text(data, "reason"))


@app.post("/api/requests/{req_id}/cancel")
async def cancel(req_id: int, request: Request):
    data = await body_of(request)
    user = text(data, "user")
    with closing(connect()) as db:
        r = get_request(db, req_id)
        if not user or r["user"] != user:
            raise Reject(403, "본인의 신청만 취소할 수 있습니다")
        if r["status"] != "신청":
            raise Reject(409, "이미 처리된 신청입니다")
        db.execute("UPDATE lv_requests SET status='취소' WHERE req_id=?", (req_id,))
        db.commit()
        return to_dict(get_request(db, req_id))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
