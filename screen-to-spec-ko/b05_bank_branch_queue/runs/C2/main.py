# -*- coding: utf-8 -*-
import csv
import os
import re
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
STATIC = os.path.join(BASE, "static")
DB_PATH = os.path.join(BASE, "bank.db")

SERVICES = ("deposit", "loan", "fx")
TIME_FMT = "%Y-%m-%d %H:%M"
PHONE_RE = re.compile(r"^01\d-\d{3,4}-\d{4}$")
HOLD_MINUTES = 3
PRIORITY_MINUTES = 10

LOCK = threading.RLock()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_time(s):
    return datetime.strptime(s, TIME_FMT)


def minutes_between(a, b):
    return (parse_time(a) - parse_time(b)).total_seconds() / 60


def is_priority(reserved_at, arrived_at):
    if not reserved_at or not arrived_at:
        return 0
    return 1 if abs(minutes_between(arrived_at, reserved_at)) <= PRIORITY_MINUTES else 0


def build_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE bk_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT, counter_id TEXT);
        CREATE TABLE bk_counters (counter_id TEXT PRIMARY KEY, name TEXT, service TEXT);
        CREATE TABLE bk_tickets (ticket_id TEXT PRIMARY KEY, number INTEGER, name TEXT, phone TEXT,
            account TEXT, service TEXT, reserved_at TEXT, arrived_at TEXT, status TEXT,
            counter_id TEXT, called_at TEXT, priority INTEGER DEFAULT 0);
    """)
    for r in read_csv("users.csv"):
        conn.execute("INSERT INTO bk_users VALUES (?,?,?,?)",
                     (r["user_id"], r["name"], r["role"], r["counter_id"] or ""))
    for r in read_csv("counters.csv"):
        conn.execute("INSERT INTO bk_counters VALUES (?,?,?)", (r["counter_id"], r["name"], r["service"]))
    for r in read_csv("tickets.csv"):
        conn.execute("INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (r["ticket_id"], int(r["number"]), r["name"], r["phone"], r["account"], r["service"],
                      r["reserved_at"], r["arrived_at"], r["status"], r["counter_id"], r["called_at"],
                      is_priority(r["reserved_at"], r["arrived_at"])))
    conn.commit()
    return conn


DB = build_db()
app = FastAPI()


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def q(sql, args=()):
    return DB.execute(sql, args).fetchall()


def q1(sql, args=()):
    return DB.execute(sql, args).fetchone()


def mask(name):
    n = len(name)
    if n <= 1:
        return "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def need_user(value):
    if not isinstance(value, str) or not value.strip():
        raise Reject(400, "사용자를 확인하세요")
    return value


def now_of(body):
    at = body.get("at")
    if at is None:
        return datetime.now().strftime(TIME_FMT)
    try:
        parse_time(at)
    except Exception:
        raise Reject(400, "시각을 확인하세요")
    return at


def find_user(uid):
    u = q1("SELECT * FROM bk_users WHERE user_id=?", (uid,))
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return u


def find_counter(cid):
    c = q1("SELECT * FROM bk_counters WHERE counter_id=?", (cid,))
    if not c:
        raise Reject(404, "창구를 찾을 수 없습니다")
    return c


def find_ticket(tid):
    t = q1("SELECT * FROM bk_tickets WHERE ticket_id=?", (tid,))
    if not t:
        raise Reject(404, "번호표를 찾을 수 없습니다")
    return t


def own_counter_only(user, counter_id):
    if user["role"] != "teller" or user["counter_id"] != counter_id:
        raise Reject(403, "자기 창구만 할 수 있습니다")


def own_customer_only(user, ticket):
    if user["role"] != "teller" or not ticket["counter_id"] or user["counter_id"] != ticket["counter_id"]:
        raise Reject(403, "자기 창구 고객이 아닙니다")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/board")
def board_page():
    return FileResponse(os.path.join(STATIC, "board.html"))


@app.get("/api/users")
def users():
    with LOCK:
        rows = q("SELECT * FROM bk_users ORDER BY rowid")
    return [{"user_id": r["user_id"], "name": r["name"], "role": r["role"], "counter_id": r["counter_id"]}
            for r in rows]


@app.get("/api/board")
def board():
    with LOCK:
        rows = q("SELECT * FROM bk_tickets WHERE status IN ('called','waiting') ORDER BY number")
    return {
        "serving": [{"number": r["number"], "masked_name": mask(r["name"]), "counter_id": r["counter_id"]}
                    for r in rows if r["status"] == "called"],
        "waiting": [{"number": r["number"], "masked_name": mask(r["name"])}
                    for r in rows if r["status"] == "waiting"],
    }


@app.post("/api/tickets", status_code=201)
async def create_ticket(request: Request):
    b = await body_of(request)
    name, phone, account, service = b.get("name"), b.get("phone"), b.get("account"), b.get("service")
    if not isinstance(name, str) or not name.strip():
        raise Reject(400, "이름을 확인하세요")
    if not isinstance(phone, str) or not PHONE_RE.match(phone):
        raise Reject(400, "전화번호 형식을 확인하세요")
    if not isinstance(account, str) or not account.strip():
        raise Reject(400, "계좌번호를 확인하세요")
    if service not in SERVICES:
        raise Reject(400, "업무 종류를 확인하세요")
    reserved_at = b.get("reserved_at")
    if reserved_at is not None:
        try:
            parse_time(reserved_at)
        except Exception:
            raise Reject(400, "예약 시각을 확인하세요")
    now = now_of(b)
    with LOCK:
        number = (q1("SELECT MAX(number) m FROM bk_tickets")["m"] or 100) + 1
        ids = [int(m.group(1)) for r in q("SELECT ticket_id FROM bk_tickets")
               for m in [re.match(r"^K-(\d+)$", r["ticket_id"])] if m]
        tid = "K-%02d" % (max(ids or [0]) + 1)
        status = "reserved" if reserved_at else "waiting"
        DB.execute("INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (tid, number, name.strip(), phone, account.strip(), service, reserved_at or "",
                    "" if reserved_at else now, status, "", "", 0))
        DB.commit()
    return {"ticket_id": tid, "number": number, "status": status}


@app.post("/api/tickets/{ticket_id}/checkin")
async def checkin(ticket_id: str, request: Request):
    b = await body_of(request)
    now = now_of(b)
    with LOCK:
        t = find_ticket(ticket_id)
        if t["status"] != "reserved":
            raise Reject(409, "예약 상태가 아닙니다")
        pr = is_priority(t["reserved_at"], now)
        DB.execute("UPDATE bk_tickets SET status='waiting', arrived_at=?, priority=? WHERE ticket_id=?",
                   (now, pr, ticket_id))
        DB.commit()
    return {"ticket_id": ticket_id, "number": t["number"], "status": "waiting", "priority": bool(pr)}


def waiting_for(service):
    return q("SELECT * FROM bk_tickets WHERE status='waiting' AND service=? "
             "ORDER BY priority DESC, arrived_at ASC, number ASC", (service,))


@app.get("/api/counters/{counter_id}/queue")
def queue(counter_id: str, viewer: str = None):
    need_user(viewer)
    with LOCK:
        c = find_counter(counter_id)
        u = find_user(viewer)
        own_counter_only(u, counter_id)
        rows = waiting_for(c["service"])
    return [{"ticket_id": r["ticket_id"], "number": r["number"], "masked_name": mask(r["name"]),
             "service": r["service"], "priority": bool(r["priority"])} for r in rows]


@app.post("/api/counters/{counter_id}/next")
async def next_call(counter_id: str, request: Request):
    b = await body_of(request)
    uid = need_user(b.get("user"))
    now = now_of(b)
    with LOCK:
        c = find_counter(counter_id)
        u = find_user(uid)
        own_counter_only(u, counter_id)
        cur = q1("SELECT * FROM bk_tickets WHERE status='called' AND counter_id=?", (counter_id,))
        if cur and minutes_between(now, cur["called_at"]) < HOLD_MINUTES:
            raise Reject(409, "호출 뒤 3분이 지나야 다음 번호를 부를 수 있습니다")
        held = None
        if cur:
            DB.execute("UPDATE bk_tickets SET status='held' WHERE ticket_id=?", (cur["ticket_id"],))
            held = cur["ticket_id"]
        rows = waiting_for(c["service"])
        called = None
        if rows:
            t = rows[0]
            DB.execute("UPDATE bk_tickets SET status='called', counter_id=?, called_at=? WHERE ticket_id=?",
                       (counter_id, now, t["ticket_id"]))
            called = {"ticket_id": t["ticket_id"], "number": t["number"],
                      "masked_name": mask(t["name"]), "counter_id": counter_id}
        DB.commit()
    return {"called": called, "held": held}


@app.post("/api/tickets/{ticket_id}/complete")
async def complete(ticket_id: str, request: Request):
    b = await body_of(request)
    uid = need_user(b.get("user"))
    now_of(b)
    with LOCK:
        t = find_ticket(ticket_id)
        u = find_user(uid)
        own_customer_only(u, t)
        if t["status"] != "called":
            raise Reject(409, "호출 중인 고객이 아닙니다")
        DB.execute("UPDATE bk_tickets SET status='done' WHERE ticket_id=?", (ticket_id,))
        DB.commit()
    return {"ticket_id": ticket_id, "status": "done"}


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str, viewer: str = None):
    need_user(viewer)
    with LOCK:
        t = find_ticket(ticket_id)
        u = find_user(viewer)
        own_customer_only(u, t)
    return {"ticket_id": t["ticket_id"], "number": t["number"], "name": t["name"], "phone": t["phone"],
            "account_last4": t["account"][-4:], "service": t["service"], "status": t["status"],
            "counter_id": t["counter_id"]}


@app.get("/api/manager/summary")
def summary(viewer: str = None):
    need_user(viewer)
    with LOCK:
        u = find_user(viewer)
        if u["role"] != "manager":
            raise Reject(403, "지점장만 볼 수 있습니다")
        waiting = {s: 0 for s in SERVICES}
        for r in q("SELECT service, COUNT(*) n FROM bk_tickets WHERE status='waiting' GROUP BY service"):
            if r["service"] in waiting:
                waiting[r["service"]] = r["n"]

        def count(st):
            return q1("SELECT COUNT(*) n FROM bk_tickets WHERE status=?", (st,))["n"]

        counters = []
        for c in q("SELECT * FROM bk_counters ORDER BY rowid"):
            cur = q1("SELECT number FROM bk_tickets WHERE status='called' AND counter_id=?", (c["counter_id"],))
            counters.append({"counter_id": c["counter_id"], "service": c["service"],
                             "number": cur["number"] if cur else None})
        return {"waiting": waiting, "held": count("held"), "done": count("done"), "counters": counters}
