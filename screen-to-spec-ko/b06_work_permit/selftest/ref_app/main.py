# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R8 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
상태 기계 requested → reviewed → approved → started → closed · 유효 = 승인 + 8시간(당일 23:59 상한) · 만료는 서버 시계 · 본인 승인 403 · 화기 × 밀폐 상충 409."""
import csv
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "permit.db")
LOCK = threading.Lock()
app = FastAPI()
FMT = "%Y-%m-%d %H:%M"
VALID_HOURS = 8
TYPES = {"height": "고소 작업", "hot": "화기 작업", "confined": "밀폐 작업"}
CONFLICT_PAIR = {"hot", "confined"}
PERMIT_COLS = ["permit_id", "work_type", "zone_id", "requester_id", "start_at", "end_at", "status", "checked", "reviewed_by", "approved_by", "approved_at", "started_at", "closed_at"]


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE wp_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE wp_zones(zone_id TEXT PRIMARY KEY, name TEXT);
    CREATE TABLE wp_check_items(work_type TEXT, item_id TEXT, name TEXT);
    CREATE TABLE wp_permits(permit_id TEXT PRIMARY KEY, work_type TEXT, zone_id TEXT, requester_id TEXT, start_at TEXT, end_at TEXT, status TEXT,
                            checked TEXT, reviewed_by TEXT, approved_by TEXT, approved_at TEXT, started_at TEXT, closed_at TEXT);""")
    for name, table, n in (("users.csv", "wp_users", 3), ("zones.csv", "wp_zones", 2), ("check_items.csv", "wp_check_items", 3), ("permits.csv", "wp_permits", 13)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def now_str():
    return datetime.now().strftime(FMT)


def parse(ts):
    return datetime.strptime(ts, FMT)


def valid_until_of(approved_at):
    a = parse(approved_at)
    return min(a + timedelta(hours=VALID_HOURS), a.replace(hour=23, minute=59)).strftime(FMT)


def need_user(uid):
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, "사용자를 확인하세요")


def find_user(c, uid):
    u = c.execute("SELECT * FROM wp_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    return u


def find_permit(c, pid):
    p = c.execute("SELECT * FROM wp_permits WHERE permit_id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "허가가 없습니다")
    return p


def shown_status(p, now=None):
    """응답의 status — 승인 · 작업 중인데 valid_until 이 지났으면 expired"""
    now = now or datetime.now()
    if p["status"] in ("approved", "started") and p["approved_at"]:
        if now > parse(valid_until_of(p["approved_at"])):
            return "expired"
    return p["status"]


def is_active(p, now=None):
    """상충 검사의 상대 — 승인 · 작업 중이고 유효"""
    return p["status"] in ("approved", "started") and shown_status(p, now) != "expired"


def view(c, p):
    z = c.execute("SELECT name FROM wp_zones WHERE zone_id=?", (p["zone_id"],)).fetchone()
    u = c.execute("SELECT name FROM wp_users WHERE user_id=?", (p["requester_id"],)).fetchone()
    nz = lambda v: v if v else None   # noqa: E731
    return {"permit_id": p["permit_id"], "work_type": p["work_type"], "work_type_name": TYPES.get(p["work_type"], p["work_type"]),
            "zone_id": p["zone_id"], "zone_name": z["name"] if z else None, "requester_id": p["requester_id"], "requester_name": u["name"] if u else p["requester_id"],
            "start_at": p["start_at"], "end_at": p["end_at"], "status": shown_status(p), "checked": [x for x in (p["checked"] or "").split("|") if x],
            "reviewed_by": nz(p["reviewed_by"]), "approved_by": nz(p["approved_by"]), "approved_at": nz(p["approved_at"]),
            "valid_until": valid_until_of(p["approved_at"]) if p["approved_at"] else None, "started_at": nz(p["started_at"]), "closed_at": nz(p["closed_at"])}


def overlaps(a, b):
    return a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]


def conflict_with(c, p, now=None):
    """같은 구역 · 겹침 · 화기와 밀폐의 짝 · 상대는 승인 · 작업 중이고 유효 — 있으면 상대 허가"""
    for o in c.execute("SELECT * FROM wp_permits WHERE zone_id=? AND permit_id<>?", (p["zone_id"], p["permit_id"])):
        if is_active(o, now) and overlaps(p, o) and {p["work_type"], o["work_type"]} == CONFLICT_PAIR:
            return o
    return None


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM wp_users ORDER BY rowid")]


@app.get("/api/work-types")
def work_types():
    c = con()
    return [{"work_type": k, "name": v, "items": [{"item_id": i["item_id"], "name": i["name"]} for i in c.execute("SELECT * FROM wp_check_items WHERE work_type=? ORDER BY rowid", (k,))]}
            for k, v in TYPES.items()]


@app.get("/api/zones")
def zones():
    return [dict(z) for z in con().execute("SELECT * FROM wp_zones ORDER BY rowid")]


@app.get("/api/permits")
def permits(viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    u = find_user(c, viewer)
    q = "SELECT * FROM wp_permits"
    rows = c.execute(q + " WHERE requester_id=? ORDER BY start_at, permit_id", (viewer,)) if u["role"] == "worker" else c.execute(q + " ORDER BY start_at, permit_id")
    return [view(c, p) for p in rows.fetchall()]


@app.get("/api/permits/{pid}")
def permit(pid: str, viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    p = find_permit(c, pid)
    u = find_user(c, viewer)
    if u["role"] == "worker" and p["requester_id"] != u["user_id"]:
        raise HTTPException(403, "본인 허가만 볼 수 있습니다")
    return view(c, p)


@app.post("/api/permits", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    # 본문만 보고 아는 400 → 404 → 점검 항목표를 찾아야 아는 400 (R8)
    need_user(body.get("user"))
    wt = body.get("work_type")
    if wt not in TYPES:
        raise HTTPException(400, "작업 종류를 확인하세요")
    start, end = body.get("start_at"), body.get("end_at")
    try:
        s, e = parse(start), parse(end)
    except (TypeError, ValueError):
        raise HTTPException(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
    if e <= s:
        raise HTTPException(400, "종료 시각이 시작 시각보다 앞입니다")
    checked = body.get("checked") or []
    if not isinstance(checked, list) or not all(isinstance(x, str) for x in checked):
        raise HTTPException(400, "점검 항목을 확인하세요")
    with LOCK:
        c = con()
        find_user(c, body["user"])
        if not c.execute("SELECT 1 FROM wp_zones WHERE zone_id=?", (body.get("zone_id"),)).fetchone():
            raise HTTPException(404, "구역이 없습니다")
        items = c.execute("SELECT item_id, name FROM wp_check_items WHERE work_type=? ORDER BY rowid", (wt,)).fetchall()
        ids = {i["item_id"] for i in items}
        if set(checked) - ids:
            raise HTTPException(400, "점검 항목을 확인하세요")
        for i in items:
            if i["item_id"] not in checked:
                raise HTTPException(400, "필수 점검 항목이 비었습니다 (%s)" % i["name"])
        mx = max([int(r[0][3:]) for r in c.execute("SELECT permit_id FROM wp_permits") if r[0].startswith("WP-") and r[0][3:].isdigit()] or [0])
        pid = "WP-%04d" % (mx + 1)
        c.execute("INSERT INTO wp_permits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (pid, wt, body["zone_id"], body["user"], start, end, "requested", "|".join(i["item_id"] for i in items), "", "", "", "", ""))
        c.commit()
        return view(c, find_permit(c, pid))


def action(pid, body, what):
    need_user(body.get("user"))
    with LOCK:
        c = con()
        p = find_permit(c, pid)
        u = find_user(c, body["user"])
        now = now_str()
        if what == "review":
            if u["role"] != "safety":
                raise HTTPException(403, "안전 담당만 검토할 수 있습니다")
            if p["status"] != "requested":
                raise HTTPException(409, "검토할 상태가 아닙니다")
            c.execute("UPDATE wp_permits SET status='reviewed', reviewed_by=? WHERE permit_id=?", (u["user_id"], pid))
            c.commit()
            return {"permit_id": pid, "status": "reviewed", "reviewed_by": u["user_id"]}
        if what == "approve":
            if u["role"] != "manager":
                raise HTTPException(403, "현장 책임자만 승인할 수 있습니다")
            if p["requester_id"] == u["user_id"]:
                raise HTTPException(403, "자기 허가는 승인할 수 없습니다")
            if p["status"] == "requested":
                raise HTTPException(409, "검토 전에는 승인할 수 없습니다")
            if p["status"] != "reviewed":
                raise HTTPException(409, "승인할 상태가 아닙니다")
            o = conflict_with(c, p)
            if o:
                raise HTTPException(409, "같은 구역에 상충 작업이 있습니다 (%s)" % o["permit_id"])
            c.execute("UPDATE wp_permits SET status='approved', approved_by=?, approved_at=? WHERE permit_id=?", (u["user_id"], now, pid))
            c.commit()
            return {"permit_id": pid, "status": "approved", "approved_by": u["user_id"], "approved_at": now, "valid_until": valid_until_of(now)}
        if what == "start":
            if p["requester_id"] != u["user_id"]:
                raise HTTPException(403, "신청자만 작업을 시작할 수 있습니다")
            if p["status"] in ("requested", "reviewed"):
                raise HTTPException(409, "승인 전에는 작업을 시작할 수 없습니다")
            if p["status"] == "started":
                raise HTTPException(409, "이미 시작한 작업입니다")
            if p["status"] == "closed":
                raise HTTPException(409, "종료된 허가입니다")
            if shown_status(p) == "expired":
                raise HTTPException(409, "허가가 만료되었습니다")
            c.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (now, pid))
            c.commit()
            return {"permit_id": pid, "status": "started", "started_at": now}
        if what == "close":
            if u["user_id"] not in (p["requester_id"], p["approved_by"]):
                raise HTTPException(403, "신청자 또는 승인자만 종료할 수 있습니다")
            if p["status"] != "started":
                raise HTTPException(409, "시작한 작업만 종료할 수 있습니다")
            c.execute("UPDATE wp_permits SET status='closed', closed_at=? WHERE permit_id=?", (now, pid))
            c.commit()
            return {"permit_id": pid, "status": "closed", "closed_at": now}


@app.post("/api/permits/{pid}/review")
def review(pid: str, body: dict[str, Any] = Body(default={})):
    return action(pid, body, "review")


@app.post("/api/permits/{pid}/approve")
def approve(pid: str, body: dict[str, Any] = Body(default={})):
    return action(pid, body, "approve")


@app.post("/api/permits/{pid}/start")
def start(pid: str, body: dict[str, Any] = Body(default={})):
    return action(pid, body, "start")


@app.post("/api/permits/{pid}/close")
def close(pid: str, body: dict[str, Any] = Body(default={})):
    return action(pid, body, "close")


@app.get("/api/dashboard")
def dashboard(viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    u = find_user(c, viewer)
    if u["role"] == "worker":
        raise HTTPException(403, "현황판은 안전 담당과 현장 책임자만 볼 수 있습니다")
    now = datetime.now()
    day0 = now.replace(hour=0, minute=0).strftime(FMT)
    day1 = (now.replace(hour=0, minute=0) + timedelta(days=1)).strftime(FMT)
    rows = [p for p in c.execute("SELECT * FROM wp_permits WHERE status<>'closed' ORDER BY start_at, permit_id") if p["start_at"] < day1 and p["end_at"] > day0]
    names = {r["user_id"]: r["name"] for r in c.execute("SELECT user_id, name FROM wp_users")}
    zones_out = []
    for z in c.execute("SELECT * FROM wp_zones ORDER BY rowid"):
        zones_out.append({"zone_id": z["zone_id"], "name": z["name"],
                          "permits": [{"permit_id": p["permit_id"], "work_type": p["work_type"], "status": shown_status(p, now), "start_at": p["start_at"], "end_at": p["end_at"],
                                       "requester_name": names.get(p["requester_id"], p["requester_id"])} for p in rows if p["zone_id"] == z["zone_id"]]})
    conflicts, seen = [], set()
    allp = c.execute("SELECT * FROM wp_permits WHERE status<>'closed'").fetchall()
    for a in allp:
        if not is_active(a, now):
            continue
        for b in allp:
            if b["permit_id"] == a["permit_id"] or b["zone_id"] != a["zone_id"]:
                continue
            if overlaps(a, b) and {a["work_type"], b["work_type"]} == CONFLICT_PAIR:
                key = tuple(sorted((a["permit_id"], b["permit_id"])))
                if key not in seen:
                    seen.add(key)
                    conflicts.append({"zone_id": a["zone_id"], "permit_ids": list(key)})
    return {"date": now.strftime("%Y-%m-%d"), "hours": list(range(6, 19)), "zones": zones_out, "conflicts": conflicts}
