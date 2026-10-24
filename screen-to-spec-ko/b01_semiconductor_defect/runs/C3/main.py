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
DAYS = {"치명": 1, "중": 3, "경": 7}

app = FastAPI()
conn = None


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global conn
    if conn:
        conn.close()
    for suffix in ("", "-journal"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE qc_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE qc_lots(lot_id TEXT PRIMARY KEY, product TEXT, line TEXT, qty INTEGER);
    CREATE TABLE qc_symptoms(code TEXT PRIMARY KEY, label TEXT);
    CREATE TABLE qc_causes(code TEXT PRIMARY KEY, label TEXT);
    CREATE TABLE qc_defects(defect_id TEXT PRIMARY KEY, lot_id TEXT, symptom TEXT, severity TEXT,
        qty INTEGER, status TEXT, reporter TEXT, assignee TEXT, cause TEXT, reported_at TEXT, rework INTEGER);
    CREATE TABLE qc_history(defect_id TEXT, at TEXT, by TEXT, action TEXT, note TEXT);
    """)
    for r in read_csv("users.csv"):
        conn.execute("INSERT INTO qc_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("lots.csv"):
        conn.execute("INSERT INTO qc_lots VALUES(?,?,?,?)", (r["lot_id"], r["product"], r["line"], int(r["qty"])))
    for r in read_csv("symptoms.csv"):
        conn.execute("INSERT INTO qc_symptoms VALUES(?,?)", (r["code"], r["label"]))
    for r in read_csv("causes.csv"):
        conn.execute("INSERT INTO qc_causes VALUES(?,?)", (r["code"], r["label"]))
    for r in read_csv("defects.csv"):
        conn.execute("INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (r["defect_id"], r["lot_id"], r["symptom"], r["severity"], int(r["qty"]), r["status"],
                      r["reporter"], r["assignee"] or None, r["cause"] or None, r["reported_at"],
                      int(r["rework"] or 0)))
    conn.commit()


init_db()


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


def need_user(b):
    u = b.get("user")
    if not isinstance(u, str) or not u:
        raise Reject(400, "사용자를 확인하세요")
    return u


def find_user(uid):
    u = conn.execute("SELECT * FROM qc_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return u


def shape(r):
    due = (datetime.strptime(r["reported_at"][:10], "%Y-%m-%d").date() + timedelta(days=DAYS.get(r["severity"], 0)))
    return {
        "defect_id": r["defect_id"], "lot_id": r["lot_id"], "product": r["product"], "line": r["line"],
        "symptom": r["symptom"], "severity": r["severity"], "qty": r["qty"], "status": r["status"],
        "reporter": r["reporter"], "assignee": r["assignee"], "cause": r["cause"],
        "reported_at": r["reported_at"], "due": due.isoformat(),
        "overdue": r["status"] != "closed" and date.today() > due, "rework": r["rework"],
    }


SELECT = ("SELECT d.*, l.product, l.line FROM qc_defects d LEFT JOIN qc_lots l ON l.lot_id=d.lot_id")


def get_one(did):
    r = conn.execute(SELECT + " WHERE d.defect_id=?", (did,)).fetchone()
    return shape(r) if r else None


def log(did, by, action, note=""):
    conn.execute("INSERT INTO qc_history VALUES(?,?,?,?,?)",
                 (did, datetime.now().strftime("%Y-%m-%d %H:%M"), by, action, note))


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with LOCK:
        return [dict(r) for r in conn.execute("SELECT * FROM qc_users ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    with LOCK:
        return [dict(r) for r in conn.execute("SELECT * FROM qc_lots ORDER BY rowid")]


@app.get("/api/symptoms")
def symptoms():
    with LOCK:
        return [dict(r) for r in conn.execute("SELECT * FROM qc_symptoms ORDER BY rowid")]


@app.get("/api/causes")
def causes():
    with LOCK:
        return [dict(r) for r in conn.execute("SELECT * FROM qc_causes ORDER BY rowid")]


@app.get("/api/defects")
def defects():
    with LOCK:
        rows = [shape(r) for r in conn.execute(SELECT + " ORDER BY d.reported_at, d.defect_id")]
    return {"defects": rows, "summary": {
        "open": sum(1 for d in rows if d["status"] != "closed"),
        "overdue": sum(1 for d in rows if d["overdue"]),
        "rework": sum(d["rework"] for d in rows)}}


@app.post("/api/defects")
async def report(request: Request):
    b = await body_of(request)
    uid = need_user(b)
    lot_id, symptom, sev, qty = b.get("lot_id"), b.get("symptom"), b.get("severity"), b.get("qty")
    with LOCK:
        if not isinstance(lot_id, str) or not isinstance(symptom, str) or sev not in DAYS:
            raise Reject(400, "입력을 확인하세요")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise Reject(400, "수량을 확인하세요")
        if not conn.execute("SELECT 1 FROM qc_symptoms WHERE code=?", (symptom,)).fetchone():
            raise Reject(400, "입력을 확인하세요")
        lot = conn.execute("SELECT * FROM qc_lots WHERE lot_id=?", (lot_id,)).fetchone()
        if not lot:
            raise Reject(404, "로트를 확인하세요")
        find_user(uid)
        if qty > lot["qty"]:
            raise Reject(400, "수량을 확인하세요")
        if conn.execute("SELECT 1 FROM qc_defects WHERE lot_id=? AND symptom=? AND status!='closed'",
                        (lot_id, symptom)).fetchone():
            raise Reject(409, "이미 신고된 불량입니다")
        n = 1
        for (i,) in conn.execute("SELECT defect_id FROM qc_defects"):
            digits = "".join(c for c in i if c.isdigit())
            if digits:
                n = max(n, int(digits) + 1)
        did = "F%03d" % n
        while conn.execute("SELECT 1 FROM qc_defects WHERE defect_id=?", (did,)).fetchone():
            n += 1
            did = "F%03d" % n
        conn.execute("INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,0)",
                     (did, lot_id, symptom, sev, qty, "reported", uid, None, None,
                      datetime.now().strftime("%Y-%m-%d %H:%M")))
        log(did, uid, "report")
        conn.commit()
        return JSONResponse(get_one(did), status_code=201)


def state_check(d, expect):
    if d["status"] == "closed":
        raise Reject(409, "종결된 건입니다")
    if d["status"] != expect:
        raise Reject(409, "지금 상태에서는 할 수 없습니다")


@app.post("/api/defects/{defect_id}/{action}")
async def do_action(defect_id: str, action: str, request: Request):
    if action not in ("analyze", "fix", "verify"):
        raise Reject(404, "찾을 수 없습니다")
    b = await body_of(request)
    uid = need_user(b)
    with LOCK:
        if action == "analyze":
            cause, assignee = b.get("cause"), b.get("assignee")
            ok = isinstance(cause, str) and isinstance(assignee, str)
            if ok:
                ok = bool(conn.execute("SELECT 1 FROM qc_causes WHERE code=?", (cause,)).fetchone()) and bool(
                    conn.execute("SELECT 1 FROM qc_users WHERE user_id=? AND role='quality'", (assignee,)).fetchone())
            if not ok:
                raise Reject(400, "원인과 담당자를 확인하세요")
        elif action == "fix":
            note = b.get("note")
            if not isinstance(note, str) or not (1 <= len(note.strip()) <= 500):
                raise Reject(400, "조치 내용을 입력하세요")
            note = note.strip()
        else:
            result = b.get("result")
            if result not in ("pass", "fail"):
                raise Reject(400, "입력을 확인하세요")

        d = get_one(defect_id)
        if not d:
            raise Reject(404, "불량 건을 찾을 수 없습니다")
        user = find_user(uid)

        if action == "analyze":
            if user["role"] != "quality":
                raise Reject(403, "품질팀만 할 수 있습니다")
            state_check(d, "reported")
            conn.execute("UPDATE qc_defects SET status='fixing', cause=?, assignee=? WHERE defect_id=?",
                         (cause, assignee, defect_id))
            log(defect_id, uid, "analyze", "%s/%s" % (cause, assignee))
        elif action == "fix":
            if d["assignee"] != uid:
                raise Reject(403, "담당자만 조치를 등록할 수 있습니다")
            state_check(d, "fixing")
            conn.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (defect_id,))
            log(defect_id, uid, "fix", note)
        else:
            if user["role"] != "quality":
                raise Reject(403, "품질팀만 할 수 있습니다")
            if d["assignee"] == uid:
                raise Reject(403, "본인 조치는 검증할 수 없습니다")
            if d["reporter"] == uid:
                raise Reject(403, "신고자는 검증할 수 없습니다")
            state_check(d, "verifying")
            if result == "pass":
                conn.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (defect_id,))
            else:
                conn.execute("UPDATE qc_defects SET status='fixing', rework=rework+1 WHERE defect_id=?",
                             (defect_id,))
            log(defect_id, uid, "verify", result)
        conn.commit()
        return get_one(defect_id)
