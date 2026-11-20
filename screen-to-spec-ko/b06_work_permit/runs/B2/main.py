import csv
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "permit.db")
INDEX = os.path.join(BASE, "static", "index.html")

FMT = "%Y-%m-%d %H:%M"
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
WORK_TYPES = [("height", "고소 작업"), ("hot", "화기 작업"), ("confined", "밀폐 작업")]
WORK_NAME = dict(WORK_TYPES)
ROLE_WORKER, ROLE_SAFETY, ROLE_MANAGER = "worker", "safety", "manager"

db = None


class Reject(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global db
    if db is not None:
        db.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE wp_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE wp_zones (zone_id TEXT PRIMARY KEY, name TEXT, ord INTEGER);
        CREATE TABLE wp_check_items (work_type TEXT, item_id TEXT, name TEXT, ord INTEGER);
        CREATE TABLE wp_permits (
            permit_id TEXT PRIMARY KEY, work_type TEXT, zone_id TEXT, requester_id TEXT,
            start_at TEXT, end_at TEXT, status TEXT, checked TEXT,
            reviewed_by TEXT, approved_by TEXT, approved_at TEXT, started_at TEXT, closed_at TEXT);
        """
    )
    for r in read_csv("users.csv"):
        db.execute("INSERT INTO wp_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for i, r in enumerate(read_csv("zones.csv")):
        db.execute("INSERT INTO wp_zones VALUES (?,?,?)", (r["zone_id"], r["name"], i))
    for i, r in enumerate(read_csv("check_items.csv")):
        db.execute("INSERT INTO wp_check_items VALUES (?,?,?,?)", (r["work_type"], r["item_id"], r["name"], i))
    cols = ["permit_id", "work_type", "zone_id", "requester_id", "start_at", "end_at", "status",
            "checked", "reviewed_by", "approved_by", "approved_at", "started_at", "closed_at"]
    for r in read_csv("permits.csv"):
        vals = [(r.get(c) or "").strip() or None for c in cols]
        db.execute("INSERT INTO wp_permits VALUES (%s)" % ",".join("?" * len(cols)), vals)
    db.commit()


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


# ---------- helpers ----------

def now_str():
    return datetime.now().strftime(FMT)


def valid_until_of(approved_at):
    if not approved_at:
        return None
    t = datetime.strptime(approved_at, FMT)
    limit = t.replace(hour=23, minute=59)
    return min(t + timedelta(hours=8), limit).strftime(FMT)


def eff_status(row):
    vu = valid_until_of(row["approved_at"])
    if row["status"] in ("approved", "started") and vu and now_str() > vu:
        return "expired"
    return row["status"]


def is_live(row):
    """승인 · 작업 중이고 유효."""
    return row["status"] in ("approved", "started") and eff_status(row) != "expired"


def overlap(a, b):
    return a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]


def conflict_pair(a, b):
    return {a["work_type"], b["work_type"]} == {"hot", "confined"}


def find_user(uid):
    if not isinstance(uid, str) or not uid:
        raise Reject(400, "사용자를 확인하세요")
    u = db.execute("SELECT * FROM wp_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return u


def find_permit(pid):
    p = db.execute("SELECT * FROM wp_permits WHERE permit_id=?", (pid,)).fetchone()
    if not p:
        raise Reject(404, "허가를 찾을 수 없습니다")
    return p


def serialize(row):
    names = {r["user_id"]: r["name"] for r in db.execute("SELECT user_id, name FROM wp_users")}
    zones = {r["zone_id"]: r["name"] for r in db.execute("SELECT zone_id, name FROM wp_zones")}
    return {
        "permit_id": row["permit_id"],
        "work_type": row["work_type"],
        "work_type_name": WORK_NAME.get(row["work_type"], row["work_type"]),
        "zone_id": row["zone_id"],
        "zone_name": zones.get(row["zone_id"]),
        "requester_id": row["requester_id"],
        "requester_name": names.get(row["requester_id"]),
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "status": eff_status(row),
        "checked": [c for c in (row["checked"] or "").split("|") if c],
        "reviewed_by": row["reviewed_by"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"],
        "valid_until": valid_until_of(row["approved_at"]),
        "started_at": row["started_at"],
        "closed_at": row["closed_at"],
    }


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        data = None
    return data if isinstance(data, dict) else {}


# ---------- read APIs ----------

@app.get("/")
async def index():
    return FileResponse(INDEX, media_type="text/html")


@app.get("/api/users")
async def users():
    return [dict(r) for r in db.execute("SELECT user_id, name, role FROM wp_users ORDER BY rowid")]


@app.get("/api/work-types")
async def work_types():
    out = []
    for wt, name in WORK_TYPES:
        items = db.execute(
            "SELECT item_id, name FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,)
        ).fetchall()
        out.append({"work_type": wt, "name": name, "items": [dict(i) for i in items]})
    return out


@app.get("/api/zones")
async def zones():
    return [dict(r) for r in db.execute("SELECT zone_id, name FROM wp_zones ORDER BY ord")]


@app.get("/api/permits")
async def list_permits(viewer: str = None):
    u = find_user(viewer)
    rows = db.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id").fetchall()
    if u["role"] == ROLE_WORKER:
        rows = [r for r in rows if r["requester_id"] == u["user_id"]]
    return [serialize(r) for r in rows]


@app.get("/api/permits/{permit_id}")
async def get_permit(permit_id: str, viewer: str = None):
    u = find_user(viewer)
    p = find_permit(permit_id)
    if u["role"] == ROLE_WORKER and p["requester_id"] != u["user_id"]:
        raise Reject(403, "본인 허가만 볼 수 있습니다")
    return serialize(p)


@app.get("/api/dashboard")
async def dashboard(viewer: str = None):
    u = find_user(viewer)
    if u["role"] not in (ROLE_SAFETY, ROLE_MANAGER):
        raise Reject(403, "현황판은 안전 담당과 현장 책임자만 볼 수 있습니다")
    today = datetime.now().date()
    d0 = today.strftime("%Y-%m-%d") + " 00:00"
    d1 = (today + timedelta(days=1)).strftime("%Y-%m-%d") + " 00:00"
    rows = [
        r for r in db.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id")
        if r["start_at"] < d1 and r["end_at"] > d0 and r["status"] != "closed"
    ]
    names = {r["user_id"]: r["name"] for r in db.execute("SELECT user_id, name FROM wp_users")}
    zones_out = []
    for z in db.execute("SELECT * FROM wp_zones ORDER BY ord"):
        zones_out.append({
            "zone_id": z["zone_id"], "name": z["name"],
            "permits": [
                {"permit_id": r["permit_id"], "work_type": r["work_type"], "status": eff_status(r),
                 "start_at": r["start_at"], "end_at": r["end_at"],
                 "requester_name": names.get(r["requester_id"])}
                for r in rows if r["zone_id"] == z["zone_id"]
            ],
        })
    conflicts = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["zone_id"] != b["zone_id"] or not overlap(a, b) or not conflict_pair(a, b):
                continue
            if is_live(a) or is_live(b):
                conflicts.append({"zone_id": a["zone_id"],
                                  "permit_ids": sorted([a["permit_id"], b["permit_id"]])})
    return {"date": today.strftime("%Y-%m-%d"), "hours": list(range(6, 19)),
            "zones": zones_out, "conflicts": conflicts}


# ---------- write APIs ----------

@app.post("/api/permits", status_code=201)
async def create_permit(request: Request):
    b = await body_of(request)
    uid = b.get("user")
    if not isinstance(uid, str) or not uid:
        raise Reject(400, "사용자를 확인하세요")
    wt = b.get("work_type")
    if not isinstance(wt, str) or wt not in WORK_NAME:
        raise Reject(400, "작업 종류를 확인하세요")
    s, e = b.get("start_at"), b.get("end_at")
    parsed = []
    for v in (s, e):
        try:
            if not isinstance(v, str) or not TIME_RE.match(v):
                raise ValueError
            parsed.append(datetime.strptime(v, FMT))
        except ValueError:
            raise Reject(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
    if not parsed[1] > parsed[0]:
        raise Reject(400, "종료 시각이 시작 시각보다 앞입니다")
    u = find_user(uid)
    zid = b.get("zone_id")
    z = db.execute("SELECT * FROM wp_zones WHERE zone_id=?", (zid,)).fetchone() if isinstance(zid, str) else None
    if not z:
        raise Reject(404, "구역을 찾을 수 없습니다")
    items = db.execute(
        "SELECT item_id, name FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,)
    ).fetchall()
    checked = b.get("checked")
    if not isinstance(checked, list) or not all(isinstance(c, str) for c in checked):
        raise Reject(400, "점검 항목을 확인하세요")
    have = set(checked)
    for it in items:
        if it["item_id"] not in have:
            raise Reject(400, "필수 점검 항목이 비었습니다 (%s)" % it["name"])
    if have - {it["item_id"] for it in items}:
        raise Reject(400, "점검 항목을 확인하세요")
    nums = [int(r["permit_id"][3:]) for r in db.execute("SELECT permit_id FROM wp_permits")
            if re.match(r"^WP-\d+$", r["permit_id"])]
    pid = "WP-%04d" % (max(nums, default=0) + 1)
    db.execute(
        "INSERT INTO wp_permits (permit_id, work_type, zone_id, requester_id, start_at, end_at, status, checked)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (pid, wt, z["zone_id"], u["user_id"], s, e, "requested", "|".join(i["item_id"] for i in items)),
    )
    db.commit()
    return serialize(find_permit(pid))


async def load(request, permit_id):
    b = await body_of(request)
    u = find_user(b.get("user"))
    p = find_permit(permit_id)
    return u, p


@app.post("/api/permits/{permit_id}/review")
async def review(permit_id: str, request: Request):
    u, p = await load(request, permit_id)
    if u["role"] != ROLE_SAFETY:
        raise Reject(403, "안전 담당만 검토할 수 있습니다")
    if p["status"] != "requested":
        raise Reject(409, "검토할 상태가 아닙니다")
    db.execute("UPDATE wp_permits SET status='reviewed', reviewed_by=? WHERE permit_id=?",
               (u["user_id"], permit_id))
    db.commit()
    return {"permit_id": permit_id, "status": "reviewed", "reviewed_by": u["user_id"]}


@app.post("/api/permits/{permit_id}/approve")
async def approve(permit_id: str, request: Request):
    u, p = await load(request, permit_id)
    if u["role"] != ROLE_MANAGER:
        raise Reject(403, "현장 책임자만 승인할 수 있습니다")
    if p["requester_id"] == u["user_id"]:
        raise Reject(403, "자기 허가는 승인할 수 없습니다")
    if p["status"] == "requested":
        raise Reject(409, "검토 전에는 승인할 수 없습니다")
    if p["status"] != "reviewed":
        raise Reject(409, "승인할 상태가 아닙니다")
    for o in db.execute("SELECT * FROM wp_permits WHERE zone_id=? AND permit_id<>?",
                        (p["zone_id"], permit_id)):
        if is_live(o) and overlap(p, o) and conflict_pair(p, o):
            raise Reject(409, "같은 구역에 상충 작업이 있습니다 (%s)" % o["permit_id"])
    at = now_str()
    db.execute("UPDATE wp_permits SET status='approved', approved_by=?, approved_at=? WHERE permit_id=?",
               (u["user_id"], at, permit_id))
    db.commit()
    return {"permit_id": permit_id, "status": "approved", "approved_by": u["user_id"],
            "approved_at": at, "valid_until": valid_until_of(at)}


@app.post("/api/permits/{permit_id}/start")
async def start(permit_id: str, request: Request):
    u, p = await load(request, permit_id)
    if p["requester_id"] != u["user_id"]:
        raise Reject(403, "신청자만 작업을 시작할 수 있습니다")
    st = p["status"]
    if st in ("requested", "reviewed"):
        raise Reject(409, "승인 전에는 작업을 시작할 수 없습니다")
    if st == "started":
        raise Reject(409, "이미 시작한 작업입니다")
    if st == "closed":
        raise Reject(409, "종료된 허가입니다")
    if eff_status(p) == "expired":
        raise Reject(409, "허가가 만료되었습니다")
    at = now_str()
    db.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (at, permit_id))
    db.commit()
    return {"permit_id": permit_id, "status": "started", "started_at": at}


@app.post("/api/permits/{permit_id}/close")
async def close(permit_id: str, request: Request):
    u, p = await load(request, permit_id)
    if u["user_id"] != p["requester_id"] and u["user_id"] != p["approved_by"]:
        raise Reject(403, "신청자 또는 승인자만 종료할 수 있습니다")
    if p["status"] != "started":
        raise Reject(409, "시작한 작업만 종료할 수 있습니다")
    at = now_str()
    db.execute("UPDATE wp_permits SET status='closed', closed_at=? WHERE permit_id=?", (at, permit_id))
    db.commit()
    return {"permit_id": permit_id, "status": "closed", "closed_at": at}
