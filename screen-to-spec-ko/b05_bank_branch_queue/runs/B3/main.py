import csv
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
STATIC = BASE / "static"
DB_PATH = BASE / "bank.db"

TIME_FMT = "%Y-%m-%d %H:%M"
SERVICES = ("deposit", "loan", "fx")
PHONE_RE = re.compile(r"^01\d-\d{3,4}-\d{4}$")
PRIORITY_WINDOW_MIN = 10
HOLD_AFTER_MIN = 3

app = FastAPI()


# ---------- DB ----------

def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_time(s):
    try:
        return datetime.strptime(s, TIME_FMT)
    except (TypeError, ValueError):
        return None


def is_priority(reserved_at, arrived_at):
    r, a = parse_time(reserved_at), parse_time(arrived_at)
    if not r or not a:
        return False
    return abs((a - r).total_seconds()) <= PRIORITY_WINDOW_MIN * 60


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE bk_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT, counter_id TEXT);
        CREATE TABLE bk_counters (counter_id TEXT PRIMARY KEY, name TEXT, service TEXT);
        CREATE TABLE bk_tickets (
            ticket_id TEXT PRIMARY KEY, number INTEGER, name TEXT, phone TEXT, account TEXT,
            service TEXT, reserved_at TEXT, arrived_at TEXT, status TEXT, counter_id TEXT,
            called_at TEXT, priority INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    for r in read_csv("users.csv"):
        conn.execute("INSERT INTO bk_users VALUES (?,?,?,?)",
                     (r["user_id"], r["name"], r["role"], r["counter_id"] or None))
    for r in read_csv("counters.csv"):
        conn.execute("INSERT INTO bk_counters VALUES (?,?,?)",
                     (r["counter_id"], r["name"], r["service"]))
    for r in read_csv("tickets.csv"):
        reserved = r["reserved_at"] or None
        arrived = r["arrived_at"] or None
        conn.execute(
            "INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["ticket_id"], int(r["number"]), r["name"], r["phone"], r["account"], r["service"],
             reserved, arrived, r["status"], r["counter_id"] or None, r["called_at"] or None,
             1 if is_priority(reserved, arrived) else 0),
        )
    conn.commit()
    return conn


db = init_db()


# ---------- helpers ----------

def err(code, detail):
    return HTTPException(status_code=code, detail=detail)


def mask_name(name):
    n = len(name)
    if n <= 1:
        return "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


async def read_body(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def need_user(value):
    if not isinstance(value, str) or not value.strip():
        raise err(400, "사용자를 확인하세요")
    return value.strip()


def now_from(body):
    """본문의 at 을 '지금' 으로. 없으면 서버 시각(분 단위)."""
    at = body.get("at")
    if at is None:
        return datetime.now().replace(second=0, microsecond=0)
    t = parse_time(at) if isinstance(at, str) else None
    if not t:
        raise err(400, "시각 형식을 확인하세요")
    return t


def fmt(t):
    return t.strftime(TIME_FMT)


def get_user(user_id):
    row = db.execute("SELECT * FROM bk_users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise err(404, "없는 사용자입니다")
    return row


def get_counter(counter_id):
    row = db.execute("SELECT * FROM bk_counters WHERE counter_id=?", (counter_id,)).fetchone()
    if not row:
        raise err(404, "없는 창구입니다")
    return row


def get_ticket(ticket_id):
    row = db.execute("SELECT * FROM bk_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not row:
        raise err(404, "없는 번호표입니다")
    return row


def is_counter_teller(user, counter_id):
    return user["role"] == "teller" and user["counter_id"] == counter_id


QUEUE_ORDER = "priority DESC, arrived_at ASC, number ASC"


# ---------- API ----------

@app.get("/api/users")
async def api_users():
    rows = db.execute("SELECT user_id, name, role, counter_id FROM bk_users ORDER BY rowid").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/board")
async def api_board():
    serving = db.execute(
        "SELECT number, name, counter_id FROM bk_tickets WHERE status='called' ORDER BY number"
    ).fetchall()
    waiting = db.execute(
        "SELECT number, name FROM bk_tickets WHERE status='waiting' ORDER BY number"
    ).fetchall()
    return {
        "serving": [{"number": r["number"], "masked_name": mask_name(r["name"]),
                     "counter_id": r["counter_id"]} for r in serving],
        "waiting": [{"number": r["number"], "masked_name": mask_name(r["name"])} for r in waiting],
    }


@app.post("/api/tickets", status_code=201)
async def api_create_ticket(request: Request):
    body = await read_body(request)
    name, phone = body.get("name"), body.get("phone")
    account, service = body.get("account"), body.get("service")
    if not isinstance(name, str) or not name.strip():
        raise err(400, "이름을 확인하세요")
    if not isinstance(phone, str) or not PHONE_RE.match(phone.strip()):
        raise err(400, "전화번호 형식을 확인하세요")
    if not isinstance(account, str) or not account.strip():
        raise err(400, "계좌번호를 확인하세요")
    if service not in SERVICES:
        raise err(400, "업무 종류를 확인하세요")
    reserved_at = body.get("reserved_at")
    if reserved_at is not None and (not isinstance(reserved_at, str) or not parse_time(reserved_at)):
        raise err(400, "예약 시각 형식을 확인하세요")
    now = now_from(body)

    top = db.execute("SELECT MAX(number) AS m FROM bk_tickets").fetchone()["m"]
    number = (top or 0) + 1
    ids = [r["ticket_id"] for r in db.execute("SELECT ticket_id FROM bk_tickets")]
    seq = max([int(m.group(1)) for i in ids if (m := re.fullmatch(r"K-(\d+)", i))] or [0]) + 1
    ticket_id = f"K-{seq:02d}"

    if reserved_at is None:
        status, arrived = "waiting", fmt(now)
    else:
        status, arrived = "reserved", None
    db.execute(
        "INSERT INTO bk_tickets (ticket_id, number, name, phone, account, service, reserved_at,"
        " arrived_at, status, priority) VALUES (?,?,?,?,?,?,?,?,?,0)",
        (ticket_id, number, name.strip(), phone.strip(), account.strip(), service,
         reserved_at, arrived, status),
    )
    db.commit()
    return {"ticket_id": ticket_id, "number": number, "status": status}


@app.post("/api/tickets/{ticket_id}/checkin")
async def api_checkin(ticket_id: str, request: Request):
    body = await read_body(request)
    now = now_from(body)
    t = get_ticket(ticket_id)
    if t["status"] != "reserved":
        raise err(409, "예약 상태가 아닙니다")
    arrived = fmt(now)
    priority = is_priority(t["reserved_at"], arrived)
    db.execute("UPDATE bk_tickets SET status='waiting', arrived_at=?, priority=? WHERE ticket_id=?",
               (arrived, 1 if priority else 0, ticket_id))
    db.commit()
    return {"ticket_id": ticket_id, "number": t["number"], "status": "waiting", "priority": priority}


@app.get("/api/counters/{counter_id}/queue")
async def api_queue(counter_id: str, viewer: str = None):
    viewer = need_user(viewer)
    counter = get_counter(counter_id)
    user = get_user(viewer)
    if not is_counter_teller(user, counter_id):
        raise err(403, "자기 창구만 할 수 있습니다")
    rows = db.execute(
        f"SELECT * FROM bk_tickets WHERE status='waiting' AND service=? ORDER BY {QUEUE_ORDER}",
        (counter["service"],),
    ).fetchall()
    return [{"ticket_id": r["ticket_id"], "number": r["number"],
             "masked_name": mask_name(r["name"]), "service": r["service"],
             "priority": bool(r["priority"])} for r in rows]


@app.post("/api/counters/{counter_id}/next")
async def api_next(counter_id: str, request: Request):
    body = await read_body(request)
    user_id = need_user(body.get("user"))
    now = now_from(body)
    counter = get_counter(counter_id)
    user = get_user(user_id)
    if not is_counter_teller(user, counter_id):
        raise err(403, "자기 창구만 할 수 있습니다")

    current = db.execute(
        "SELECT * FROM bk_tickets WHERE status='called' AND counter_id=? ORDER BY called_at",
        (counter_id,),
    ).fetchall()
    for c in current:
        called = parse_time(c["called_at"])
        if called is None or (now - called).total_seconds() < HOLD_AFTER_MIN * 60:
            raise err(409, "호출 뒤 3분이 지나야 다음 번호를 부를 수 있습니다")
    held = None
    for c in current:
        db.execute("UPDATE bk_tickets SET status='held' WHERE ticket_id=?", (c["ticket_id"],))
        held = c["ticket_id"]

    nxt = db.execute(
        f"SELECT * FROM bk_tickets WHERE status='waiting' AND service=? ORDER BY {QUEUE_ORDER} LIMIT 1",
        (counter["service"],),
    ).fetchone()
    called = None
    if nxt:
        db.execute("UPDATE bk_tickets SET status='called', counter_id=?, called_at=? WHERE ticket_id=?",
                   (counter_id, fmt(now), nxt["ticket_id"]))
        called = {"ticket_id": nxt["ticket_id"], "number": nxt["number"],
                  "masked_name": mask_name(nxt["name"]), "counter_id": counter_id}
    db.commit()
    return {"called": called, "held": held}


@app.post("/api/tickets/{ticket_id}/complete")
async def api_complete(ticket_id: str, request: Request):
    body = await read_body(request)
    user_id = need_user(body.get("user"))
    now_from(body)
    t = get_ticket(ticket_id)
    user = get_user(user_id)
    if not t["counter_id"] or not is_counter_teller(user, t["counter_id"]):
        raise err(403, "자기 창구 고객이 아닙니다")
    if t["status"] != "called":
        raise err(409, "호출 중인 고객이 아닙니다")
    db.execute("UPDATE bk_tickets SET status='done' WHERE ticket_id=?", (ticket_id,))
    db.commit()
    return {"ticket_id": ticket_id, "status": "done"}


@app.get("/api/tickets/{ticket_id}")
async def api_ticket(ticket_id: str, viewer: str = None):
    viewer = need_user(viewer)
    t = get_ticket(ticket_id)
    user = get_user(viewer)
    if not t["counter_id"] or not is_counter_teller(user, t["counter_id"]):
        raise err(403, "자기 창구 고객이 아닙니다")
    return {"ticket_id": t["ticket_id"], "number": t["number"], "name": t["name"],
            "phone": t["phone"], "account_last4": t["account"][-4:], "service": t["service"],
            "status": t["status"], "counter_id": t["counter_id"]}


@app.get("/api/manager/summary")
async def api_summary(viewer: str = None):
    viewer = need_user(viewer)
    user = get_user(viewer)
    if user["role"] != "manager":
        raise err(403, "지점장만 볼 수 있습니다")
    waiting = {s: 0 for s in SERVICES}
    for r in db.execute("SELECT service, COUNT(*) AS n FROM bk_tickets WHERE status='waiting' GROUP BY service"):
        if r["service"] in waiting:
            waiting[r["service"]] = r["n"]
    count = lambda st: db.execute("SELECT COUNT(*) AS n FROM bk_tickets WHERE status=?", (st,)).fetchone()["n"]
    counters = []
    for c in db.execute("SELECT * FROM bk_counters ORDER BY counter_id"):
        row = db.execute("SELECT number FROM bk_tickets WHERE status='called' AND counter_id=? ORDER BY called_at DESC",
                         (c["counter_id"],)).fetchone()
        counters.append({"counter_id": c["counter_id"], "service": c["service"],
                         "number": row["number"] if row else None})
    return {"waiting": waiting, "held": count("held"), "done": count("done"), "counters": counters}


# ---------- pages ----------

@app.get("/board")
async def page_board():
    return FileResponse(STATIC / "board.html")


@app.get("/")
async def page_index():
    return FileResponse(STATIC / "index.html")
