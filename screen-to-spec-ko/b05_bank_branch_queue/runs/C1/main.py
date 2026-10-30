import csv
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
STATIC = os.path.join(BASE, "static")
DB_PATH = os.path.join(BASE, "bank.db")
FMT = "%Y-%m-%d %H:%M"
SERVICES = ("deposit", "loan", "fx")
PHONE_RE = re.compile(r"^01\d-\d{3,4}-\d{4}$")

lock = threading.RLock()
db = None


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global db
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE bk_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT, counter_id TEXT);
        CREATE TABLE bk_counters (counter_id TEXT PRIMARY KEY, name TEXT, service TEXT);
        CREATE TABLE bk_tickets (ticket_id TEXT PRIMARY KEY, number INTEGER, name TEXT, phone TEXT,
            account TEXT, service TEXT, reserved_at TEXT, arrived_at TEXT, status TEXT,
            counter_id TEXT, called_at TEXT);
        """
    )
    for r in read_csv("users.csv"):
        db.execute("INSERT INTO bk_users VALUES (?,?,?,?)",
                   (r["user_id"], r["name"], r["role"], r["counter_id"] or ""))
    for r in read_csv("counters.csv"):
        db.execute("INSERT INTO bk_counters VALUES (?,?,?)", (r["counter_id"], r["name"], r["service"]))
    for r in read_csv("tickets.csv"):
        db.execute("INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (r["ticket_id"], int(r["number"]), r["name"], r["phone"], r["account"], r["service"],
                    r["reserved_at"], r["arrived_at"], r["status"], r["counter_id"], r["called_at"]))
    db.commit()


init_db()
app = FastAPI()


@app.exception_handler(Reject)
async def on_reject(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


@app.exception_handler(StarletteHTTPException)
async def on_http(request, exc):
    return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def on_validation(request, exc):
    return JSONResponse({"detail": "요청을 확인하세요"}, status_code=400)


# ── 도우미 ──
def mask(name):
    n = len(name)
    if n <= 1:
        return "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


def parse_time(s):
    try:
        return datetime.strptime(s, FMT)
    except (TypeError, ValueError):
        return None


async def body_of(request):
    try:
        b = json.loads((await request.body()).decode("utf-8") or "null")
    except ValueError:
        return {}
    return b if isinstance(b, dict) else {}


def now_of(body):
    """본문의 at 이 먼저, 없으면 서버 시각"""
    at = body.get("at")
    if at is None or at == "":
        return datetime.now().replace(second=0, microsecond=0)
    t = parse_time(at) if isinstance(at, str) else None
    if t is None:
        raise Reject(400, "시각을 확인하세요")
    return t


def text_of(v):
    return v.strip() if isinstance(v, str) else ""


def need_user(v):
    u = text_of(v)
    if not u:
        raise Reject(400, "사용자를 확인하세요")
    return u


def find_user(uid):
    r = db.execute("SELECT * FROM bk_users WHERE user_id=?", (uid,)).fetchone()
    if r is None:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return r


def find_counter(cid):
    r = db.execute("SELECT * FROM bk_counters WHERE counter_id=?", (cid,)).fetchone()
    if r is None:
        raise Reject(404, "창구를 찾을 수 없습니다")
    return r


def find_ticket(tid):
    r = db.execute("SELECT * FROM bk_tickets WHERE ticket_id=?", (tid,)).fetchone()
    if r is None:
        raise Reject(404, "번호표를 찾을 수 없습니다")
    return r


def is_priority(t):
    res, arr = parse_time(t["reserved_at"]), parse_time(t["arrived_at"])
    return bool(res and arr and abs(arr - res) <= timedelta(minutes=10))


def waiting_line(service):
    rows = db.execute("SELECT * FROM bk_tickets WHERE status='waiting' AND service=?", (service,)).fetchall()
    return sorted(rows, key=lambda t: (not is_priority(t), t["arrived_at"], t["number"]))


def own_counter(user, counter_id):
    if user["role"] != "teller" or user["counter_id"] != counter_id:
        raise Reject(403, "자기 창구만 할 수 있습니다")


def own_ticket(user, ticket):
    if user["role"] != "teller" or not ticket["counter_id"] or user["counter_id"] != ticket["counter_id"]:
        raise Reject(403, "자기 창구 고객이 아닙니다")


# ── 화면 ──
@app.get("/")
def index_page():
    return FileResponse(os.path.join(STATIC, "index.html"), media_type="text/html; charset=utf-8")


@app.get("/board")
def board_page():
    return FileResponse(os.path.join(STATIC, "board.html"), media_type="text/html; charset=utf-8")


# ── API ──
@app.get("/api/users")
def users():
    with lock:
        rows = db.execute("SELECT user_id,name,role,counter_id FROM bk_users ORDER BY rowid").fetchall()
    return [{"user_id": r["user_id"], "name": r["name"], "role": r["role"], "counter_id": r["counter_id"]} for r in rows]


@app.get("/api/board")
def board():
    with lock:
        rows = db.execute("SELECT * FROM bk_tickets WHERE status IN ('called','waiting') ORDER BY number").fetchall()
    return {
        "serving": [{"number": r["number"], "masked_name": mask(r["name"]), "counter_id": r["counter_id"]}
                    for r in rows if r["status"] == "called"],
        "waiting": [{"number": r["number"], "masked_name": mask(r["name"])}
                    for r in rows if r["status"] == "waiting"],
    }


@app.post("/api/tickets", status_code=201)
async def create_ticket(request: Request):
    b = await body_of(request)
    if not text_of(b.get("name")):
        raise Reject(400, "이름을 확인하세요")
    if not isinstance(b.get("phone"), str) or not PHONE_RE.match(b["phone"].strip()):
        raise Reject(400, "전화번호 형식을 확인하세요")
    if not text_of(b.get("account")):
        raise Reject(400, "계좌번호를 확인하세요")
    if b.get("service") not in SERVICES:
        raise Reject(400, "업무 종류를 확인하세요")
    reserved = b.get("reserved_at")
    reserved = None if reserved in (None, "") else reserved
    if reserved is not None and (not isinstance(reserved, str) or parse_time(reserved) is None):
        raise Reject(400, "예약 시각을 확인하세요")
    now = now_of(b)
    with lock:
        number = (db.execute("SELECT MAX(number) FROM bk_tickets").fetchone()[0] or 100) + 1
        ids = [int(m.group(1)) for (i,) in db.execute("SELECT ticket_id FROM bk_tickets")
               for m in [re.match(r"^K-(\d+)$", i)] if m]
        tid = "K-%02d" % ((max(ids) if ids else 0) + 1)
        status = "reserved" if reserved else "waiting"
        db.execute("INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (tid, number, b["name"].strip(), b["phone"].strip(), b["account"].strip(), b["service"],
                    reserved or "", "" if reserved else now.strftime(FMT), status, "", ""))
        db.commit()
    return {"ticket_id": tid, "number": number, "status": status}


@app.post("/api/tickets/{ticket_id}/checkin")
async def checkin(ticket_id: str, request: Request):
    b = await body_of(request)
    now = now_of(b)
    with lock:
        t = find_ticket(ticket_id)
        if t["status"] != "reserved":
            raise Reject(409, "예약 상태가 아닙니다")
        db.execute("UPDATE bk_tickets SET status='waiting', arrived_at=? WHERE ticket_id=?",
                   (now.strftime(FMT), ticket_id))
        db.commit()
        t = find_ticket(ticket_id)
        return {"ticket_id": t["ticket_id"], "number": t["number"], "status": "waiting", "priority": is_priority(t)}


@app.get("/api/counters/{counter_id}/queue")
def queue(counter_id: str, viewer: str = None):
    uid = need_user(viewer)
    with lock:
        c = find_counter(counter_id)
        u = find_user(uid)
        own_counter(u, counter_id)
        return [{"ticket_id": t["ticket_id"], "number": t["number"], "masked_name": mask(t["name"]),
                 "service": t["service"], "priority": is_priority(t)} for t in waiting_line(c["service"])]


@app.post("/api/counters/{counter_id}/next")
async def next_call(counter_id: str, request: Request):
    b = await body_of(request)
    uid = need_user(b.get("user"))
    now = now_of(b)
    with lock:
        c = find_counter(counter_id)
        u = find_user(uid)
        own_counter(u, counter_id)
        front = db.execute("SELECT * FROM bk_tickets WHERE status='called' AND counter_id=? "
                           "ORDER BY called_at DESC, number DESC", (counter_id,)).fetchone()
        held = None
        if front is not None:
            called_at = parse_time(front["called_at"])
            if called_at is not None and now - called_at < timedelta(minutes=3):
                raise Reject(409, "호출 뒤 3분이 지나야 다음 번호를 부를 수 있습니다")
            db.execute("UPDATE bk_tickets SET status='held' WHERE ticket_id=?", (front["ticket_id"],))
            held = front["ticket_id"]
        line = waiting_line(c["service"])
        called = None
        if line:
            t = line[0]
            db.execute("UPDATE bk_tickets SET status='called', counter_id=?, called_at=? WHERE ticket_id=?",
                       (counter_id, now.strftime(FMT), t["ticket_id"]))
            called = {"ticket_id": t["ticket_id"], "number": t["number"], "masked_name": mask(t["name"]),
                      "counter_id": counter_id}
        db.commit()
    return {"called": called, "held": held}


@app.post("/api/tickets/{ticket_id}/complete")
async def complete(ticket_id: str, request: Request):
    b = await body_of(request)
    uid = need_user(b.get("user"))
    now_of(b)
    with lock:
        t = find_ticket(ticket_id)
        u = find_user(uid)
        own_ticket(u, t)
        if t["status"] != "called":
            raise Reject(409, "호출 중인 고객이 아닙니다")
        db.execute("UPDATE bk_tickets SET status='done' WHERE ticket_id=?", (ticket_id,))
        db.commit()
    return {"ticket_id": ticket_id, "status": "done"}


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str, viewer: str = None):
    uid = need_user(viewer)
    with lock:
        t = find_ticket(ticket_id)
        u = find_user(uid)
        own_ticket(u, t)
    return {"ticket_id": t["ticket_id"], "number": t["number"], "name": t["name"], "phone": t["phone"],
            "account_last4": t["account"][-4:], "service": t["service"], "status": t["status"],
            "counter_id": t["counter_id"]}


@app.get("/api/manager/summary")
def manager_summary(viewer: str = None):
    uid = need_user(viewer)
    with lock:
        u = find_user(uid)
        if u["role"] != "manager":
            raise Reject(403, "지점장만 볼 수 있습니다")

        def count(st, sv=None):
            if sv:
                return db.execute("SELECT COUNT(*) FROM bk_tickets WHERE status=? AND service=?", (st, sv)).fetchone()[0]
            return db.execute("SELECT COUNT(*) FROM bk_tickets WHERE status=?", (st,)).fetchone()[0]

        counters = []
        for c in db.execute("SELECT * FROM bk_counters ORDER BY rowid").fetchall():
            r = db.execute("SELECT number FROM bk_tickets WHERE status='called' AND counter_id=? "
                           "ORDER BY called_at DESC, number DESC", (c["counter_id"],)).fetchone()
            counters.append({"counter_id": c["counter_id"], "service": c["service"],
                             "number": r["number"] if r else None})
        return {"waiting": {s: count("waiting", s) for s in SERVICES}, "held": count("held"),
                "done": count("done"), "counters": counters}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
