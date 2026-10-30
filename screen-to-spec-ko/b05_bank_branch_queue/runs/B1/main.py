import csv
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "bank.db"
FMT = "%Y-%m-%d %H:%M"
SERVICES = ("deposit", "loan", "fx")
PHONE_RE = re.compile(r"^01\d-\d{3,4}-\d{4}$")

app = FastAPI()
lock = threading.RLock()


def parse_time(value):
    try:
        return datetime.strptime(value, FMT)
    except (TypeError, ValueError):
        return None


def is_priority(reserved_at, arrived_at):
    r, a = parse_time(reserved_at), parse_time(arrived_at)
    if not r or not a:
        return 0
    return 1 if abs((a - r).total_seconds()) <= 600 else 0


def read_csv(name):
    with open(ROOT / "seed" / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(
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
        con.execute("INSERT INTO bk_users VALUES (?,?,?,?)",
                    (r["user_id"], r["name"], r["role"], r["counter_id"] or None))
    for r in read_csv("counters.csv"):
        con.execute("INSERT INTO bk_counters VALUES (?,?,?)", (r["counter_id"], r["name"], r["service"]))
    for r in read_csv("tickets.csv"):
        res, arr = r["reserved_at"] or None, r["arrived_at"] or None
        con.execute(
            "INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["ticket_id"], int(r["number"]), r["name"], r["phone"], r["account"], r["service"],
             res, arr, r["status"], r["counter_id"] or None, r["called_at"] or None,
             is_priority(res, arr)),
        )
    con.commit()
    con.close()


init_db()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def mask(name):
    n = len(name)
    if n <= 1:
        return "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


async def read_body(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def fail(code, detail):
    raise HTTPException(status_code=code, detail=detail)


def need_user_id(value):
    if not isinstance(value, str) or not value.strip():
        fail(400, "사용자를 확인하세요")
    return value


def get_now(body):
    at = body.get("at")
    if at is None:
        return datetime.now().replace(second=0, microsecond=0)
    t = parse_time(at) if isinstance(at, str) else None
    if t is None:
        fail(400, "시각 형식을 확인하세요")
    return t


def find_user(con, user_id):
    row = con.execute("SELECT * FROM bk_users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        fail(404, "사용자를 찾을 수 없습니다")
    return row


def find_counter(con, counter_id):
    row = con.execute("SELECT * FROM bk_counters WHERE counter_id=?", (counter_id,)).fetchone()
    if not row:
        fail(404, "창구를 찾을 수 없습니다")
    return row


def find_ticket(con, ticket_id):
    row = con.execute("SELECT * FROM bk_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not row:
        fail(404, "번호표를 찾을 수 없습니다")
    return row


def require_own_counter(user, counter_id):
    if user["role"] != "teller" or user["counter_id"] != counter_id:
        fail(403, "자기 창구만 할 수 있습니다")


def waiting_rows(con, service):
    return con.execute(
        "SELECT * FROM bk_tickets WHERE status='waiting' AND service=? "
        "ORDER BY priority DESC, arrived_at ASC, number ASC",
        (service,),
    ).fetchall()


@app.get("/")
def index_page():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/board")
def board_page():
    return FileResponse(ROOT / "static" / "board.html")


@app.get("/api/users")
def users():
    with lock, db() as con:
        rows = con.execute("SELECT * FROM bk_users ORDER BY rowid").fetchall()
    return [{"user_id": r["user_id"], "name": r["name"], "role": r["role"],
             "counter_id": r["counter_id"]} for r in rows]


@app.get("/api/board")
def board():
    with lock, db() as con:
        serving = con.execute(
            "SELECT * FROM bk_tickets WHERE status='called' ORDER BY number").fetchall()
        waiting = con.execute(
            "SELECT * FROM bk_tickets WHERE status='waiting' ORDER BY number").fetchall()
    return {
        "serving": [{"number": r["number"], "masked_name": mask(r["name"]),
                     "counter_id": r["counter_id"]} for r in serving],
        "waiting": [{"number": r["number"], "masked_name": mask(r["name"])} for r in waiting],
    }


@app.post("/api/tickets", status_code=201)
async def create_ticket(request: Request):
    body = await read_body(request)
    name, phone, account = body.get("name"), body.get("phone"), body.get("account")
    service, reserved_at = body.get("service"), body.get("reserved_at")
    if not isinstance(name, str) or not name.strip():
        fail(400, "이름을 확인하세요")
    if not isinstance(phone, str) or not PHONE_RE.match(phone):
        fail(400, "전화번호 형식을 확인하세요")
    if not isinstance(account, str) or not account.strip():
        fail(400, "계좌번호를 확인하세요")
    if service not in SERVICES:
        fail(400, "업무 종류를 확인하세요")
    if reserved_at is not None and (not isinstance(reserved_at, str) or not parse_time(reserved_at)):
        fail(400, "예약 시각을 확인하세요")
    now = get_now(body)
    with lock, db() as con:
        number = (con.execute("SELECT MAX(number) FROM bk_tickets").fetchone()[0] or 0) + 1
        count = con.execute("SELECT COUNT(*) FROM bk_tickets").fetchone()[0]
        ticket_id = f"K-{count + 1:02d}"
        while con.execute("SELECT 1 FROM bk_tickets WHERE ticket_id=?", (ticket_id,)).fetchone():
            count += 1
            ticket_id = f"K-{count + 1:02d}"
        if reserved_at is None:
            status, arrived = "waiting", now.strftime(FMT)
        else:
            status, arrived = "reserved", None
        con.execute(
            "INSERT INTO bk_tickets (ticket_id, number, name, phone, account, service, reserved_at,"
            " arrived_at, status, priority) VALUES (?,?,?,?,?,?,?,?,?,0)",
            (ticket_id, number, name.strip(), phone, account.strip(), service, reserved_at,
             arrived, status),
        )
    return {"ticket_id": ticket_id, "number": number, "status": status}


@app.post("/api/tickets/{ticket_id}/checkin")
async def checkin(ticket_id: str, request: Request):
    body = await read_body(request)
    now = get_now(body)
    with lock, db() as con:
        t = find_ticket(con, ticket_id)
        if t["status"] != "reserved":
            fail(409, "예약 상태가 아닙니다")
        arrived = now.strftime(FMT)
        pr = is_priority(t["reserved_at"], arrived)
        con.execute("UPDATE bk_tickets SET status='waiting', arrived_at=?, priority=? WHERE ticket_id=?",
                    (arrived, pr, ticket_id))
    return {"ticket_id": ticket_id, "number": t["number"], "status": "waiting", "priority": bool(pr)}


@app.get("/api/counters/{counter_id}/queue")
def counter_queue(counter_id: str, viewer: str = None):
    need_user_id(viewer)
    with lock, db() as con:
        counter = find_counter(con, counter_id)
        user = find_user(con, viewer)
        require_own_counter(user, counter_id)
        rows = waiting_rows(con, counter["service"])
    return [{"ticket_id": r["ticket_id"], "number": r["number"], "masked_name": mask(r["name"]),
             "service": r["service"], "priority": bool(r["priority"])} for r in rows]


@app.post("/api/counters/{counter_id}/next")
async def call_next(counter_id: str, request: Request):
    body = await read_body(request)
    user_id = need_user_id(body.get("user"))
    now = get_now(body)
    with lock, db() as con:
        counter = find_counter(con, counter_id)
        user = find_user(con, user_id)
        require_own_counter(user, counter_id)
        current = con.execute(
            "SELECT * FROM bk_tickets WHERE status='called' AND counter_id=? ORDER BY number",
            (counter_id,)).fetchone()
        held = None
        if current:
            called_at = parse_time(current["called_at"])
            if called_at and (now - called_at).total_seconds() < 180:
                fail(409, "호출 뒤 3분이 지나야 다음 번호를 부를 수 있습니다")
            con.execute("UPDATE bk_tickets SET status='held' WHERE ticket_id=?", (current["ticket_id"],))
            held = current["ticket_id"]
        rows = waiting_rows(con, counter["service"])
        if not rows:
            return {"called": None, "held": held}
        nxt = rows[0]
        con.execute("UPDATE bk_tickets SET status='called', counter_id=?, called_at=? WHERE ticket_id=?",
                    (counter_id, now.strftime(FMT), nxt["ticket_id"]))
    return {"called": {"ticket_id": nxt["ticket_id"], "number": nxt["number"],
                       "masked_name": mask(nxt["name"]), "counter_id": counter_id},
            "held": held}


def require_ticket_owner(user, ticket):
    if user["role"] != "teller" or not ticket["counter_id"] or user["counter_id"] != ticket["counter_id"]:
        fail(403, "자기 창구 고객이 아닙니다")


@app.post("/api/tickets/{ticket_id}/complete")
async def complete(ticket_id: str, request: Request):
    body = await read_body(request)
    user_id = need_user_id(body.get("user"))
    get_now(body)
    with lock, db() as con:
        t = find_ticket(con, ticket_id)
        user = find_user(con, user_id)
        require_ticket_owner(user, t)
        if t["status"] != "called":
            fail(409, "호출 중인 고객이 아닙니다")
        con.execute("UPDATE bk_tickets SET status='done' WHERE ticket_id=?", (ticket_id,))
    return {"ticket_id": ticket_id, "status": "done"}


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str, viewer: str = None):
    need_user_id(viewer)
    with lock, db() as con:
        t = find_ticket(con, ticket_id)
        user = find_user(con, viewer)
        require_ticket_owner(user, t)
    return {"ticket_id": t["ticket_id"], "number": t["number"], "name": t["name"],
            "phone": t["phone"], "account_last4": t["account"][-4:], "service": t["service"],
            "status": t["status"], "counter_id": t["counter_id"]}


@app.get("/api/manager/summary")
def manager_summary(viewer: str = None):
    need_user_id(viewer)
    with lock, db() as con:
        user = find_user(con, viewer)
        if user["role"] != "manager":
            fail(403, "지점장만 볼 수 있습니다")
        waiting = {s: con.execute(
            "SELECT COUNT(*) FROM bk_tickets WHERE status='waiting' AND service=?", (s,)).fetchone()[0]
            for s in SERVICES}
        held = con.execute("SELECT COUNT(*) FROM bk_tickets WHERE status='held'").fetchone()[0]
        done = con.execute("SELECT COUNT(*) FROM bk_tickets WHERE status='done'").fetchone()[0]
        counters = []
        for c in con.execute("SELECT * FROM bk_counters ORDER BY rowid").fetchall():
            cur = con.execute(
                "SELECT number FROM bk_tickets WHERE status='called' AND counter_id=? ORDER BY number",
                (c["counter_id"],)).fetchone()
            counters.append({"counter_id": c["counter_id"], "service": c["service"],
                             "number": cur["number"] if cur else None})
    return {"waiting": waiting, "held": held, "done": done, "counters": counters}
