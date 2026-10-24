import csv
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "qc.db")
LOCK = threading.Lock()

SEVERITY_DAYS = {"치명": 1, "중": 3, "경": 7}
STATUSES = ("reported", "fixing", "verifying", "closed")

SCHEMA = """
CREATE TABLE qc_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
CREATE TABLE qc_lots (lot_id TEXT PRIMARY KEY, product TEXT, line TEXT, qty INTEGER);
CREATE TABLE qc_symptoms (code TEXT PRIMARY KEY, label TEXT);
CREATE TABLE qc_causes (code TEXT PRIMARY KEY, label TEXT);
CREATE TABLE qc_defects (defect_id TEXT PRIMARY KEY, lot_id TEXT, symptom TEXT, severity TEXT,
  qty INTEGER, status TEXT, reporter TEXT, assignee TEXT, cause TEXT, reported_at TEXT, rework INTEGER);
CREATE TABLE qc_history (defect_id TEXT, at TEXT, by TEXT, action TEXT, note TEXT);
"""


def read_csv(name):
    path = os.path.join(SEED, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    c = conn()
    c.executescript(SCHEMA)
    for r in read_csv("users.csv"):
        c.execute("INSERT OR REPLACE INTO qc_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("lots.csv"):
        c.execute("INSERT OR REPLACE INTO qc_lots VALUES (?,?,?,?)", (r["lot_id"], r["product"], r["line"], to_int(r["qty"])))
    for n, t in (("symptoms.csv", "qc_symptoms"), ("causes.csv", "qc_causes")):
        for r in read_csv(n):
            c.execute("INSERT OR REPLACE INTO %s VALUES (?,?)" % t, (r["code"], r["label"]))
    for r in read_csv("defects.csv"):
        c.execute("INSERT OR REPLACE INTO qc_defects VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (r["defect_id"], r["lot_id"], r["symptom"], r["severity"], to_int(r["qty"]), r["status"],
                   r["reporter"], (r.get("assignee") or "").strip() or None, (r.get("cause") or "").strip() or None,
                   r["reported_at"], to_int(r.get("rework"))))
    c.commit()
    c.close()


init_db()
app = FastAPI()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


async def body_of(request: Request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def check_user_field(b):
    u = b.get("user")
    if not isinstance(u, str) or not u.strip():
        raise Reject(400, "사용자를 확인하세요")
    return u


def get_user(c, uid):
    u = c.execute("SELECT * FROM qc_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return u


def shape(r):
    try:
        rep = datetime.strptime(r["reported_at"][:10], "%Y-%m-%d").date()
        due = rep + timedelta(days=SEVERITY_DAYS.get(r["severity"], 0))
    except (ValueError, TypeError):
        due = None
    overdue = bool(due and r["status"] != "closed" and date.today() > due)
    return {
        "defect_id": r["defect_id"], "lot_id": r["lot_id"], "product": r["product"], "line": r["line"],
        "symptom": r["symptom"], "severity": r["severity"], "qty": r["qty"], "status": r["status"],
        "reporter": r["reporter"], "assignee": r["assignee"], "cause": r["cause"],
        "reported_at": r["reported_at"], "due": due.isoformat() if due else None,
        "overdue": overdue, "rework": r["rework"],
    }


DEFECT_SQL = ("SELECT d.*, l.product AS product, l.line AS line FROM qc_defects d "
              "LEFT JOIN qc_lots l ON l.lot_id=d.lot_id ")


def fetch_one(c, did):
    r = c.execute(DEFECT_SQL + "WHERE d.defect_id=?", (did,)).fetchone()
    return shape(r) if r else None


def log(c, did, by, action, note=""):
    c.execute("INSERT INTO qc_history VALUES (?,?,?,?,?)",
              (did, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), by, action, note))


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")


def listing(sql):
    c = conn()
    try:
        return [dict(r) for r in c.execute(sql).fetchall()]
    finally:
        c.close()


@app.get("/api/users")
def users():
    return listing("SELECT user_id, name, role FROM qc_users ORDER BY rowid")


@app.get("/api/lots")
def lots():
    return listing("SELECT lot_id, product, line, qty FROM qc_lots ORDER BY rowid")


@app.get("/api/symptoms")
def symptoms():
    return listing("SELECT code, label FROM qc_symptoms ORDER BY rowid")


@app.get("/api/causes")
def causes():
    return listing("SELECT code, label FROM qc_causes ORDER BY rowid")


@app.get("/api/defects")
def defects():
    c = conn()
    try:
        rows = [shape(r) for r in c.execute(DEFECT_SQL + "ORDER BY d.reported_at, d.defect_id").fetchall()]
    finally:
        c.close()
    return {"defects": rows, "summary": {
        "open": sum(1 for d in rows if d["status"] != "closed"),
        "overdue": sum(1 for d in rows if d["overdue"]),
        "rework": sum(d["rework"] for d in rows),
    }}


@app.post("/api/defects")
async def create_defect(request: Request):
    b = await body_of(request)
    uid = check_user_field(b)
    lot_id, symptom, severity, qty = b.get("lot_id"), b.get("symptom"), b.get("severity"), b.get("qty")
    if (not isinstance(lot_id, str) or not isinstance(symptom, str) or severity not in SEVERITY_DAYS
            or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1):
        # 수량 모양이 틀린 경우는 수량 문구, 나머지는 입력 문구
        if isinstance(lot_id, str) and isinstance(symptom, str) and severity in SEVERITY_DAYS:
            raise Reject(400, "수량을 확인하세요")
        raise Reject(400, "입력을 확인하세요")
    with LOCK:
        c = conn()
        try:
            get_user(c, uid)
            lot = c.execute("SELECT * FROM qc_lots WHERE lot_id=?", (lot_id,)).fetchone()
            if not lot:
                raise Reject(404, "로트를 확인하세요")
            if not c.execute("SELECT 1 FROM qc_symptoms WHERE code=?", (symptom,)).fetchone():
                raise Reject(400, "입력을 확인하세요")
            if qty > lot["qty"]:
                raise Reject(400, "수량을 확인하세요")
            if c.execute("SELECT 1 FROM qc_defects WHERE lot_id=? AND symptom=? AND status!='closed'",
                         (lot_id, symptom)).fetchone():
                raise Reject(409, "이미 신고된 불량입니다")
            n = 1 + max([to_int(r[0][1:], 0) for r in c.execute("SELECT defect_id FROM qc_defects").fetchall()
                         if r[0][:1] == "F"] + [0])
            did = "F%03d" % n
            while c.execute("SELECT 1 FROM qc_defects WHERE defect_id=?", (did,)).fetchone():
                n += 1
                did = "F%03d" % n
            c.execute("INSERT INTO qc_defects VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (did, lot_id, symptom, severity, qty, "reported", uid, None, None,
                       datetime.now().strftime("%Y-%m-%d %H:%M"), 0))
            log(c, did, uid, "report")
            c.commit()
            return JSONResponse(fetch_one(c, did), status_code=201)
        finally:
            c.close()


@app.post("/api/defects/{defect_id}/{action}")
async def act(defect_id: str, action: str, request: Request):
    b = await body_of(request)
    uid = check_user_field(b)
    if action not in ("analyze", "fix", "verify"):
        raise Reject(404, "찾을 수 없습니다")
    # 본문만 보면 아는 것(400)
    if action == "analyze":
        cause, assignee = b.get("cause"), b.get("assignee")
        if not isinstance(cause, str) or not isinstance(assignee, str):
            raise Reject(400, "원인과 담당자를 확인하세요")
    elif action == "fix":
        note = b.get("note")
        note = note.strip() if isinstance(note, str) else ""
        if not 1 <= len(note) <= 500:
            raise Reject(400, "조치 내용을 입력하세요")
    else:
        if b.get("result") not in ("pass", "fail"):
            raise Reject(400, "입력을 확인하세요")
    with LOCK:
        c = conn()
        try:
            d = c.execute("SELECT * FROM qc_defects WHERE defect_id=?", (defect_id,)).fetchone()
            if not d:
                raise Reject(404, "불량 건을 찾을 수 없습니다")
            user = get_user(c, uid)
            # 권한(403)
            if action == "analyze":
                if user["role"] != "quality":
                    raise Reject(403, "품질팀만 할 수 있습니다")
            elif action == "fix":
                if d["assignee"] and d["assignee"] != uid:
                    raise Reject(403, "담당자만 조치를 등록할 수 있습니다")
            else:
                if user["role"] != "quality":
                    raise Reject(403, "품질팀만 할 수 있습니다")
                if d["assignee"] == uid:
                    raise Reject(403, "본인 조치는 검증할 수 없습니다")
                if d["reporter"] == uid:
                    raise Reject(403, "신고자는 검증할 수 없습니다")
            # 상태(409) 앞의 값 확인 — 원인/담당자 목록 대조(400)
            if action == "analyze":
                a = c.execute("SELECT role FROM qc_users WHERE user_id=?", (assignee,)).fetchone()
                if (not c.execute("SELECT 1 FROM qc_causes WHERE code=?", (cause,)).fetchone()
                        or not a or a["role"] != "quality"):
                    raise Reject(400, "원인과 담당자를 확인하세요")
            # 상태(409)
            if d["status"] == "closed":
                raise Reject(409, "종결된 건입니다")
            need = {"analyze": "reported", "fix": "fixing", "verify": "verifying"}[action]
            if d["status"] != need:
                raise Reject(409, "지금 상태에서는 할 수 없습니다")
            if action == "analyze":
                c.execute("UPDATE qc_defects SET status='fixing', cause=?, assignee=? WHERE defect_id=?",
                          (cause, assignee, defect_id))
                log(c, defect_id, uid, action, "%s/%s" % (cause, assignee))
            elif action == "fix":
                c.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (defect_id,))
                log(c, defect_id, uid, action, note)
            elif b["result"] == "pass":
                c.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (defect_id,))
                log(c, defect_id, uid, action, "pass")
            else:
                c.execute("UPDATE qc_defects SET status='fixing', rework=rework+1 WHERE defect_id=?", (defect_id,))
                log(c, defect_id, uid, action, "fail")
            c.commit()
            return fetch_one(c, defect_id)
        finally:
            c.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
