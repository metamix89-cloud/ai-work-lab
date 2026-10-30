import csv
import os
import re
import sqlite3
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "bank.db")
SEED = os.path.join(BASE, "seed")
STATIC = os.path.join(BASE, "static")
FMT = "%Y-%m-%d %H:%M"
SERVICES = ("deposit", "loan", "fx")
PHONE_RE = re.compile(r"^01\d-\d{3,4}-\d{4}$")


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def parse(s):
    try:
        return datetime.strptime(s, FMT)
    except (TypeError, ValueError):
        return None


def is_priority(reserved_at, arrived_at):
    r, a = parse(reserved_at), parse(arrived_at)
    return bool(r and a and abs(a - r) <= timedelta(minutes=10))


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = connect()
    con.executescript("""
        CREATE TABLE bk_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT, counter_id TEXT);
        CREATE TABLE bk_counters (counter_id TEXT PRIMARY KEY, name TEXT, service TEXT);
        CREATE TABLE bk_tickets (ticket_id TEXT PRIMARY KEY, number INTEGER, name TEXT, phone TEXT,
            account TEXT, service TEXT, reserved_at TEXT, arrived_at TEXT, status TEXT,
            counter_id TEXT, called_at TEXT, priority INTEGER DEFAULT 0);
    """)
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO bk_users VALUES (?,?,?,?)",
                    (r["user_id"], r["name"], r["role"], r["counter_id"] or None))
    for r in read_csv("counters.csv"):
        con.execute("INSERT INTO bk_counters VALUES (?,?,?)", (r["counter_id"], r["name"], r["service"]))
    for r in read_csv("tickets.csv"):
        pri = 1 if r["status"] == "waiting" and is_priority(r["reserved_at"], r["arrived_at"]) else 0
        con.execute("INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["ticket_id"], int(r["number"]), r["name"], r["phone"], r["account"], r["service"],
                     r["reserved_at"] or None, r["arrived_at"] or None, r["status"],
                     r["counter_id"] or None, r["called_at"] or None, pri))
    con.commit()
    con.close()


init_db()
app = FastAPI()


def mask(name):
    n = len(name)
    if n <= 1:
        return "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


async def body_of(request):
    try:
        j = await request.json()
    except Exception:
        return {}
    return j if isinstance(j, dict) else {}


def now_of(body):
    at = body.get("at")
    if at is None or at == "":
        return datetime.now().strftime(FMT)
    if not isinstance(at, str) or parse(at) is None:
        raise HTTPException(400, "시각을 확인하세요")
    return at


def need_user(value):
    if not isinstance(value, str) or not value:
        raise HTTPException(400, "사용자를 확인하세요")
    return value


def get_user(con, uid):
    u = con.execute("SELECT * FROM bk_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자를 찾을 수 없습니다")
    return u


def get_counter(con, cid):
    c = con.execute("SELECT * FROM bk_counters WHERE counter_id=?", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "창구를 찾을 수 없습니다")
    return c


def get_ticket(con, tid):
    t = con.execute("SELECT * FROM bk_tickets WHERE ticket_id=?", (tid,)).fetchone()
    if not t:
        raise HTTPException(404, "번호표를 찾을 수 없습니다")
    return t


def own_counter(user, cid):
    if user["role"] != "teller" or user["counter_id"] != cid:
        raise HTTPException(403, "자기 창구만 할 수 있습니다")


def queue_rows(con, service):
    return con.execute(
        "SELECT * FROM bk_tickets WHERE status='waiting' AND service=? "
        "ORDER BY priority DESC, arrived_at, number", (service,)).fetchall()


@app.get("/")
def index_page():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/board")
def board_page():
    return FileResponse(os.path.join(STATIC, "board.html"))


@app.get("/api/users")
def users():
    con = connect()
    rows = con.execute("SELECT user_id, name, role, counter_id FROM bk_users ORDER BY rowid").fetchall()
    con.close()
    return [{"user_id": r["user_id"], "name": r["name"], "role": r["role"], "counter_id": r["counter_id"] or ""}
            for r in rows]


@app.get("/api/board")
def board():
    con = connect()
    serving = con.execute("SELECT number, name, counter_id FROM bk_tickets WHERE status='called' ORDER BY number").fetchall()
    waiting = con.execute("SELECT number, name FROM bk_tickets WHERE status='waiting' ORDER BY number").fetchall()
    con.close()
    return {"serving": [{"number": r["number"], "masked_name": mask(r["name"]), "counter_id": r["counter_id"]} for r in serving],
            "waiting": [{"number": r["number"], "masked_name": mask(r["name"])} for r in waiting]}


@app.post("/api/tickets", status_code=201)
async def create_ticket(request: Request):
    b = await body_of(request)
    name, phone, account, service = b.get("name"), b.get("phone"), b.get("account"), b.get("service")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(400, "이름을 확인하세요")
    if not isinstance(phone, str) or not PHONE_RE.match(phone):
        raise HTTPException(400, "전화번호 형식을 확인하세요")
    if not isinstance(account, str) or not account.strip():
        raise HTTPException(400, "계좌번호를 확인하세요")
    if service not in SERVICES:
        raise HTTPException(400, "업무 종류를 확인하세요")
    reserved_at = b.get("reserved_at")
    if reserved_at in (None, ""):
        reserved_at = None
    elif not isinstance(reserved_at, str) or parse(reserved_at) is None:
        raise HTTPException(400, "예약 시각을 확인하세요")
    now = now_of(b)
    con = connect()
    number = (con.execute("SELECT MAX(number) FROM bk_tickets").fetchone()[0] or 100) + 1
    i = con.execute("SELECT COUNT(*) FROM bk_tickets").fetchone()[0] + 1
    while con.execute("SELECT 1 FROM bk_tickets WHERE ticket_id=?", ("K-%02d" % i,)).fetchone():
        i += 1
    tid = "K-%02d" % i
    status, arrived = ("reserved", None) if reserved_at else ("waiting", now)
    con.execute("INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
                (tid, number, name.strip(), phone, account.strip(), service, reserved_at, arrived, status, None, None))
    con.commit()
    con.close()
    return {"ticket_id": tid, "number": number, "status": status}


@app.post("/api/tickets/{ticket_id}/checkin")
async def checkin(ticket_id: str, request: Request):
    b = await body_of(request)
    now = now_of(b)
    con = connect()
    try:
        t = get_ticket(con, ticket_id)
        if t["status"] != "reserved":
            raise HTTPException(409, "예약 상태가 아닙니다")
        pri = is_priority(t["reserved_at"], now)
        con.execute("UPDATE bk_tickets SET status='waiting', arrived_at=?, priority=? WHERE ticket_id=?",
                    (now, int(pri), ticket_id))
        con.commit()
        return {"ticket_id": ticket_id, "number": t["number"], "status": "waiting", "priority": pri}
    finally:
        con.close()


@app.get("/api/counters/{counter_id}/queue")
def counter_queue(counter_id: str, request: Request):
    viewer = need_user(request.query_params.get("viewer"))
    con = connect()
    try:
        c = get_counter(con, counter_id)
        u = get_user(con, viewer)
        own_counter(u, counter_id)
        return [{"ticket_id": r["ticket_id"], "number": r["number"], "masked_name": mask(r["name"]),
                 "service": r["service"], "priority": bool(r["priority"])}
                for r in queue_rows(con, c["service"])]
    finally:
        con.close()


@app.post("/api/counters/{counter_id}/next")
async def counter_next(counter_id: str, request: Request):
    b = await body_of(request)
    uid = need_user(b.get("user"))
    now = now_of(b)
    con = connect()
    try:
        c = get_counter(con, counter_id)
        u = get_user(con, uid)
        own_counter(u, counter_id)
        cur = con.execute("SELECT * FROM bk_tickets WHERE status='called' AND counter_id=? ORDER BY number",
                          (counter_id,)).fetchone()
        held = None
        if cur:
            called_at = parse(cur["called_at"])
            if called_at and parse(now) < called_at + timedelta(minutes=3):
                raise HTTPException(409, "호출 뒤 3분이 지나야 다음 번호를 부를 수 있습니다")
            con.execute("UPDATE bk_tickets SET status='held' WHERE ticket_id=?", (cur["ticket_id"],))
            held = cur["ticket_id"]
        rows = queue_rows(con, c["service"])
        called = None
        if rows:
            n = rows[0]
            con.execute("UPDATE bk_tickets SET status='called', counter_id=?, called_at=? WHERE ticket_id=?",
                        (counter_id, now, n["ticket_id"]))
            called = {"ticket_id": n["ticket_id"], "number": n["number"], "masked_name": mask(n["name"]),
                      "counter_id": counter_id}
        con.commit()
        return {"called": called, "held": held}
    finally:
        con.close()


@app.post("/api/tickets/{ticket_id}/complete")
async def complete(ticket_id: str, request: Request):
    b = await body_of(request)
    uid = need_user(b.get("user"))
    now_of(b)
    con = connect()
    try:
        t = get_ticket(con, ticket_id)
        u = get_user(con, uid)
        if u["role"] != "teller" or t["counter_id"] != u["counter_id"]:
            raise HTTPException(403, "자기 창구 고객이 아닙니다")
        if t["status"] != "called":
            raise HTTPException(409, "호출 중인 고객이 아닙니다")
        con.execute("UPDATE bk_tickets SET status='done' WHERE ticket_id=?", (ticket_id,))
        con.commit()
        return {"ticket_id": ticket_id, "status": "done"}
    finally:
        con.close()


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str, request: Request):
    viewer = need_user(request.query_params.get("viewer"))
    con = connect()
    try:
        t = get_ticket(con, ticket_id)
        u = get_user(con, viewer)
        if u["role"] != "teller" or not t["counter_id"] or t["counter_id"] != u["counter_id"]:
            raise HTTPException(403, "자기 창구 고객이 아닙니다")
        return {"ticket_id": t["ticket_id"], "number": t["number"], "name": t["name"], "phone": t["phone"],
                "account_last4": t["account"][-4:], "service": t["service"], "status": t["status"],
                "counter_id": t["counter_id"]}
    finally:
        con.close()


@app.get("/api/manager/summary")
def manager_summary(request: Request):
    viewer = need_user(request.query_params.get("viewer"))
    con = connect()
    try:
        u = get_user(con, viewer)
        if u["role"] != "manager":
            raise HTTPException(403, "지점장만 볼 수 있습니다")
        waiting = {s: 0 for s in SERVICES}
        for r in con.execute("SELECT service, COUNT(*) n FROM bk_tickets WHERE status='waiting' GROUP BY service"):
            if r["service"] in waiting:
                waiting[r["service"]] = r["n"]

        def count(st):
            return con.execute("SELECT COUNT(*) FROM bk_tickets WHERE status=?", (st,)).fetchone()[0]

        counters = []
        for c in con.execute("SELECT * FROM bk_counters ORDER BY rowid").fetchall():
            cur = con.execute("SELECT number FROM bk_tickets WHERE status='called' AND counter_id=? ORDER BY number",
                              (c["counter_id"],)).fetchone()
            counters.append({"counter_id": c["counter_id"], "service": c["service"],
                             "number": cur["number"] if cur else None})
        return {"waiting": waiting, "held": count("held"), "done": count("done"), "counters": counters}
    finally:
        con.close()
