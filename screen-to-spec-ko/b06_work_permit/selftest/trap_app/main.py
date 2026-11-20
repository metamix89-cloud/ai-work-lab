# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수를 일부러 넣었다. 정해진 테스트만 떨어져야 채점기가 그 실수를 잡는 것이다.
실수: ① 허가에 끝 시각이 없다(만료 없음 — 승인만 됐으면 언제든 작업 시작) ② 신청자 본인도 승인 ③ 검토를 건너뛰고 승인(순서 없음)
      ④ 상충 검사 없음 ⑤ 점검 항목이 비어도 신청을 받음 ⑥ 현황판에 상충 경고 없음."""
import csv
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "permit.db")
app = FastAPI()
FMT = "%Y-%m-%d %H:%M"
TYPES = {"height": "고소 작업", "hot": "화기 작업", "confined": "밀폐 작업"}


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


def view(c, p):
    z = c.execute("SELECT name FROM wp_zones WHERE zone_id=?", (p["zone_id"],)).fetchone()
    u = c.execute("SELECT name FROM wp_users WHERE user_id=?", (p["requester_id"],)).fetchone()
    nz = lambda v: v if v else None   # noqa: E731
    vu = (datetime.strptime(p["approved_at"], FMT) + timedelta(hours=8)).strftime(FMT) if p["approved_at"] else None   # ① 적기만 하고 보지 않는다
    return {"permit_id": p["permit_id"], "work_type": p["work_type"], "work_type_name": TYPES.get(p["work_type"]), "zone_id": p["zone_id"], "zone_name": z["name"] if z else None,
            "requester_id": p["requester_id"], "requester_name": u["name"] if u else None, "start_at": p["start_at"], "end_at": p["end_at"], "status": p["status"],
            "checked": [x for x in (p["checked"] or "").split("|") if x], "reviewed_by": nz(p["reviewed_by"]), "approved_by": nz(p["approved_by"]), "approved_at": nz(p["approved_at"]),
            "valid_until": vu, "started_at": nz(p["started_at"]), "closed_at": nz(p["closed_at"])}


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>뚝딱건설 위험 작업 허가서</h1><select data-testid='user'><option value='w1'>김작업</option><option value='s1'>박안전</option><option value='m1'>최소장</option></select></body></html>"


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM wp_users ORDER BY rowid")]


@app.get("/api/work-types")
def work_types():
    c = con()
    return [{"work_type": k, "name": v, "items": [{"item_id": i["item_id"], "name": i["name"]} for i in c.execute("SELECT * FROM wp_check_items WHERE work_type=? ORDER BY rowid", (k,))]} for k, v in TYPES.items()]


@app.get("/api/zones")
def zones():
    return [dict(z) for z in con().execute("SELECT * FROM wp_zones ORDER BY rowid")]


@app.get("/api/permits")
def permits(viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    u = find_user(c, viewer)
    rows = c.execute("SELECT * FROM wp_permits WHERE requester_id=? ORDER BY start_at, permit_id", (viewer,)) if u["role"] == "worker" else c.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id")
    return [view(c, p) for p in rows.fetchall()]


@app.get("/api/permits/{pid}")
def permit(pid: str, viewer: str = Query(default="")):
    need_user(viewer)
    c = con()
    p = find_permit(c, pid)
    u = find_user(c, viewer)
    if u["role"] == "worker" and p["requester_id"] != viewer:
        raise HTTPException(403, "본인 허가만 볼 수 있습니다")
    return view(c, p)


@app.post("/api/permits", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    wt = body.get("work_type")
    if wt not in TYPES:
        raise HTTPException(400, "작업 종류를 확인하세요")
    try:
        s, e = datetime.strptime(body.get("start_at"), FMT), datetime.strptime(body.get("end_at"), FMT)
    except (TypeError, ValueError):
        raise HTTPException(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
    if e <= s:
        raise HTTPException(400, "종료 시각이 시작 시각보다 앞입니다")
    c = con()
    find_user(c, body["user"])
    if not c.execute("SELECT 1 FROM wp_zones WHERE zone_id=?", (body.get("zone_id"),)).fetchone():
        raise HTTPException(404, "구역이 없습니다")
    mx = max([int(r[0][3:]) for r in c.execute("SELECT permit_id FROM wp_permits")] or [0])
    pid = "WP-%04d" % (mx + 1)
    c.execute("INSERT INTO wp_permits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (pid, wt, body["zone_id"], body["user"], body["start_at"], body["end_at"], "requested", "|".join(body.get("checked") or []), "", "", "", "", ""))   # ⑤
    c.commit()
    return view(c, find_permit(c, pid))


def action(pid, body, what):
    need_user(body.get("user"))
    c = con()
    p = find_permit(c, pid)
    u = find_user(c, body["user"])
    now = datetime.now().strftime(FMT)
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
        if p["status"] not in ("requested", "reviewed"):      # ② 본인도 ③ 검토 전에도 ④ 상충도 그냥
            raise HTTPException(409, "승인할 상태가 아닙니다")
        c.execute("UPDATE wp_permits SET status='approved', approved_by=?, approved_at=? WHERE permit_id=?", (u["user_id"], now, pid))
        c.commit()
        return {"permit_id": pid, "status": "approved", "approved_by": u["user_id"], "approved_at": now, "valid_until": (datetime.now() + timedelta(hours=8)).strftime(FMT)}
    if what == "start":
        if p["requester_id"] != u["user_id"]:
            raise HTTPException(403, "신청자만 작업을 시작할 수 있습니다")
        if p["status"] in ("requested", "reviewed"):
            raise HTTPException(409, "승인 전에는 작업을 시작할 수 없습니다")
        if p["status"] != "approved":
            raise HTTPException(409, "이미 시작한 작업입니다")
        c.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (now, pid))   # ① 만료를 안 본다
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
    rows = [p for p in c.execute("SELECT * FROM wp_permits WHERE status<>'closed' ORDER BY start_at") if p["start_at"] < day1 and p["end_at"] > day0]
    zs = [{"zone_id": z["zone_id"], "name": z["name"], "permits": [{"permit_id": p["permit_id"], "work_type": p["work_type"], "status": p["status"], "start_at": p["start_at"], "end_at": p["end_at"], "requester_name": p["requester_id"]} for p in rows if p["zone_id"] == z["zone_id"]]}
          for z in c.execute("SELECT * FROM wp_zones ORDER BY rowid")]
    return {"date": now.strftime("%Y-%m-%d"), "hours": list(range(6, 19)), "zones": zs, "conflicts": []}   # ⑥
