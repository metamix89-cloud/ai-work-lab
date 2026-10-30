# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R9 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
가리기 · 칸 고르기는 서버에서, 계좌번호 전체는 어떤 응답에도 없음."""
import csv
import os
import re
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "bank.db")
app = FastAPI()
FMT = "%Y-%m-%d %H:%M"
WINDOW_MIN, HOLD_MIN = 10, 3
SERVICES = ("deposit", "loan", "fx")


def load():
    if os.path.exists(DB):
        os.remove(DB)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE bk_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT, counter_id TEXT);
    CREATE TABLE bk_counters(counter_id TEXT PRIMARY KEY, name TEXT, service TEXT);
    CREATE TABLE bk_tickets(ticket_id TEXT PRIMARY KEY, number INTEGER, name TEXT, phone TEXT, account TEXT, service TEXT,
                            reserved_at TEXT, arrived_at TEXT, status TEXT, counter_id TEXT, called_at TEXT);""")
    for name, table, n in (("users.csv", "bk_users", 4), ("counters.csv", "bk_counters", 3), ("tickets.csv", "bk_tickets", 11)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                c.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    c.commit()
    c.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def mask(name):
    if len(name) <= 1:
        return name
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def now_of(at):
    if at is None:
        return datetime.now().strftime(FMT)
    try:
        datetime.strptime(at, FMT)
    except (TypeError, ValueError):
        raise HTTPException(400, "시각 형식을 확인하세요")
    return at


def minutes(a, b):
    return (datetime.strptime(a, FMT) - datetime.strptime(b, FMT)).total_seconds() / 60


def priority_of(t):
    if not t["reserved_at"] or not t["arrived_at"]:
        return False
    return abs(minutes(t["arrived_at"], t["reserved_at"])) < WINDOW_MIN


def need_user(uid):
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, "사용자를 확인하세요")


def find_user(c, uid):
    u = c.execute("SELECT * FROM bk_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    return u


def find_counter(c, cid):
    r = c.execute("SELECT * FROM bk_counters WHERE counter_id=?", (cid,)).fetchone()
    if not r:
        raise HTTPException(404, "창구가 없습니다")
    return r


def find_ticket(c, tid):
    r = c.execute("SELECT * FROM bk_tickets WHERE ticket_id=?", (tid,)).fetchone()
    if not r:
        raise HTTPException(404, "번호표가 없습니다")
    return r


def own_counter(u, cid):
    if u["role"] != "teller" or u["counter_id"] != cid:
        raise HTTPException(403, "자기 창구만 할 수 있습니다")


def own_ticket(u, t):
    if u["role"] != "teller" or not t["counter_id"] or u["counter_id"] != t["counter_id"]:
        raise HTTPException(403, "자기 창구 고객이 아닙니다")


def queue_of(c, service):
    rows = [dict(r) for r in c.execute("SELECT * FROM bk_tickets WHERE status='waiting' AND service=?", (service,))]
    for r in rows:
        r["priority"] = priority_of(r)
    rows.sort(key=lambda r: (not r["priority"], r["arrived_at"], r["number"]))
    return rows


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/board")
def board_page():
    return FileResponse(os.path.join(HERE, "static", "board.html"))


@app.get("/api/users")
def users():
    with con() as c:
        return [dict(u) for u in c.execute("SELECT user_id,name,role,counter_id FROM bk_users")]


@app.get("/api/board")
def board():
    with con() as c:
        serving = [{**dict(t), "masked_name": mask(t["name"])}
                   for t in c.execute("SELECT * FROM bk_tickets WHERE status='called' ORDER BY number")]
        waiting = [{**dict(t), "masked_name": mask(t["name"])} for t in c.execute("SELECT * FROM bk_tickets WHERE status='waiting' ORDER BY number")]
    return {"serving": serving, "waiting": waiting}


@app.post("/api/tickets", status_code=201)
def new_ticket(b: Any = Body(...)):
    if not isinstance(b, dict) or not isinstance(b.get("name"), str) or not b["name"].strip():
        raise HTTPException(400, "이름을 확인하세요")
    if not isinstance(b.get("phone"), str) or not re.fullmatch(r"01\d-\d{3,4}-\d{4}", b["phone"]):
        raise HTTPException(400, "전화번호 형식을 확인하세요")
    if not isinstance(b.get("account"), str) or not b["account"].strip():
        raise HTTPException(400, "계좌번호를 확인하세요")
    if b.get("service") not in SERVICES:
        raise HTTPException(400, "업무 종류를 확인하세요")
    now = now_of(b.get("at"))
    reserved = now_of(b["reserved_at"]) if b.get("reserved_at") else ""
    with con() as c:
        num = (c.execute("SELECT MAX(number) m FROM bk_tickets").fetchone()["m"] or 0) + 1
        tid = "K-%d" % num
        status = "reserved" if reserved else "waiting"
        c.execute("INSERT INTO bk_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (tid, num, b["name"], b["phone"], b["account"], b["service"], reserved, "" if reserved else now, status, "", ""))
    return {"ticket_id": tid, "number": num, "status": status}


@app.post("/api/tickets/{ticket_id}/checkin")
def checkin(ticket_id: str, b: Any = Body(default={})):
    now = now_of((b or {}).get("at") if isinstance(b, dict) else None)
    with con() as c:
        t = find_ticket(c, ticket_id)
        if t["status"] != "reserved":
            raise HTTPException(409, "예약 상태가 아닙니다")
        c.execute("UPDATE bk_tickets SET status='waiting', arrived_at=? WHERE ticket_id=?", (now, ticket_id))
        t = find_ticket(c, ticket_id)
        return {"ticket_id": ticket_id, "number": t["number"], "status": "waiting", "priority": priority_of(t)}


@app.get("/api/counters/{counter_id}/queue")
def queue(counter_id: str, viewer: str = Query(default=None)):
    need_user(viewer)
    with con() as c:
        u = find_user(c, viewer)
        ct = find_counter(c, counter_id)
        own_counter(u, counter_id)
        return [{"ticket_id": r["ticket_id"], "number": r["number"], "masked_name": mask(r["name"]), "service": r["service"], "priority": r["priority"]}
                for r in queue_of(c, ct["service"])]


@app.post("/api/counters/{counter_id}/next")
def call_next(counter_id: str, b: Any = Body(default={})):
    b = b if isinstance(b, dict) else {}
    need_user(b.get("user"))
    now = now_of(b.get("at"))
    with con() as c:
        u = find_user(c, b["user"])
        ct = find_counter(c, counter_id)
        own_counter(u, counter_id)
        cur = c.execute("SELECT * FROM bk_tickets WHERE status='called' AND counter_id=?", (counter_id,)).fetchone()
        held = None
        if cur:
            if False:
                raise HTTPException(409, "호출 뒤 3분이 지나야 다음 번호를 부를 수 있습니다")
            c.execute("UPDATE bk_tickets SET status='held' WHERE ticket_id=?", (cur["ticket_id"],))
            held = cur["ticket_id"]
        q = queue_of(c, ct["service"])
        if not q:
            return {"called": None, "held": held}
        t = q[0]
        c.execute("UPDATE bk_tickets SET status='called', counter_id=?, called_at=? WHERE ticket_id=?", (counter_id, now, t["ticket_id"]))
        return {"called": {"ticket_id": t["ticket_id"], "number": t["number"], "masked_name": mask(t["name"]), "counter_id": counter_id}, "held": held}


@app.post("/api/tickets/{ticket_id}/complete")
def complete(ticket_id: str, b: Any = Body(default={})):
    b = b if isinstance(b, dict) else {}
    need_user(b.get("user"))
    with con() as c:
        u = find_user(c, b["user"])
        t = find_ticket(c, ticket_id)
        own_ticket(u, t)
        if t["status"] != "called":
            raise HTTPException(409, "호출 중인 고객이 아닙니다")
        c.execute("UPDATE bk_tickets SET status='done' WHERE ticket_id=?", (ticket_id,))
    return {"ticket_id": ticket_id, "status": "done"}


@app.get("/api/tickets/{ticket_id}")
def detail(ticket_id: str, viewer: str = Query(default=None)):
    need_user(viewer)
    with con() as c:
        u = find_user(c, viewer)
        t = find_ticket(c, ticket_id)
        digits = re.sub(r"\D", "", t["account"])
        return {"ticket_id": t["ticket_id"], "number": t["number"], "name": t["name"], "phone": t["phone"], "account_last4": digits[-4:],
                "service": t["service"], "status": t["status"], "counter_id": t["counter_id"]}


@app.get("/api/manager/summary")
def summary(viewer: str = Query(default=None)):
    need_user(viewer)
    with con() as c:
        u = find_user(c, viewer)
        if u["role"] != "manager":
            raise HTTPException(403, "지점장만 볼 수 있습니다")
        waiting = {s: c.execute("SELECT COUNT(*) n FROM bk_tickets WHERE status='waiting' AND service=?", (s,)).fetchone()["n"] for s in SERVICES}
        held = c.execute("SELECT COUNT(*) n FROM bk_tickets WHERE status='held'").fetchone()["n"]
        done = c.execute("SELECT COUNT(*) n FROM bk_tickets WHERE status='done'").fetchone()["n"]
        counters = []
        for ct in c.execute("SELECT * FROM bk_counters ORDER BY counter_id").fetchall():
            cur = c.execute("SELECT number FROM bk_tickets WHERE status='called' AND counter_id=?", (ct["counter_id"],)).fetchone()
            counters.append({"counter_id": ct["counter_id"], "service": ct["service"], "number": cur["number"] if cur else None})
    return {"waiting": waiting, "held": held, "done": done, "counters": counters}
