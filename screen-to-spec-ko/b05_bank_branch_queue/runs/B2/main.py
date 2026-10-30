import csv
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(ROOT, "seed")
STATIC = os.path.join(ROOT, "static")
DB_PATH = os.path.join(ROOT, "bank.db")

FMT = "%Y-%m-%d %H:%M"
SERVICES = ("deposit", "loan", "fx")
PHONE_RE = re.compile(r"^01\d-\d{3,4}-\d{4}$")
HOLD_MINUTES = 3
PRIORITY_MINUTES = 10

lock = threading.RLock()
db = None


class ApiError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def parse_time(s):
    return datetime.strptime(s, FMT)


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_priority(reserved_at, arrived_at):
    if not reserved_at or not arrived_at:
        return 0
    diff = abs(parse_time(arrived_at) - parse_time(reserved_at))
    return 1 if diff <= timedelta(minutes=PRIORITY_MINUTES) else 0


def init_db():
    global db
    if db is not None:
        db.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except FileNotFoundError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE bk_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT, counter_id TEXT);
        CREATE TABLE bk_counters (counter_id TEXT PRIMARY KEY, name TEXT, service TEXT);
        CREATE TABLE bk_tickets (
            ticket_id TEXT PRIMARY KEY, number INTEGER, name TEXT, phone TEXT, account TEXT,
            service TEXT, reserved_at TEXT, arrived_at TEXT, status TEXT, counter_id TEXT,
            called_at TEXT, priority INTEGER DEFAULT 0
        );
        """
    )
    for r in read_csv("users.csv"):
        db.execute("INSERT INTO bk_users VALUES (?,?,?,?)",
                   (r["user_id"], r["name"], r["role"], r["counter_id"] or None))
    for r in read_csv("counters.csv"):
        db.execute("INSERT INTO bk_counters VALUES (?,?,?)", (r["counter_id"], r["name"], r["service"]))
    for r in read_csv("tickets.csv"):
        reserved = r["reserved_at"] or None
        arrived = r["arrived_at"] or None
        db.execute(
            "INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["ticket_id"], int(r["number"]), r["name"], r["phone"], r["account"], r["service"],
             reserved, arrived, r["status"], r["counter_id"] or None, r["called_at"] or None,
             is_priority(reserved, arrived)),
        )
    db.commit()


def mask_name(name):
    n = len(name)
    if n <= 1:
        return "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


def q(sql, args=()):
    return db.execute(sql, args).fetchall()


def q1(sql, args=()):
    return db.execute(sql, args).fetchone()


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def need_user(value):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "사용자를 확인하세요")
    return value


def get_user(user_id):
    u = q1("SELECT * FROM bk_users WHERE user_id=?", (user_id,))
    if u is None:
        raise ApiError(404, "없는 사용자입니다")
    return u


def get_counter(counter_id):
    c = q1("SELECT * FROM bk_counters WHERE counter_id=?", (counter_id,))
    if c is None:
        raise ApiError(404, "없는 창구입니다")
    return c


def get_ticket(ticket_id):
    t = q1("SELECT * FROM bk_tickets WHERE ticket_id=?", (ticket_id,))
    if t is None:
        raise ApiError(404, "없는 번호표입니다")
    return t


def now_of(body):
    at = body.get("at")
    if at is None or at == "":
        return datetime.now().replace(second=0, microsecond=0)
    try:
        return parse_time(at)
    except Exception:
        raise ApiError(400, "시각을 확인하세요")


def queue_rows(service):
    return q(
        "SELECT * FROM bk_tickets WHERE status='waiting' AND service=? "
        "ORDER BY priority DESC, arrived_at ASC, number ASC",
        (service,),
    )


def require_counter_staff(user, counter_id):
    if user["role"] != "teller" or user["counter_id"] != counter_id:
        raise ApiError(403, "자기 창구만 할 수 있습니다")


def require_ticket_owner(user, ticket):
    if user["role"] != "teller" or ticket["counter_id"] is None or ticket["counter_id"] != user["counter_id"]:
        raise ApiError(403, "자기 창구 고객이 아닙니다")


app = FastAPI()


@app.exception_handler(ApiError)
async def api_error_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


# rebuild the DB from seed/ every time the server starts
init_db()


@app.get("/")
def index_page():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/board")
def board_page():
    return FileResponse(os.path.join(STATIC, "board.html"))


@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in q("SELECT user_id,name,role,counter_id FROM bk_users ORDER BY rowid")]


@app.get("/api/board")
def board():
    with lock:
        rows = q("SELECT * FROM bk_tickets WHERE status IN ('called','waiting') ORDER BY number ASC")
        return {
            "serving": [{"number": r["number"], "masked_name": mask_name(r["name"]), "counter_id": r["counter_id"]}
                        for r in rows if r["status"] == "called"],
            "waiting": [{"number": r["number"], "masked_name": mask_name(r["name"])}
                        for r in rows if r["status"] == "waiting"],
        }


@app.post("/api/tickets", status_code=201)
async def create_ticket(request: Request):
    b = await body_of(request)
    name, phone, account = b.get("name"), b.get("phone"), b.get("account")
    service, reserved_at = b.get("service"), b.get("reserved_at")
    if not isinstance(name, str) or not name.strip():
        raise ApiError(400, "이름을 확인하세요")
    if not isinstance(phone, str) or not PHONE_RE.match(phone):
        raise ApiError(400, "전화번호 형식을 확인하세요")
    if not isinstance(account, str) or not account.strip():
        raise ApiError(400, "계좌번호를 확인하세요")
    if service not in SERVICES:
        raise ApiError(400, "업무 종류를 확인하세요")
    if reserved_at is not None and reserved_at != "":
        try:
            parse_time(reserved_at)
        except Exception:
            raise ApiError(400, "예약 시각을 확인하세요")
    else:
        reserved_at = None
    now = now_of(b)
    with lock:
        number = (q1("SELECT MAX(number) m FROM bk_tickets")["m"] or 100) + 1
        ticket_id = f"K-{number}"
        if reserved_at:
            status, arrived = "reserved", None
        else:
            status, arrived = "waiting", now.strftime(FMT)
        db.execute(
            "INSERT INTO bk_tickets (ticket_id,number,name,phone,account,service,reserved_at,arrived_at,status,priority) "
            "VALUES (?,?,?,?,?,?,?,?,?,0)",
            (ticket_id, number, name.strip(), phone, account.strip(), service, reserved_at, arrived, status),
        )
        db.commit()
    return {"ticket_id": ticket_id, "number": number, "status": status}


@app.post("/api/tickets/{ticket_id}/checkin")
async def checkin(ticket_id: str, request: Request):
    b = await body_of(request)
    now = now_of(b)
    with lock:
        t = get_ticket(ticket_id)
        if t["status"] != "reserved":
            raise ApiError(409, "예약 상태가 아닙니다")
        arrived = now.strftime(FMT)
        pr = is_priority(t["reserved_at"], arrived)
        db.execute("UPDATE bk_tickets SET status='waiting', arrived_at=?, priority=? WHERE ticket_id=?",
                   (arrived, pr, ticket_id))
        db.commit()
        return {"ticket_id": ticket_id, "number": t["number"], "status": "waiting", "priority": bool(pr)}


@app.get("/api/counters/{counter_id}/queue")
def counter_queue(counter_id: str, viewer: str = None):
    with lock:
        need_user(viewer)
        c = get_counter(counter_id)
        u = get_user(viewer)
        require_counter_staff(u, counter_id)
        return [{"ticket_id": r["ticket_id"], "number": r["number"], "masked_name": mask_name(r["name"]),
                 "service": r["service"], "priority": bool(r["priority"])}
                for r in queue_rows(c["service"])]


@app.post("/api/counters/{counter_id}/next")
async def counter_next(counter_id: str, request: Request):
    b = await body_of(request)
    user_id = need_user(b.get("user"))
    now = now_of(b)
    with lock:
        c = get_counter(counter_id)
        u = get_user(user_id)
        require_counter_staff(u, counter_id)
        current = q1("SELECT * FROM bk_tickets WHERE status='called' AND counter_id=?", (counter_id,))
        if current is not None:
            if now - parse_time(current["called_at"]) < timedelta(minutes=HOLD_MINUTES):
                raise ApiError(409, "호출 뒤 3분이 지나야 다음 번호를 부를 수 있습니다")
            db.execute("UPDATE bk_tickets SET status='held' WHERE ticket_id=?", (current["ticket_id"],))
        held = current["ticket_id"] if current is not None else None
        rows = queue_rows(c["service"])
        called = None
        if rows:
            n = rows[0]
            db.execute("UPDATE bk_tickets SET status='called', counter_id=?, called_at=? WHERE ticket_id=?",
                       (counter_id, now.strftime(FMT), n["ticket_id"]))
            called = {"ticket_id": n["ticket_id"], "number": n["number"],
                      "masked_name": mask_name(n["name"]), "counter_id": counter_id}
        db.commit()
        return {"called": called, "held": held}


@app.post("/api/tickets/{ticket_id}/complete")
async def complete(ticket_id: str, request: Request):
    b = await body_of(request)
    user_id = need_user(b.get("user"))
    now_of(b)
    with lock:
        t = get_ticket(ticket_id)
        u = get_user(user_id)
        require_ticket_owner(u, t)
        if t["status"] != "called":
            raise ApiError(409, "호출 중인 고객이 아닙니다")
        db.execute("UPDATE bk_tickets SET status='done' WHERE ticket_id=?", (ticket_id,))
        db.commit()
        return {"ticket_id": ticket_id, "status": "done"}


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str, viewer: str = None):
    with lock:
        need_user(viewer)
        t = get_ticket(ticket_id)
        u = get_user(viewer)
        require_ticket_owner(u, t)
        return {"ticket_id": t["ticket_id"], "number": t["number"], "name": t["name"], "phone": t["phone"],
                "account_last4": t["account"][-4:], "service": t["service"], "status": t["status"],
                "counter_id": t["counter_id"]}


@app.get("/api/manager/summary")
def manager_summary(viewer: str = None):
    with lock:
        need_user(viewer)
        u = get_user(viewer)
        if u["role"] != "manager":
            raise ApiError(403, "지점장만 볼 수 있습니다")
        waiting = {s: 0 for s in SERVICES}
        for r in q("SELECT service, COUNT(*) n FROM bk_tickets WHERE status='waiting' GROUP BY service"):
            if r["service"] in waiting:
                waiting[r["service"]] = r["n"]
        count = lambda st: q1("SELECT COUNT(*) n FROM bk_tickets WHERE status=?", (st,))["n"]
        counters = []
        for c in q("SELECT * FROM bk_counters ORDER BY rowid"):
            cur = q1("SELECT number FROM bk_tickets WHERE status='called' AND counter_id=?", (c["counter_id"],))
            counters.append({"counter_id": c["counter_id"], "service": c["service"],
                             "number": cur["number"] if cur else None})
        return {"waiting": waiting, "held": count("held"), "done": count("done"), "counters": counters}
