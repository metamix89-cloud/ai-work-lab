# -*- coding: utf-8 -*-
"""뚝딱건설 해뜰현장 「위험 작업 허가서」 — FastAPI + SQLite."""
import csv
import os
import sqlite3
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "permit.db")
INDEX = os.path.join(BASE, "static", "index.html")
FMT = "%Y-%m-%d %H:%M"
LOCK = threading.RLock()

WORK_TYPES = [("height", "고소 작업"), ("hot", "화기 작업"), ("confined", "밀폐 작업")]
WT_NAME = dict(WORK_TYPES)
NEXT = {"requested": "reviewed", "reviewed": "approved", "approved": "started", "started": "closed"}

app = FastAPI()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def _reject(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


# ── DB ──────────────────────────────────────────────────────────────────────
def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def valid_until_of(approved_at):
    a = datetime.strptime(approved_at, FMT)
    return min(a + timedelta(hours=8), a.replace(hour=23, minute=59)).strftime(FMT)


def init_db():
    with LOCK:
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(DB + suffix)
            except OSError:
                pass
        c = conn()
        c.executescript("""
        CREATE TABLE wp_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE wp_zones (zone_id TEXT PRIMARY KEY, name TEXT, ord INTEGER);
        CREATE TABLE wp_check_items (work_type TEXT, item_id TEXT, name TEXT, ord INTEGER);
        CREATE TABLE wp_permits (permit_id TEXT PRIMARY KEY, work_type TEXT, zone_id TEXT, requester_id TEXT,
            start_at TEXT, end_at TEXT, status TEXT, checked TEXT, reviewed_by TEXT, approved_by TEXT,
            approved_at TEXT, valid_until TEXT, started_at TEXT, closed_at TEXT);
        """)
        for r in read_csv("users.csv"):
            c.execute("INSERT INTO wp_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
        for i, r in enumerate(read_csv("zones.csv")):
            c.execute("INSERT INTO wp_zones VALUES (?,?,?)", (r["zone_id"], r["name"], i))
        for i, r in enumerate(read_csv("check_items.csv")):
            c.execute("INSERT INTO wp_check_items VALUES (?,?,?,?)", (r["work_type"], r["item_id"], r["name"], i))
        for r in read_csv("permits.csv"):
            def v(k):
                return (r.get(k) or "").strip() or None
            ap = v("approved_at")
            c.execute("INSERT INTO wp_permits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (r["permit_id"].strip(), v("work_type"), v("zone_id"), v("requester_id"), v("start_at"), v("end_at"),
                       v("status"), v("checked") or "", v("reviewed_by"), v("approved_by"), ap,
                       valid_until_of(ap) if ap else None, v("started_at"), v("closed_at")))
        c.commit()
        c.close()


init_db()


def now_str():
    return datetime.now().strftime(FMT)


# ── 조회 도우미 ─────────────────────────────────────────────────────────────
def present(row, users, zones):
    status = row["status"]
    if status in ("approved", "started") and row["valid_until"] and now_str() > row["valid_until"]:
        status = "expired"
    return {
        "permit_id": row["permit_id"], "work_type": row["work_type"],
        "work_type_name": WT_NAME.get(row["work_type"], row["work_type"]),
        "zone_id": row["zone_id"], "zone_name": zones.get(row["zone_id"]),
        "requester_id": row["requester_id"], "requester_name": users.get(row["requester_id"], {}).get("name"),
        "start_at": row["start_at"], "end_at": row["end_at"], "status": status,
        "checked": [x for x in (row["checked"] or "").split("|") if x],
        "reviewed_by": row["reviewed_by"], "approved_by": row["approved_by"],
        "approved_at": row["approved_at"], "valid_until": row["valid_until"],
        "started_at": row["started_at"], "closed_at": row["closed_at"],
    }


def maps(c):
    users = {r["user_id"]: dict(r) for r in c.execute("SELECT * FROM wp_users")}
    zones = {r["zone_id"]: r["name"] for r in c.execute("SELECT * FROM wp_zones")}
    return users, zones


def is_expired(row):
    return row["status"] in ("approved", "started") and bool(row["valid_until"]) and now_str() > row["valid_until"]


def is_live(row):
    return row["status"] in ("approved", "started") and not is_expired(row)


def pair(a, b):
    return {a["work_type"], b["work_type"]} == {"hot", "confined"}


def overlap(a, b):
    return a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]


def need_user(value):
    if not isinstance(value, str) or not value.strip():
        raise Reject(400, "사용자를 확인하세요")
    return value.strip()


def find_user(c, uid):
    r = c.execute("SELECT * FROM wp_users WHERE user_id=?", (uid,)).fetchone()
    if not r:
        raise Reject(404, "없는 사용자입니다")
    return r


def find_permit(c, pid):
    r = c.execute("SELECT * FROM wp_permits WHERE permit_id=?", (pid,)).fetchone()
    if not r:
        raise Reject(404, "없는 허가입니다")
    return r


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


# ── 읽기 API ────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(INDEX, media_type="text/html; charset=utf-8")


@app.get("/api/users")
def users():
    with LOCK:
        c = conn()
        out = [{"user_id": r["user_id"], "name": r["name"], "role": r["role"]} for r in c.execute("SELECT * FROM wp_users")]
        c.close()
        return out


@app.get("/api/work-types")
def work_types():
    with LOCK:
        c = conn()
        out = []
        for wt, name in WORK_TYPES:
            items = [{"item_id": r["item_id"], "name": r["name"]}
                     for r in c.execute("SELECT * FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,))]
            out.append({"work_type": wt, "name": name, "items": items})
        c.close()
        return out


@app.get("/api/zones")
def zones_api():
    with LOCK:
        c = conn()
        out = [{"zone_id": r["zone_id"], "name": r["name"]} for r in c.execute("SELECT * FROM wp_zones ORDER BY ord")]
        c.close()
        return out


@app.get("/api/permits")
def permits(viewer: str = None):
    with LOCK:
        c = conn()
        try:
            u = find_user(c, need_user(viewer))
            us, zs = maps(c)
            rows = c.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id").fetchall()
            if u["role"] == "worker":
                rows = [r for r in rows if r["requester_id"] == u["user_id"]]
            return [present(r, us, zs) for r in rows]
        finally:
            c.close()


@app.get("/api/permits/{permit_id}")
def permit_one(permit_id: str, viewer: str = None):
    with LOCK:
        c = conn()
        try:
            need = need_user(viewer)
            u = find_user(c, need)
            row = find_permit(c, permit_id)
            if u["role"] == "worker" and row["requester_id"] != u["user_id"]:
                raise Reject(403, "본인 허가만 볼 수 있습니다")
            us, zs = maps(c)
            return present(row, us, zs)
        finally:
            c.close()


@app.get("/api/dashboard")
def dashboard(viewer: str = None):
    with LOCK:
        c = conn()
        try:
            u = find_user(c, need_user(viewer))
            if u["role"] == "worker":
                raise Reject(403, "현황판은 안전 담당과 현장 책임자만 볼 수 있습니다")
            us, zs = maps(c)
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            lo, hi = today.strftime(FMT), (today + timedelta(days=1)).strftime(FMT)
            rows = [r for r in c.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id")
                    if r["status"] != "closed" and r["start_at"] < hi and r["end_at"] > lo]
            zones_out = []
            for z in c.execute("SELECT * FROM wp_zones ORDER BY ord"):
                ps = []
                for r in rows:
                    if r["zone_id"] == z["zone_id"]:
                        p = present(r, us, zs)
                        ps.append({"permit_id": p["permit_id"], "work_type": p["work_type"], "status": p["status"],
                                   "start_at": p["start_at"], "end_at": p["end_at"], "requester_name": p["requester_name"]})
                zones_out.append({"zone_id": z["zone_id"], "name": z["name"], "permits": ps})
            conflicts = []
            for i, a in enumerate(rows):
                for b in rows[i + 1:]:
                    if a["zone_id"] == b["zone_id"] and pair(a, b) and overlap(a, b) and (is_live(a) or is_live(b)):
                        conflicts.append({"zone_id": a["zone_id"], "permit_ids": sorted([a["permit_id"], b["permit_id"]])})
            return {"date": today.strftime("%Y-%m-%d"), "hours": list(range(6, 19)), "zones": zones_out, "conflicts": conflicts}
        finally:
            c.close()


# ── 쓰기 API ────────────────────────────────────────────────────────────────
@app.post("/api/permits", status_code=201)
async def create_permit(request: Request):
    b = await body_of(request)
    with LOCK:
        c = conn()
        try:
            uid = need_user(b.get("user"))
            wt = b.get("work_type")
            if wt not in WT_NAME:
                raise Reject(400, "작업 종류를 확인하세요")
            times = []
            for k in ("start_at", "end_at"):
                try:
                    v = b.get(k)
                    if not isinstance(v, str):
                        raise ValueError
                    t = datetime.strptime(v, FMT)
                    if t.strftime(FMT) != v:
                        raise ValueError
                    times.append(t)
                except ValueError:
                    raise Reject(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
            if not times[1] > times[0]:
                raise Reject(400, "종료 시각이 시작 시각보다 앞입니다")
            find_user(c, uid)
            zid = b.get("zone_id")
            if not isinstance(zid, str) or not c.execute("SELECT 1 FROM wp_zones WHERE zone_id=?", (zid,)).fetchone():
                raise Reject(404, "없는 구역입니다")
            items = list(c.execute("SELECT * FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,)))
            checked = b.get("checked")
            if not isinstance(checked, list) or not all(isinstance(x, str) for x in checked):
                checked = []
            missing = [i["name"] for i in items if i["item_id"] not in checked]
            if missing:
                raise Reject(400, "필수 점검 항목이 비었습니다 (%s)" % ", ".join(missing))
            ids = {i["item_id"] for i in items}
            if any(x not in ids for x in checked):
                raise Reject(400, "점검 항목을 확인하세요")
            mx = 100
            for r in c.execute("SELECT permit_id FROM wp_permits"):
                try:
                    mx = max(mx, int(r["permit_id"].split("-")[1]))
                except (IndexError, ValueError):
                    pass
            pid = "WP-%04d" % (mx + 1)
            ordered = [i["item_id"] for i in items]
            c.execute("INSERT INTO wp_permits (permit_id, work_type, zone_id, requester_id, start_at, end_at, status, checked)"
                      " VALUES (?,?,?,?,?,?,?,?)",
                      (pid, wt, zid, uid, b["start_at"], b["end_at"], "requested", "|".join(ordered)))
            c.commit()
            us, zs = maps(c)
            return JSONResponse(present(find_permit(c, pid), us, zs), status_code=201)
        finally:
            c.close()


async def load_action(request, permit_id):
    b = await body_of(request)
    uid = need_user(b.get("user"))
    c = conn()
    try:
        u = find_user(c, uid)
        row = find_permit(c, permit_id)
    except Exception:
        c.close()
        raise
    return c, u, row


@app.post("/api/permits/{permit_id}/review")
async def review(permit_id: str, request: Request):
    with LOCK:
        c, u, row = await load_action(request, permit_id)
        try:
            if u["role"] != "safety":
                raise Reject(403, "안전 담당만 검토할 수 있습니다")
            if row["status"] != "requested":
                raise Reject(409, "검토할 상태가 아닙니다")
            c.execute("UPDATE wp_permits SET status='reviewed', reviewed_by=? WHERE permit_id=?", (u["user_id"], permit_id))
            c.commit()
            return {"permit_id": permit_id, "status": "reviewed", "reviewed_by": u["user_id"]}
        finally:
            c.close()


@app.post("/api/permits/{permit_id}/approve")
async def approve(permit_id: str, request: Request):
    with LOCK:
        c, u, row = await load_action(request, permit_id)
        try:
            if u["role"] != "manager":
                raise Reject(403, "현장 책임자만 승인할 수 있습니다")
            if row["requester_id"] == u["user_id"]:
                raise Reject(403, "자기 허가는 승인할 수 없습니다")
            if row["status"] == "requested":
                raise Reject(409, "검토 전에는 승인할 수 없습니다")
            if row["status"] != "reviewed":
                raise Reject(409, "승인할 상태가 아닙니다")
            for o in c.execute("SELECT * FROM wp_permits WHERE zone_id=? AND permit_id<>?", (row["zone_id"], permit_id)):
                if is_live(o) and overlap(row, o) and pair(row, o):
                    raise Reject(409, "같은 구역에 상충 작업이 있습니다 (%s)" % o["permit_id"])
            at = now_str()
            vu = valid_until_of(at)
            c.execute("UPDATE wp_permits SET status='approved', approved_by=?, approved_at=?, valid_until=? WHERE permit_id=?",
                      (u["user_id"], at, vu, permit_id))
            c.commit()
            return {"permit_id": permit_id, "status": "approved", "approved_by": u["user_id"], "approved_at": at, "valid_until": vu}
        finally:
            c.close()


@app.post("/api/permits/{permit_id}/start")
async def start(permit_id: str, request: Request):
    with LOCK:
        c, u, row = await load_action(request, permit_id)
        try:
            if row["requester_id"] != u["user_id"]:
                raise Reject(403, "신청자만 작업을 시작할 수 있습니다")
            st = row["status"]
            if st in ("requested", "reviewed"):
                raise Reject(409, "승인 전에는 작업을 시작할 수 없습니다")
            if st == "started":
                raise Reject(409, "이미 시작한 작업입니다")
            if st == "closed":
                raise Reject(409, "종료된 허가입니다")
            if is_expired(row):
                raise Reject(409, "허가가 만료되었습니다")
            at = now_str()
            c.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (at, permit_id))
            c.commit()
            return {"permit_id": permit_id, "status": "started", "started_at": at}
        finally:
            c.close()


@app.post("/api/permits/{permit_id}/close")
async def close(permit_id: str, request: Request):
    with LOCK:
        c, u, row = await load_action(request, permit_id)
        try:
            if u["user_id"] not in (row["requester_id"], row["approved_by"]):
                raise Reject(403, "신청자 또는 승인자만 종료할 수 있습니다")
            if row["status"] != "started":
                raise Reject(409, "시작한 작업만 종료할 수 있습니다")
            at = now_str()
            c.execute("UPDATE wp_permits SET status='closed', closed_at=? WHERE permit_id=?", (at, permit_id))
            c.commit()
            return {"permit_id": permit_id, "status": "closed", "closed_at": at}
        finally:
            c.close()
