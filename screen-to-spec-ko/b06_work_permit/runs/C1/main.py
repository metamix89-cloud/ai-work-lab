# -*- coding: utf-8 -*-
"""뚝딱건설 해뜰현장 「위험 작업 허가서」 — FastAPI + SQLite. 규칙은 PRD.md 6 (R1~R8)."""
import csv
import os
import re
import sqlite3
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "permit.db")
STATIC = os.path.join(BASE, "static")
FMT = "%Y-%m-%d %H:%M"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
WORK_TYPES = {"height": "고소 작업", "hot": "화기 작업", "confined": "밀폐 작업"}
ROLES = ("worker", "safety", "manager")

app = FastAPI()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail


@app.exception_handler(Reject)
async def _reject(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


# ── DB ────────────────────────────────────────────────────────────────────────
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = db()
    con.executescript("""
        CREATE TABLE wp_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT, ord INTEGER);
        CREATE TABLE wp_zones (zone_id TEXT PRIMARY KEY, name TEXT, ord INTEGER);
        CREATE TABLE wp_check_items (work_type TEXT, item_id TEXT, name TEXT, ord INTEGER);
        CREATE TABLE wp_permits (permit_id TEXT PRIMARY KEY, work_type TEXT, zone_id TEXT, requester_id TEXT,
            start_at TEXT, end_at TEXT, status TEXT, checked TEXT, reviewed_by TEXT, approved_by TEXT,
            approved_at TEXT, started_at TEXT, closed_at TEXT);
    """)
    for i, r in enumerate(read_csv("users.csv")):
        con.execute("INSERT INTO wp_users VALUES (?,?,?,?)", (r["user_id"], r["name"], r["role"], i))
    for i, r in enumerate(read_csv("zones.csv")):
        con.execute("INSERT INTO wp_zones VALUES (?,?,?)", (r["zone_id"], r["name"], i))
    for i, r in enumerate(read_csv("check_items.csv")):
        con.execute("INSERT INTO wp_check_items VALUES (?,?,?,?)", (r["work_type"], r["item_id"], r["name"], i))
    for r in read_csv("permits.csv"):
        con.execute("INSERT INTO wp_permits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r["permit_id"], r["work_type"], r["zone_id"], r["requester_id"], r["start_at"], r["end_at"],
            r["status"], r["checked"], r["reviewed_by"] or None, r["approved_by"] or None,
            r["approved_at"] or None, r["started_at"] or None, r["closed_at"] or None))
    con.commit()
    con.close()


init_db()


# ── 도우미 ─────────────────────────────────────────────────────────────────────
def now():
    return datetime.now().replace(second=0, microsecond=0)


def parse(ts):
    return datetime.strptime(ts, FMT)


def valid_until(approved_at):
    if not approved_at:
        return None
    a = parse(approved_at)
    return min(a + timedelta(hours=8), a.replace(hour=23, minute=59)).strftime(FMT)


def is_expired(row):
    vu = valid_until(row["approved_at"])
    return row["status"] in ("approved", "started") and vu is not None and now().strftime(FMT) > vu


def eff_status(row):
    return "expired" if is_expired(row) else row["status"]


def is_active(row):
    """승인 · 작업 중이고 유효(만료 아님)"""
    return row["status"] in ("approved", "started") and not is_expired(row)


def is_hot_confined(a, b):
    return {a["work_type"], b["work_type"]} == {"hot", "confined"}


def overlap(a, b):
    return a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]


PERMIT_SQL = """SELECT p.*, z.name AS zone_name, u.name AS requester_name
                FROM wp_permits p LEFT JOIN wp_zones z ON z.zone_id = p.zone_id
                LEFT JOIN wp_users u ON u.user_id = p.requester_id"""


def serialize(r):
    return {
        "permit_id": r["permit_id"], "work_type": r["work_type"],
        "work_type_name": WORK_TYPES.get(r["work_type"], r["work_type"]),
        "zone_id": r["zone_id"], "zone_name": r["zone_name"],
        "requester_id": r["requester_id"], "requester_name": r["requester_name"],
        "start_at": r["start_at"], "end_at": r["end_at"], "status": eff_status(r),
        "checked": [x for x in (r["checked"] or "").split("|") if x],
        "reviewed_by": r["reviewed_by"], "approved_by": r["approved_by"],
        "approved_at": r["approved_at"], "valid_until": valid_until(r["approved_at"]),
        "started_at": r["started_at"], "closed_at": r["closed_at"],
    }


def need_text(v):
    if not isinstance(v, str) or not v.strip():
        raise Reject(400, "사용자를 확인하세요")
    return v.strip()


def find_user(con, uid):
    u = con.execute("SELECT * FROM wp_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise Reject(404, "없는 사용자입니다")
    return u


def find_permit(con, pid):
    p = con.execute(PERMIT_SQL + " WHERE p.permit_id=?", (pid,)).fetchone()
    if not p:
        raise Reject(404, "없는 허가입니다")
    return p


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        b = None
    return b if isinstance(b, dict) else {}


# ── 화면 ──────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), media_type="text/html; charset=utf-8")


# ── 조회 API ──────────────────────────────────────────────────────────────────
@app.get("/api/users")
def users():
    con = db()
    rows = con.execute("SELECT user_id, name, role FROM wp_users ORDER BY ord").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/work-types")
def work_types():
    con = db()
    out = []
    for wt, name in WORK_TYPES.items():
        items = con.execute("SELECT item_id, name FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,)).fetchall()
        out.append({"work_type": wt, "name": name, "items": [dict(i) for i in items]})
    con.close()
    return out


@app.get("/api/zones")
def zones():
    con = db()
    rows = con.execute("SELECT zone_id, name FROM wp_zones ORDER BY ord").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/permits")
def list_permits(viewer: str = None):
    viewer = need_text(viewer)
    con = db()
    try:
        u = find_user(con, viewer)
        rows = con.execute(PERMIT_SQL + " ORDER BY p.start_at, p.permit_id").fetchall()
        if u["role"] == "worker":
            rows = [r for r in rows if r["requester_id"] == u["user_id"]]
        return [serialize(r) for r in rows]
    finally:
        con.close()


@app.get("/api/permits/{permit_id}")
def get_permit(permit_id: str, viewer: str = None):
    viewer = need_text(viewer)
    con = db()
    try:
        u = find_user(con, viewer)
        p = find_permit(con, permit_id)
        if u["role"] == "worker" and p["requester_id"] != u["user_id"]:
            raise Reject(403, "본인 허가만 볼 수 있습니다")
        return serialize(p)
    finally:
        con.close()


# ── 신청 ──────────────────────────────────────────────────────────────────────
@app.post("/api/permits", status_code=201)
async def create_permit(request: Request):
    b = await body_of(request)
    user = need_text(b.get("user"))
    wt = b.get("work_type")
    if not isinstance(wt, str) or wt not in WORK_TYPES:
        raise Reject(400, "작업 종류를 확인하세요")
    s, e = b.get("start_at"), b.get("end_at")
    for t in (s, e):
        ok = isinstance(t, str) and TS_RE.match(t)
        if ok:
            try:
                parse(t)
            except ValueError:
                ok = False
        if not ok:
            raise Reject(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
    if e <= s:
        raise Reject(400, "종료 시각이 시작 시각보다 앞입니다")
    con = db()
    try:
        find_user(con, user)
        zid = b.get("zone_id")
        if not isinstance(zid, str) or not con.execute("SELECT 1 FROM wp_zones WHERE zone_id=?", (zid,)).fetchone():
            raise Reject(404, "없는 구역입니다")
        items = con.execute("SELECT item_id, name FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,)).fetchall()
        checked = b.get("checked")
        if not isinstance(checked, list) or not all(isinstance(x, str) for x in checked):
            raise Reject(400, "점검 항목을 확인하세요")
        missing = [i["name"] for i in items if i["item_id"] not in checked]
        if missing:
            raise Reject(400, "필수 점검 항목이 비었습니다 (%s)" % ", ".join(missing))
        if any(x not in {i["item_id"] for i in items} for x in checked):
            raise Reject(400, "점검 항목을 확인하세요")
        nums = [int(m.group(1)) for (pid,) in con.execute("SELECT permit_id FROM wp_permits") if (m := re.fullmatch(r"WP-(\d+)", pid))]
        pid = "WP-%04d" % (max(nums) + 1 if nums else 1)
        ordered = "|".join(i["item_id"] for i in items)
        con.execute("INSERT INTO wp_permits (permit_id, work_type, zone_id, requester_id, start_at, end_at, status, checked) "
                    "VALUES (?,?,?,?,?,?,?,?)", (pid, wt, zid, user, s, e, "requested", ordered))
        con.commit()
        return JSONResponse(serialize(find_permit(con, pid)), status_code=201)
    finally:
        con.close()


# ── 검토 · 승인 · 시작 · 종료 ─────────────────────────────────────────────────
async def prepare(request, permit_id):
    b = await body_of(request)
    user = need_text(b.get("user"))
    con = db()
    try:
        u = find_user(con, user)
        p = find_permit(con, permit_id)
    except Exception:
        con.close()
        raise
    return con, u, p


@app.post("/api/permits/{permit_id}/review")
async def review(permit_id: str, request: Request):
    con, u, p = await prepare(request, permit_id)
    try:
        if u["role"] != "safety":
            raise Reject(403, "안전 담당만 검토할 수 있습니다")
        if p["status"] != "requested":
            raise Reject(409, "검토할 상태가 아닙니다")
        con.execute("UPDATE wp_permits SET status='reviewed', reviewed_by=? WHERE permit_id=?", (u["user_id"], permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "reviewed", "reviewed_by": u["user_id"]}
    finally:
        con.close()


@app.post("/api/permits/{permit_id}/approve")
async def approve(permit_id: str, request: Request):
    con, u, p = await prepare(request, permit_id)
    try:
        if u["role"] != "manager":
            raise Reject(403, "현장 책임자만 승인할 수 있습니다")
        if p["requester_id"] == u["user_id"]:
            raise Reject(403, "자기 허가는 승인할 수 없습니다")
        if p["status"] == "requested":
            raise Reject(409, "검토 전에는 승인할 수 없습니다")
        if p["status"] != "reviewed":
            raise Reject(409, "승인할 상태가 아닙니다")
        for o in con.execute(PERMIT_SQL + " WHERE p.zone_id=? AND p.permit_id<>?", (p["zone_id"], permit_id)).fetchall():
            if is_active(o) and overlap(p, o) and is_hot_confined(p, o):
                raise Reject(409, "같은 구역에 상충 작업이 있습니다 (%s)" % o["permit_id"])
        at = now().strftime(FMT)
        con.execute("UPDATE wp_permits SET status='approved', approved_by=?, approved_at=? WHERE permit_id=?",
                    (u["user_id"], at, permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "approved", "approved_by": u["user_id"],
                "approved_at": at, "valid_until": valid_until(at)}
    finally:
        con.close()


@app.post("/api/permits/{permit_id}/start")
async def start(permit_id: str, request: Request):
    con, u, p = await prepare(request, permit_id)
    try:
        if p["requester_id"] != u["user_id"]:
            raise Reject(403, "신청자만 작업을 시작할 수 있습니다")
        st = p["status"]
        if st in ("requested", "reviewed"):
            raise Reject(409, "승인 전에는 작업을 시작할 수 없습니다")
        if st == "started":
            raise Reject(409, "이미 시작한 작업입니다")
        if st == "closed":
            raise Reject(409, "종료된 허가입니다")
        if st != "approved":
            raise Reject(409, "작업을 시작할 상태가 아닙니다")
        if is_expired(p):
            raise Reject(409, "허가가 만료되었습니다")
        at = now().strftime(FMT)
        con.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (at, permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "started", "started_at": at}
    finally:
        con.close()


@app.post("/api/permits/{permit_id}/close")
async def close(permit_id: str, request: Request):
    con, u, p = await prepare(request, permit_id)
    try:
        if u["user_id"] not in (p["requester_id"], p["approved_by"]):
            raise Reject(403, "신청자 또는 승인자만 종료할 수 있습니다")
        if p["status"] != "started":
            raise Reject(409, "시작한 작업만 종료할 수 있습니다")
        at = now().strftime(FMT)
        con.execute("UPDATE wp_permits SET status='closed', closed_at=? WHERE permit_id=?", (at, permit_id))
        con.commit()
        return {"permit_id": permit_id, "status": "closed", "closed_at": at}
    finally:
        con.close()


# ── 현황판 ────────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard(viewer: str = None):
    viewer = need_text(viewer)
    con = db()
    try:
        u = find_user(con, viewer)
        if u["role"] not in ("safety", "manager"):
            raise Reject(403, "현황판은 안전 담당과 현장 책임자만 볼 수 있습니다")
        today = now().replace(hour=0, minute=0)
        d0, d1 = today.strftime(FMT), (today + timedelta(days=1)).strftime(FMT)
        rows = [r for r in con.execute(PERMIT_SQL + " ORDER BY p.start_at, p.permit_id").fetchall()
                if r["status"] != "closed" and r["start_at"] < d1 and r["end_at"] > d0]
        zs = []
        for z in con.execute("SELECT zone_id, name FROM wp_zones ORDER BY ord").fetchall():
            zs.append({"zone_id": z["zone_id"], "name": z["name"], "permits": [
                {"permit_id": r["permit_id"], "work_type": r["work_type"], "status": eff_status(r),
                 "start_at": r["start_at"], "end_at": r["end_at"], "requester_name": r["requester_name"]}
                for r in rows if r["zone_id"] == z["zone_id"]]})
        conflicts = []
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a["zone_id"] != b["zone_id"] or not overlap(a, b) or not is_hot_confined(a, b):
                    continue
                if is_active(a) or is_active(b):
                    conflicts.append({"zone_id": a["zone_id"], "permit_ids": sorted([a["permit_id"], b["permit_id"]])})
        return {"date": today.strftime("%Y-%m-%d"), "hours": list(range(6, 19)), "zones": zs, "conflicts": conflicts}
    finally:
        con.close()
