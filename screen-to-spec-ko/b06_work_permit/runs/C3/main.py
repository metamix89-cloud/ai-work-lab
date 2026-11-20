# -*- coding: utf-8 -*-
"""뚝딱건설 해뜰현장 「위험 작업 허가서」 — FastAPI + SQLite. PRD.md 참고."""
import csv
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "permit.db")
INDEX = os.path.join(BASE, "static", "index.html")
FMT = "%Y-%m-%d %H:%M"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
WORK_TYPES = [("height", "고소 작업"), ("hot", "화기 작업"), ("confined", "밀폐 작업")]
WORK_TYPE_NAMES = dict(WORK_TYPES)
LOCK = threading.RLock()

app = FastAPI()


# ── DB ───────────────────────────────────────────────────────────────────────
def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def calc_valid_until(approved_at):
    a = datetime.strptime(approved_at, FMT)
    return min(a + timedelta(hours=8), a.replace(hour=23, minute=59)).strftime(FMT)


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE wp_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE wp_zones (zone_id TEXT PRIMARY KEY, name TEXT, ord INTEGER);
        CREATE TABLE wp_check_items (work_type TEXT, item_id TEXT, name TEXT, ord INTEGER);
        CREATE TABLE wp_permits (
            permit_id TEXT PRIMARY KEY, work_type TEXT, zone_id TEXT, requester_id TEXT,
            start_at TEXT, end_at TEXT, status TEXT, checked TEXT,
            reviewed_by TEXT, approved_by TEXT, approved_at TEXT, valid_until TEXT,
            started_at TEXT, closed_at TEXT);
        """
    )
    con.executemany("INSERT INTO wp_users VALUES (?,?,?)",
                    [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    con.executemany("INSERT INTO wp_zones VALUES (?,?,?)",
                    [(r["zone_id"], r["name"], i) for i, r in enumerate(read_csv("zones.csv"))])
    con.executemany("INSERT INTO wp_check_items VALUES (?,?,?,?)",
                    [(r["work_type"], r["item_id"], r["name"], i) for i, r in enumerate(read_csv("check_items.csv"))])
    for r in read_csv("permits.csv"):
        def v(k):
            return (r.get(k) or "").strip() or None
        approved_at = v("approved_at")
        valid_until = None
        if approved_at:
            try:
                valid_until = calc_valid_until(approved_at)
            except ValueError:
                valid_until = None
        con.execute("INSERT INTO wp_permits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (v("permit_id"), v("work_type"), v("zone_id"), v("requester_id"), v("start_at"), v("end_at"),
                     v("status"), v("checked") or "", v("reviewed_by"), v("approved_by"), approved_at, valid_until,
                     v("started_at"), v("closed_at")))
    con.commit()
    con.close()


init_db()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ── 공통 ─────────────────────────────────────────────────────────────────────
def now_str():
    return datetime.now().replace(second=0, microsecond=0).strftime(FMT)


def fail(code, detail):
    raise HTTPException(status_code=code, detail=detail)


async def body_of(request):
    try:
        data = json.loads((await request.body()) or b"{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def need_user_id(v):
    if not isinstance(v, str) or not v.strip():
        fail(400, "사용자를 확인하세요")
    return v


def find_user(con, user_id):
    u = con.execute("SELECT * FROM wp_users WHERE user_id=?", (user_id,)).fetchone()
    if not u:
        fail(404, "사용자를 찾을 수 없습니다")
    return u


def find_permit(con, permit_id):
    p = con.execute("SELECT * FROM wp_permits WHERE permit_id=?", (permit_id,)).fetchone()
    if not p:
        fail(404, "허가를 찾을 수 없습니다")
    return p


def is_expired(p, now=None):
    """승인 · 작업 중인데 지금이 valid_until 을 지났으면 만료 (같은 분까지는 유효)."""
    return p["status"] in ("approved", "started") and bool(p["valid_until"]) and (now or now_str()) > p["valid_until"]


def is_live(p, now=None):
    """승인 · 작업 중이고 유효."""
    return p["status"] in ("approved", "started") and not is_expired(p, now)


def shown_status(p, now=None):
    return "expired" if is_expired(p, now) else p["status"]


def permit_json(con, p, now=None):
    names = {r["user_id"]: r["name"] for r in con.execute("SELECT user_id, name FROM wp_users")}
    zone = con.execute("SELECT name FROM wp_zones WHERE zone_id=?", (p["zone_id"],)).fetchone()
    return {
        "permit_id": p["permit_id"],
        "work_type": p["work_type"],
        "work_type_name": WORK_TYPE_NAMES.get(p["work_type"], p["work_type"]),
        "zone_id": p["zone_id"],
        "zone_name": zone["name"] if zone else None,
        "requester_id": p["requester_id"],
        "requester_name": names.get(p["requester_id"]),
        "start_at": p["start_at"],
        "end_at": p["end_at"],
        "status": shown_status(p, now),
        "checked": [c for c in (p["checked"] or "").split("|") if c],
        "reviewed_by": p["reviewed_by"],
        "approved_by": p["approved_by"],
        "approved_at": p["approved_at"],
        "valid_until": p["valid_until"],
        "started_at": p["started_at"],
        "closed_at": p["closed_at"],
    }


def is_conflict_pair(a, b):
    return (a["zone_id"] == b["zone_id"]
            and a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]
            and {a["work_type"], b["work_type"]} == {"hot", "confined"})


# ── 화면 · 기초 목록 ─────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(INDEX, media_type="text/html; charset=utf-8")


@app.get("/api/users")
def users():
    with LOCK, db() as con:
        return [{"user_id": r["user_id"], "name": r["name"], "role": r["role"]}
                for r in con.execute("SELECT * FROM wp_users")]


@app.get("/api/work-types")
def work_types():
    with LOCK, db() as con:
        out = []
        for wt, name in WORK_TYPES:
            items = [{"item_id": r["item_id"], "name": r["name"]}
                     for r in con.execute("SELECT * FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,))]
            out.append({"work_type": wt, "name": name, "items": items})
        return out


@app.get("/api/zones")
def zones():
    with LOCK, db() as con:
        return [{"zone_id": r["zone_id"], "name": r["name"]}
                for r in con.execute("SELECT * FROM wp_zones ORDER BY ord")]


# ── 허가 조회 ────────────────────────────────────────────────────────────────
@app.get("/api/permits")
def list_permits(viewer: str = None):
    need_user_id(viewer)
    with LOCK, db() as con:
        u = find_user(con, viewer)
        rows = con.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id").fetchall()
        now = now_str()
        return [permit_json(con, p, now) for p in rows
                if u["role"] != "worker" or p["requester_id"] == u["user_id"]]


@app.get("/api/permits/{permit_id}")
def get_permit(permit_id: str, viewer: str = None):
    need_user_id(viewer)
    with LOCK, db() as con:
        u = find_user(con, viewer)
        p = find_permit(con, permit_id)
        if u["role"] == "worker" and p["requester_id"] != u["user_id"]:
            fail(403, "본인 허가만 볼 수 있습니다")
        return permit_json(con, p)


# ── 신청 ─────────────────────────────────────────────────────────────────────
def valid_ts(v):
    if not isinstance(v, str) or not TS_RE.match(v):
        return False
    try:
        datetime.strptime(v, FMT)
    except ValueError:
        return False
    return True


@app.post("/api/permits", status_code=201)
async def create_permit(request: Request):
    b = await body_of(request)
    need_user_id(b.get("user"))
    work_type = b.get("work_type")
    if not isinstance(work_type, str) or work_type not in WORK_TYPE_NAMES:
        fail(400, "작업 종류를 확인하세요")
    start_at, end_at = b.get("start_at"), b.get("end_at")
    if not valid_ts(start_at) or not valid_ts(end_at):
        fail(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
    if end_at <= start_at:
        fail(400, "종료 시각이 시작 시각보다 앞입니다")
    zone_id = b.get("zone_id")
    checked = b.get("checked")
    with LOCK, db() as con:
        u = find_user(con, b["user"])
        if not isinstance(zone_id, str) or not con.execute("SELECT 1 FROM wp_zones WHERE zone_id=?", (zone_id,)).fetchone():
            fail(404, "구역을 찾을 수 없습니다")
        items = con.execute("SELECT item_id, name FROM wp_check_items WHERE work_type=? ORDER BY ord", (work_type,)).fetchall()
        if not isinstance(checked, list) or not all(isinstance(c, str) for c in checked):
            checked = []
        missing = [i["name"] for i in items if i["item_id"] not in checked]
        if missing:
            fail(400, "필수 점검 항목이 비었습니다 (%s)" % ", ".join(missing))
        valid_ids = {i["item_id"] for i in items}
        if any(c not in valid_ids for c in checked):
            fail(400, "점검 항목을 확인하세요")
        nums = [int(m.group(1)) for (pid,) in con.execute("SELECT permit_id FROM wp_permits")
                for m in [re.fullmatch(r"WP-(\d+)", pid or "")] if m]
        pid = "WP-%04d" % (max(nums) + 1 if nums else 1)
        ordered = [i["item_id"] for i in items if i["item_id"] in checked]
        con.execute("INSERT INTO wp_permits (permit_id, work_type, zone_id, requester_id, start_at, end_at, status, checked) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (pid, work_type, zone_id, u["user_id"], start_at, end_at, "requested", "|".join(ordered)))
        con.commit()
        return JSONResponse(permit_json(con, find_permit(con, pid)), status_code=201)


# ── 검토 · 승인 · 시작 · 종료 ────────────────────────────────────────────────
async def load_for_action(request, permit_id, con):
    b = await body_of(request)
    need_user_id(b.get("user"))
    u = find_user(con, b["user"])
    p = find_permit(con, permit_id)
    return u, p


@app.post("/api/permits/{permit_id}/review")
async def review(permit_id: str, request: Request):
    with LOCK, db() as con:
        u, p = await load_for_action(request, permit_id, con)
        if u["role"] != "safety":
            fail(403, "안전 담당만 검토할 수 있습니다")
        if p["status"] != "requested":
            fail(409, "검토할 상태가 아닙니다")
        con.execute("UPDATE wp_permits SET status='reviewed', reviewed_by=? WHERE permit_id=?", (u["user_id"], permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "reviewed", "reviewed_by": u["user_id"]}


@app.post("/api/permits/{permit_id}/approve")
async def approve(permit_id: str, request: Request):
    with LOCK, db() as con:
        u, p = await load_for_action(request, permit_id, con)
        if u["role"] != "manager":
            fail(403, "현장 책임자만 승인할 수 있습니다")
        if p["requester_id"] == u["user_id"]:
            fail(403, "자기 허가는 승인할 수 없습니다")
        if p["status"] == "requested":
            fail(409, "검토 전에는 승인할 수 없습니다")
        if p["status"] != "reviewed":
            fail(409, "승인할 상태가 아닙니다")
        now = now_str()
        for o in con.execute("SELECT * FROM wp_permits WHERE permit_id<>? ORDER BY permit_id", (permit_id,)):
            if is_live(o, now) and is_conflict_pair(p, o):
                fail(409, "같은 구역에 상충 작업이 있습니다 (%s)" % o["permit_id"])
        valid_until = calc_valid_until(now)
        con.execute("UPDATE wp_permits SET status='approved', approved_by=?, approved_at=?, valid_until=? WHERE permit_id=?",
                    (u["user_id"], now, valid_until, permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "approved", "approved_by": u["user_id"],
                "approved_at": now, "valid_until": valid_until}


@app.post("/api/permits/{permit_id}/start")
async def start(permit_id: str, request: Request):
    with LOCK, db() as con:
        u, p = await load_for_action(request, permit_id, con)
        if p["requester_id"] != u["user_id"]:
            fail(403, "신청자만 작업을 시작할 수 있습니다")
        st = p["status"]
        if st in ("requested", "reviewed"):
            fail(409, "승인 전에는 작업을 시작할 수 없습니다")
        if st == "started":
            fail(409, "이미 시작한 작업입니다")
        if st == "closed":
            fail(409, "종료된 허가입니다")
        if is_expired(p):
            fail(409, "허가가 만료되었습니다")
        now = now_str()
        con.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (now, permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "started", "started_at": now}


@app.post("/api/permits/{permit_id}/close")
async def close(permit_id: str, request: Request):
    with LOCK, db() as con:
        u, p = await load_for_action(request, permit_id, con)
        if u["user_id"] not in (p["requester_id"], p["approved_by"]):
            fail(403, "신청자 또는 승인자만 종료할 수 있습니다")
        if p["status"] != "started":
            fail(409, "시작한 작업만 종료할 수 있습니다")
        now = now_str()
        con.execute("UPDATE wp_permits SET status='closed', closed_at=? WHERE permit_id=?", (now, permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "closed", "closed_at": now}


# ── 현황판 ───────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard(viewer: str = None):
    need_user_id(viewer)
    with LOCK, db() as con:
        u = find_user(con, viewer)
        if u["role"] == "worker":
            fail(403, "현황판은 안전 담당과 현장 책임자만 볼 수 있습니다")
        n = datetime.now()
        today = n.strftime("%Y-%m-%d")
        day0 = today + " 00:00"
        day1 = (n + timedelta(days=1)).strftime("%Y-%m-%d") + " 00:00"
        now = now_str()
        names = {r["user_id"]: r["name"] for r in con.execute("SELECT user_id, name FROM wp_users")}
        rows = [p for p in con.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id")
                if p["status"] != "closed" and p["start_at"] < day1 and p["end_at"] > day0]
        out_zones = []
        for z in con.execute("SELECT * FROM wp_zones ORDER BY ord"):
            out_zones.append({
                "zone_id": z["zone_id"], "name": z["name"],
                "permits": [{"permit_id": p["permit_id"], "work_type": p["work_type"], "status": shown_status(p, now),
                             "start_at": p["start_at"], "end_at": p["end_at"],
                             "requester_name": names.get(p["requester_id"])}
                            for p in rows if p["zone_id"] == z["zone_id"]]})
        conflicts = []
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if is_conflict_pair(a, b) and (is_live(a, now) or is_live(b, now)):
                    conflicts.append({"zone_id": a["zone_id"], "permit_ids": sorted([a["permit_id"], b["permit_id"]])})
        return {"date": today, "hours": list(range(6, 19)), "zones": out_zones, "conflicts": conflicts}
