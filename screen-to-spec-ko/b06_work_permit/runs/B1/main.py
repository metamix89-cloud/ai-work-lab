import csv
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "permit.db")
FMT = "%Y-%m-%d %H:%M"

WORK_TYPE_NAMES = {"height": "고소 작업", "hot": "화기 작업", "confined": "밀폐 작업"}
LOCK = threading.RLock()


class HTTPErr(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail


app = FastAPI()


@app.exception_handler(HTTPErr)
async def _err(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


# ---------------------------------------------------------------- DB
def _read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    for t in ("wp_permits", "wp_check_items", "wp_zones", "wp_users"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.execute("CREATE TABLE wp_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT)")
    con.execute("CREATE TABLE wp_zones (zone_id TEXT PRIMARY KEY, name TEXT, ord INTEGER)")
    con.execute("CREATE TABLE wp_check_items (work_type TEXT, item_id TEXT, name TEXT, ord INTEGER)")
    con.execute(
        "CREATE TABLE wp_permits (permit_id TEXT PRIMARY KEY, work_type TEXT, zone_id TEXT, requester_id TEXT,"
        " start_at TEXT, end_at TEXT, status TEXT, checked TEXT, reviewed_by TEXT, approved_by TEXT,"
        " approved_at TEXT, started_at TEXT, closed_at TEXT)"
    )
    for r in _read_csv("users.csv"):
        con.execute("INSERT INTO wp_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for i, r in enumerate(_read_csv("zones.csv")):
        con.execute("INSERT INTO wp_zones VALUES (?,?,?)", (r["zone_id"], r["name"], i))
    for i, r in enumerate(_read_csv("check_items.csv")):
        con.execute("INSERT INTO wp_check_items VALUES (?,?,?,?)", (r["work_type"], r["item_id"], r["name"], i))
    cols = ["permit_id", "work_type", "zone_id", "requester_id", "start_at", "end_at", "status", "checked",
            "reviewed_by", "approved_by", "approved_at", "started_at", "closed_at"]
    for r in _read_csv("permits.csv"):
        con.execute(
            f"INSERT INTO wp_permits VALUES ({','.join('?' * len(cols))})",
            [(r.get(c) or "").strip() or None for c in cols],
        )
    con.commit()
    return con


DB = init_db()


def q(sql, args=()):
    return DB.execute(sql, args).fetchall()


# ---------------------------------------------------------------- helpers
def now():
    return datetime.now().replace(second=0, microsecond=0)


def parse(s):
    return datetime.strptime(s, FMT)


def valid_until(approved_at):
    if not approved_at:
        return None
    a = parse(approved_at)
    cap = a.replace(hour=23, minute=59)
    return min(a + timedelta(hours=8), cap)


def eff_status(row):
    st = row["status"]
    if st in ("approved", "started") and row["approved_at"]:
        if now() > valid_until(row["approved_at"]):
            return "expired"
    return st


def is_live(row):
    """승인 · 작업 중이고 유효."""
    return row["status"] in ("approved", "started") and eff_status(row) != "expired"


def is_pair(a, b):
    return {a["work_type"], b["work_type"]} == {"hot", "confined"}


def overlap(a, b):
    return a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]


def permit_json(row):
    vu = valid_until(row["approved_at"])
    users = {u["user_id"]: u["name"] for u in q("SELECT * FROM wp_users")}
    zone = q("SELECT name FROM wp_zones WHERE zone_id=?", (row["zone_id"],))
    return {
        "permit_id": row["permit_id"],
        "work_type": row["work_type"],
        "work_type_name": WORK_TYPE_NAMES.get(row["work_type"], row["work_type"]),
        "zone_id": row["zone_id"],
        "zone_name": zone[0]["name"] if zone else None,
        "requester_id": row["requester_id"],
        "requester_name": users.get(row["requester_id"]),
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "status": eff_status(row),
        "checked": [c for c in (row["checked"] or "").split("|") if c],
        "reviewed_by": row["reviewed_by"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"],
        "valid_until": vu.strftime(FMT) if vu else None,
        "started_at": row["started_at"],
        "closed_at": row["closed_at"],
    }


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def need_user_id(v):
    if not isinstance(v, str) or not v.strip():
        raise HTTPErr(400, "사용자를 확인하세요")
    return v


def find_user(uid):
    r = q("SELECT * FROM wp_users WHERE user_id=?", (uid,))
    if not r:
        raise HTTPErr(404, "사용자를 찾을 수 없습니다")
    return r[0]


def find_permit(pid):
    r = q("SELECT * FROM wp_permits WHERE permit_id=?", (pid,))
    if not r:
        raise HTTPErr(404, "허가를 찾을 수 없습니다")
    return r[0]


def sorted_permits(rows):
    return sorted(rows, key=lambda r: (r["start_at"], r["permit_id"]))


# ---------------------------------------------------------------- reads
@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")


@app.get("/api/users")
def users():
    with LOCK:
        return [{"user_id": r["user_id"], "name": r["name"], "role": r["role"]} for r in q("SELECT * FROM wp_users")]


@app.get("/api/work-types")
def work_types():
    with LOCK:
        out = []
        for wt, name in WORK_TYPE_NAMES.items():
            items = q("SELECT item_id,name FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,))
            out.append({"work_type": wt, "name": name,
                        "items": [{"item_id": i["item_id"], "name": i["name"]} for i in items]})
        return out


@app.get("/api/zones")
def zones():
    with LOCK:
        return [{"zone_id": r["zone_id"], "name": r["name"]} for r in q("SELECT * FROM wp_zones ORDER BY ord")]


@app.get("/api/permits")
def list_permits(viewer: str = None):
    with LOCK:
        u = find_user(need_user_id(viewer))
        rows = q("SELECT * FROM wp_permits")
        if u["role"] == "worker":
            rows = [r for r in rows if r["requester_id"] == u["user_id"]]
        return [permit_json(r) for r in sorted_permits(rows)]


@app.get("/api/permits/{permit_id}")
def get_permit(permit_id: str, viewer: str = None):
    with LOCK:
        need_user_id(viewer)
        u = find_user(viewer)
        p = find_permit(permit_id)
        if u["role"] == "worker" and p["requester_id"] != u["user_id"]:
            raise HTTPErr(403, "본인 허가만 볼 수 있습니다")
        return permit_json(p)


# ---------------------------------------------------------------- create
@app.post("/api/permits", status_code=201)
async def create_permit(request: Request):
    b = await body_of(request)
    with LOCK:
        uid = need_user_id(b.get("user"))
        wt = b.get("work_type")
        if not isinstance(wt, str) or wt not in WORK_TYPE_NAMES:
            raise HTTPErr(400, "작업 종류를 확인하세요")
        s, e = b.get("start_at"), b.get("end_at")
        try:
            sd, ed = parse(s), parse(e)
            if sd.strftime(FMT) != s or ed.strftime(FMT) != e:
                raise ValueError
        except Exception:
            raise HTTPErr(400, "시각 형식은 YYYY-MM-DD HH:MM 입니다")
        if ed <= sd:
            raise HTTPErr(400, "종료 시각이 시작 시각보다 앞입니다")
        find_user(uid)
        zid = b.get("zone_id")
        if not isinstance(zid, str) or not q("SELECT 1 FROM wp_zones WHERE zone_id=?", (zid,)):
            raise HTTPErr(404, "구역을 찾을 수 없습니다")
        items = q("SELECT item_id,name FROM wp_check_items WHERE work_type=? ORDER BY ord", (wt,))
        checked = b.get("checked")
        if not isinstance(checked, list):
            checked = []
        valid_ids = {i["item_id"] for i in items}
        for i in items:
            if i["item_id"] not in checked:
                raise HTTPErr(400, f"필수 점검 항목이 비었습니다 ({i['name']})")
        if any((not isinstance(c, str)) or c not in valid_ids for c in checked):
            raise HTTPErr(400, "점검 항목을 확인하세요")
        nums = [int(r["permit_id"][3:]) for r in q("SELECT permit_id FROM wp_permits")
                if r["permit_id"][3:].isdigit()]
        pid = "WP-%04d" % ((max(nums) if nums else 0) + 1)
        ordered = [i["item_id"] for i in items]
        DB.execute(
            "INSERT INTO wp_permits (permit_id,work_type,zone_id,requester_id,start_at,end_at,status,checked)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (pid, wt, zid, uid, s, e, "requested", "|".join(ordered)),
        )
        DB.commit()
        return permit_json(find_permit(pid))


# ---------------------------------------------------------------- transitions
def load_action(pid, uid):
    uid = need_user_id(uid)
    user = find_user(uid)
    p = find_permit(pid)
    return user, p


@app.post("/api/permits/{permit_id}/review")
async def review(permit_id: str, request: Request):
    b = await body_of(request)
    with LOCK:
        user, p = load_action(permit_id, b.get("user"))
        if user["role"] != "safety":
            raise HTTPErr(403, "안전 담당만 검토할 수 있습니다")
        if p["status"] != "requested":
            raise HTTPErr(409, "검토할 상태가 아닙니다")
        DB.execute("UPDATE wp_permits SET status='reviewed', reviewed_by=? WHERE permit_id=?",
                   (user["user_id"], permit_id))
        DB.commit()
        return {"permit_id": permit_id, "status": "reviewed", "reviewed_by": user["user_id"]}


@app.post("/api/permits/{permit_id}/approve")
async def approve(permit_id: str, request: Request):
    b = await body_of(request)
    with LOCK:
        user, p = load_action(permit_id, b.get("user"))
        if user["role"] != "manager":
            raise HTTPErr(403, "현장 책임자만 승인할 수 있습니다")
        if p["requester_id"] == user["user_id"]:
            raise HTTPErr(403, "자기 허가는 승인할 수 없습니다")
        if p["status"] == "requested":
            raise HTTPErr(409, "검토 전에는 승인할 수 없습니다")
        if p["status"] != "reviewed":
            raise HTTPErr(409, "승인할 상태가 아닙니다")
        for o in sorted_permits(q("SELECT * FROM wp_permits WHERE zone_id=? AND permit_id<>?",
                                  (p["zone_id"], permit_id))):
            if is_live(o) and overlap(p, o) and is_pair(p, o):
                raise HTTPErr(409, f"같은 구역에 상충 작업이 있습니다 ({o['permit_id']})")
        at = now().strftime(FMT)
        DB.execute("UPDATE wp_permits SET status='approved', approved_by=?, approved_at=? WHERE permit_id=?",
                   (user["user_id"], at, permit_id))
        DB.commit()
        return {"permit_id": permit_id, "status": "approved", "approved_by": user["user_id"],
                "approved_at": at, "valid_until": valid_until(at).strftime(FMT)}


@app.post("/api/permits/{permit_id}/start")
async def start(permit_id: str, request: Request):
    b = await body_of(request)
    with LOCK:
        user, p = load_action(permit_id, b.get("user"))
        if p["requester_id"] != user["user_id"]:
            raise HTTPErr(403, "신청자만 작업을 시작할 수 있습니다")
        st = p["status"]
        if st in ("requested", "reviewed"):
            raise HTTPErr(409, "승인 전에는 작업을 시작할 수 없습니다")
        if st == "started":
            raise HTTPErr(409, "이미 시작한 작업입니다")
        if st == "closed":
            raise HTTPErr(409, "종료된 허가입니다")
        if eff_status(p) == "expired":
            raise HTTPErr(409, "허가가 만료되었습니다")
        at = now().strftime(FMT)
        DB.execute("UPDATE wp_permits SET status='started', started_at=? WHERE permit_id=?", (at, permit_id))
        DB.commit()
        return {"permit_id": permit_id, "status": "started", "started_at": at}


@app.post("/api/permits/{permit_id}/close")
async def close(permit_id: str, request: Request):
    b = await body_of(request)
    with LOCK:
        user, p = load_action(permit_id, b.get("user"))
        if user["user_id"] not in (p["requester_id"], p["approved_by"]):
            raise HTTPErr(403, "신청자 또는 승인자만 종료할 수 있습니다")
        if p["status"] != "started":
            raise HTTPErr(409, "시작한 작업만 종료할 수 있습니다")
        at = now().strftime(FMT)
        DB.execute("UPDATE wp_permits SET status='closed', closed_at=? WHERE permit_id=?", (at, permit_id))
        DB.commit()
        return {"permit_id": permit_id, "status": "closed", "closed_at": at}


# ---------------------------------------------------------------- dashboard
@app.get("/api/dashboard")
def dashboard(viewer: str = None):
    with LOCK:
        u = find_user(need_user_id(viewer))
        if u["role"] == "worker":
            raise HTTPErr(403, "현황판은 안전 담당과 현장 책임자만 볼 수 있습니다")
        today = now().replace(hour=0, minute=0)
        d0 = today.strftime(FMT)
        d1 = (today + timedelta(days=1)).strftime(FMT)
        users = {x["user_id"]: x["name"] for x in q("SELECT * FROM wp_users")}
        rows = [r for r in q("SELECT * FROM wp_permits")
                if r["status"] != "closed" and r["start_at"] < d1 and r["end_at"] > d0]
        rows = sorted_permits(rows)
        zs = []
        for z in q("SELECT * FROM wp_zones ORDER BY ord"):
            zs.append({"zone_id": z["zone_id"], "name": z["name"], "permits": [
                {"permit_id": r["permit_id"], "work_type": r["work_type"], "status": eff_status(r),
                 "start_at": r["start_at"], "end_at": r["end_at"],
                 "requester_name": users.get(r["requester_id"])}
                for r in rows if r["zone_id"] == z["zone_id"]]})
        conflicts = []
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a["zone_id"] == b["zone_id"] and overlap(a, b) and is_pair(a, b) \
                        and (is_live(a) or is_live(b)):
                    conflicts.append({"zone_id": a["zone_id"],
                                      "permit_ids": sorted([a["permit_id"], b["permit_id"]])})
        return {"date": today.strftime("%Y-%m-%d"), "hours": list(range(6, 19)), "zones": zs,
                "conflicts": conflicts}
