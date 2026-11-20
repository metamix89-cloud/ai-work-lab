import csv
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "permit.db"
INDEX = BASE / "static" / "index.html"

FMT = "%Y-%m-%d %H:%M"
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
WORK_TYPES = {"height": "고소 작업", "hot": "화기 작업", "confined": "밀폐 작업"}
STATUSES = ("requested", "reviewed", "approved", "started", "closed")

app = FastAPI()


# ---------- DB ----------
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def expand(v):
    """Optional TODAY / YESTERDAY tokens in seed times so the demo data stays 'today'."""
    v = (v or "").strip()
    if not v:
        return None
    today = datetime.now().date()
    v = v.replace("YESTERDAY", str(today - timedelta(days=1))).replace("TODAY", str(today))
    return v


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    c = conn()
    c.executescript(
        """
        CREATE TABLE wp_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE wp_zones (zone_id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE wp_check_items (work_type TEXT, item_id TEXT, name TEXT);
        CREATE TABLE wp_permits (
            permit_id TEXT PRIMARY KEY, work_type TEXT, zone_id TEXT, requester_id TEXT,
            start_at TEXT, end_at TEXT, status TEXT, checked TEXT, reviewed_by TEXT,
            approved_by TEXT, approved_at TEXT, started_at TEXT, closed_at TEXT);
        """
    )
    for r in read_csv("users.csv"):
        c.execute("INSERT INTO wp_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("zones.csv"):
        c.execute("INSERT INTO wp_zones VALUES (?,?)", (r["zone_id"], r["name"]))
    for r in read_csv("check_items.csv"):
        c.execute("INSERT INTO wp_check_items VALUES (?,?,?)", (r["work_type"], r["item_id"], r["name"]))
    for r in read_csv("permits.csv"):
        c.execute(
            "INSERT INTO wp_permits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["permit_id"], r["work_type"], r["zone_id"], r["requester_id"],
                expand(r["start_at"]), expand(r["end_at"]), r["status"],
                (r.get("checked") or "").strip(),
                expand(r["reviewed_by"]), expand(r["approved_by"]), expand(r["approved_at"]),
                expand(r["started_at"]), expand(r["closed_at"]),
            ),
        )
    c.commit()
    c.close()


init_db()


@app.on_event("startup")
def _startup():
    init_db()


# ---------- helpers ----------
def now_minute():
    return datetime.now().replace(second=0, microsecond=0)


def parse(s):
    return datetime.strptime(s, FMT)


def valid_until_of(approved_at):
    if not approved_at:
        return None
    a = parse(approved_at)
    cap = a.replace(hour=23, minute=59)
    return min(a + timedelta(hours=8), cap)


def is_expired(row):
    if row["status"] not in ("approved", "started") or not row["approved_at"]:
        return False
    return now_minute() > valid_until_of(row["approved_at"])


def is_live(row):
    """approved or started and still valid"""
    return row["status"] in ("approved", "started") and not is_expired(row)


def eff_status(row):
    return "expired" if is_expired(row) else row["status"]


def fmt(dt):
    return dt.strftime(FMT) if dt else None


def permit_json(c, row):
    z = c.execute("SELECT name FROM wp_zones WHERE zone_id=?", (row["zone_id"],)).fetchone()
    u = c.execute("SELECT name FROM wp_users WHERE user_id=?", (row["requester_id"],)).fetchone()
    return {
        "permit_id": row["permit_id"],
        "work_type": row["work_type"],
        "work_type_name": WORK_TYPES.get(row["work_type"], row["work_type"]),
        "zone_id": row["zone_id"],
        "zone_name": z["name"] if z else None,
        "requester_id": row["requester_id"],
        "requester_name": u["name"] if u else None,
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "status": eff_status(row),
        "checked": [x for x in (row["checked"] or "").split("|") if x],
        "reviewed_by": row["reviewed_by"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"],
        "valid_until": fmt(valid_until_of(row["approved_at"])),
        "started_at": row["started_at"],
        "closed_at": row["closed_at"],
    }


def err(code, msg):
    raise HTTPException(status_code=code, detail=msg)


def need_str(v):
    if not isinstance(v, str) or not v.strip():
        err(400, "사용자를 확인하세요")
    return v


def get_user(c, uid):
    u = c.execute("SELECT * FROM wp_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        err(404, "없는 사용자입니다")
    return u


def get_permit(c, pid):
    p = c.execute("SELECT * FROM wp_permits WHERE permit_id=?", (pid,)).fetchone()
    if not p:
        err(404, "없는 허가입니다")
    return p


async def body_of(request: Request):
    try:
        b = await request.json()
    except Exception:
        b = None
    return b if isinstance(b, dict) else {}


def overlaps(a, b):
    return a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]


def clash_pair(a, b):
    return (
        a["zone_id"] == b["zone_id"]
        and {a["work_type"], b["work_type"]} == {"hot", "confined"}
        and overlaps(a, b)
    )


# ---------- pages & lookups ----------
@app.get("/")
def index():
    return FileResponse(INDEX, media_type="text/html")


@app.get("/api/users")
def users():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT user_id,name,role FROM wp_users ORDER BY rowid")]
    finally:
        c.close()


@app.get("/api/work-types")
def work_types():
    c = conn()
    try:
        out = []
        for wt, name in WORK_TYPES.items():
            items = [
                {"item_id": r["item_id"], "name": r["name"]}
                for r in c.execute("SELECT item_id,name FROM wp_check_items WHERE work_type=? ORDER BY rowid", (wt,))
            ]
            out.append({"work_type": wt, "name": name, "items": items})
        return out
    finally:
        c.close()


@app.get("/api/zones")
def zones():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT zone_id,name FROM wp_zones ORDER BY rowid")]
    finally:
        c.close()


# ---------- permits ----------
@app.get("/api/permits")
def list_permits(viewer: str = None):
    need_str(viewer)
    c = conn()
    try:
        u = get_user(c, viewer)
        rows = c.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id").fetchall()
        if u["role"] == "worker":
            rows = [r for r in rows if r["requester_id"] == u["user_id"]]
        return [permit_json(c, r) for r in rows]
    finally:
        c.close()


@app.get("/api/permits/{permit_id}")
def get_one(permit_id: str, viewer: str = None):
    need_str(viewer)
    c = conn()
    try:
        u = get_user(c, viewer)
        p = get_permit(c, permit_id)
        if u["role"] == "worker" and p["requester_id"] != u["user_id"]:
            err(403, "본인 허가만 볼 수 있습니다")
        return permit_json(c, p)
    finally:
        c.close()


@app.post("/api/permits", status_code=201)
async def create_permit(request: Request):
    b = await body_of(request)
    need_str(b.get("user"))
    wt = b.get("work_type")
    if not isinstance(wt, str) or wt not in WORK_TYPES:
        err(400, "작업 종류를 확인하세요")
    s, e = b.get("start_at"), b.get("end_at")
    try:
        if not (isinstance(s, str) and isinstance(e, str) and TIME_RE.match(s) and TIME_RE.match(e)):
            raise ValueError
        sd, ed = parse(s), parse(e)
    except ValueError:
        err(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
    if ed <= sd:
        err(400, "종료 시각이 시작 시각보다 앞입니다")
    c = conn()
    try:
        get_user(c, b["user"])
        zid = b.get("zone_id")
        if not isinstance(zid, str) or not c.execute("SELECT 1 FROM wp_zones WHERE zone_id=?", (zid,)).fetchone():
            err(404, "없는 구역입니다")
        items = c.execute("SELECT item_id,name FROM wp_check_items WHERE work_type=? ORDER BY rowid", (wt,)).fetchall()
        checked = b.get("checked")
        if not isinstance(checked, list) or not all(isinstance(x, str) for x in checked):
            err(400, "점검 항목을 확인하세요")
        have = set(checked)
        for it in items:
            if it["item_id"] not in have:
                err(400, f"필수 점검 항목이 비었습니다 ({it['name']})")
        valid_ids = {it["item_id"] for it in items}
        if any(x not in valid_ids for x in checked):
            err(400, "점검 항목을 확인하세요")
        mx = c.execute("SELECT MAX(CAST(SUBSTR(permit_id,4) AS INTEGER)) m FROM wp_permits").fetchone()["m"] or 0
        pid = f"WP-{mx + 1:04d}"
        ordered = [it["item_id"] for it in items]
        c.execute(
            "INSERT INTO wp_permits (permit_id,work_type,zone_id,requester_id,start_at,end_at,status,checked) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, wt, zid, b["user"], s, e, "requested", "|".join(ordered)),
        )
        c.commit()
        return permit_json(c, get_permit(c, pid))
    finally:
        c.close()


async def action_prelude(c, request, permit_id):
    b = await body_of(request)
    need_str(b.get("user"))
    u = get_user(c, b["user"])
    p = get_permit(c, permit_id)
    return u, p


@app.post("/api/permits/{permit_id}/review")
async def review(permit_id: str, request: Request):
    c = conn()
    try:
        u, p = await action_prelude(c, request, permit_id)
        if u["role"] != "safety":
            err(403, "안전 담당만 검토할 수 있습니다")
        if p["status"] != "requested":
            err(409, "검토할 상태가 아닙니다")
        c.execute("UPDATE wp_permits SET status='reviewed', reviewed_by=? WHERE permit_id=?", (u["user_id"], permit_id))
        c.commit()
        return {"permit_id": permit_id, "status": "reviewed", "reviewed_by": u["user_id"]}
    finally:
        c.close()


@app.post("/api/permits/{permit_id}/approve")
async def approve(permit_id: str, request: Request):
    c = conn()
    try:
        u, p = await action_prelude(c, request, permit_id)
        if u["role"] != "manager":
            err(403, "현장 책임자만 승인할 수 있습니다")
        if p["requester_id"] == u["user_id"]:
            err(403, "자기 허가는 승인할 수 없습니다")
        if p["status"] == "requested":
            err(409, "검토 전에는 승인할 수 없습니다")
        if p["status"] != "reviewed":
            err(409, "승인할 상태가 아닙니다")
        for o in c.execute("SELECT * FROM wp_permits WHERE permit_id<>?", (permit_id,)).fetchall():
            if is_live(o) and clash_pair(p, o):
                err(409, f"같은 구역에 상충 작업이 있습니다 ({o['permit_id']})")
        now = now_minute()
        at = fmt(now)
        c.execute(
            "UPDATE wp_permits SET status='approved', approved_by=?, approved_at=? WHERE permit_id=?",
            (u["user_id"], at, permit_id),
        )
        c.commit()
        return {
            "permit_id": permit_id,
            "status": "approved",
            "approved_by": u["user_id"],
            "approved_at": at,
            "valid_until": fmt(valid_until_of(at)),
        }
    finally:
        c.close()


@app.post("/api/permits/{permit_id}/start")
async def start(permit_id: str, request: Request):
    c = conn()
    try:
        u, p = await action_prelude(c, request, permit_id)
        if p["requester_id"] != u["user_id"]:
            err(403, "신청자만 작업을 시작할 수 있습니다")
        st = p["status"]
        if st in ("requested", "reviewed"):
            err(409, "승인 전에는 작업을 시작할 수 없습니다")
        if st == "started":
            err(409, "이미 시작한 작업입니다")
        if st == "closed":
            err(409, "종료된 허가입니다")
        if is_expired(p):
            err(409, "허가가 만료되었습니다")
        at = fmt(now_minute())
        c.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (at, permit_id))
        c.commit()
        return {"permit_id": permit_id, "status": "started", "started_at": at}
    finally:
        c.close()


@app.post("/api/permits/{permit_id}/close")
async def close(permit_id: str, request: Request):
    c = conn()
    try:
        u, p = await action_prelude(c, request, permit_id)
        if u["user_id"] not in (p["requester_id"], p["approved_by"]):
            err(403, "신청자 또는 승인자만 종료할 수 있습니다")
        if p["status"] != "started":
            err(409, "시작한 작업만 종료할 수 있습니다")
        at = fmt(now_minute())
        c.execute("UPDATE wp_permits SET status='closed', closed_at=? WHERE permit_id=?", (at, permit_id))
        c.commit()
        return {"permit_id": permit_id, "status": "closed", "closed_at": at}
    finally:
        c.close()


# ---------- dashboard ----------
@app.get("/api/dashboard")
def dashboard(viewer: str = None):
    need_str(viewer)
    c = conn()
    try:
        u = get_user(c, viewer)
        if u["role"] not in ("safety", "manager"):
            err(403, "현황판은 안전 담당과 현장 책임자만 볼 수 있습니다")
        today = datetime.now().date()
        d0 = f"{today} 00:00"
        d1 = f"{today + timedelta(days=1)} 00:00"
        rows = [
            r
            for r in c.execute("SELECT * FROM wp_permits ORDER BY start_at, permit_id").fetchall()
            if r["status"] != "closed" and r["start_at"] < d1 and r["end_at"] > d0
        ]
        names = {r["user_id"]: r["name"] for r in c.execute("SELECT user_id,name FROM wp_users")}
        zs = []
        for z in c.execute("SELECT zone_id,name FROM wp_zones ORDER BY rowid").fetchall():
            zs.append(
                {
                    "zone_id": z["zone_id"],
                    "name": z["name"],
                    "permits": [
                        {
                            "permit_id": r["permit_id"],
                            "work_type": r["work_type"],
                            "status": eff_status(r),
                            "start_at": r["start_at"],
                            "end_at": r["end_at"],
                            "requester_name": names.get(r["requester_id"]),
                        }
                        for r in rows
                        if r["zone_id"] == z["zone_id"]
                    ],
                }
            )
        conflicts = []
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if clash_pair(a, b) and (is_live(a) or is_live(b)):
                    ids = sorted([a["permit_id"], b["permit_id"]])
                    conflicts.append({"zone_id": a["zone_id"], "permit_ids": ids})
        return {"date": str(today), "hours": list(range(6, 19)), "zones": zs, "conflicts": conflicts}
    finally:
        c.close()
