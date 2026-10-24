import csv
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "qc.db")
DAYS = {"치명": 1, "중": 3, "경": 7}
LOCK = threading.RLock()

app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE qc_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE qc_lots(lot_id TEXT PRIMARY KEY, product TEXT, line TEXT, qty INTEGER);
    CREATE TABLE qc_symptoms(code TEXT PRIMARY KEY, label TEXT);
    CREATE TABLE qc_causes(code TEXT PRIMARY KEY, label TEXT);
    CREATE TABLE qc_defects(defect_id TEXT PRIMARY KEY, lot_id TEXT, symptom TEXT, severity TEXT,
        qty INTEGER, status TEXT, reporter TEXT, assignee TEXT, cause TEXT, reported_at TEXT,
        rework INTEGER, seq INTEGER);
    CREATE TABLE qc_history(defect_id TEXT, at TEXT, by TEXT, action TEXT, note TEXT);
    """)
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO qc_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("lots.csv"):
        con.execute("INSERT INTO qc_lots VALUES(?,?,?,?)", (r["lot_id"], r["product"], r["line"], int(r["qty"])))
    for r in read_csv("symptoms.csv"):
        con.execute("INSERT INTO qc_symptoms VALUES(?,?)", (r["code"], r["label"]))
    for r in read_csv("causes.csv"):
        con.execute("INSERT INTO qc_causes VALUES(?,?)", (r["code"], r["label"]))
    for i, r in enumerate(read_csv("defects.csv")):
        con.execute("INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["defect_id"], r["lot_id"], r["symptom"], r["severity"], int(r["qty"]), r["status"],
                     r["reporter"], r["assignee"] or None, r["cause"] or None, r["reported_at"],
                     int(r["rework"] or 0), i))
    con.commit()
    return con


DB = init_db()


def shape(row):
    reported = datetime.strptime(row["reported_at"][:10], "%Y-%m-%d").date()
    due = reported + timedelta(days=DAYS.get(row["severity"], 7))
    return {
        "defect_id": row["defect_id"], "lot_id": row["lot_id"], "product": row["product"], "line": row["line"],
        "symptom": row["symptom"], "severity": row["severity"], "qty": row["qty"], "status": row["status"],
        "reporter": row["reporter"], "assignee": row["assignee"], "cause": row["cause"],
        "reported_at": row["reported_at"], "due": due.isoformat(),
        "overdue": row["status"] != "closed" and date.today() > due, "rework": row["rework"],
    }


SELECT = ("SELECT d.*, l.product, l.line FROM qc_defects d LEFT JOIN qc_lots l ON l.lot_id=d.lot_id")


def get_one(did):
    row = DB.execute(SELECT + " WHERE d.defect_id=?", (did,)).fetchone()
    return shape(row) if row else None


async def read_body(request):
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        body = {}
    return body


def need_user(body):
    u = body.get("user")
    if not isinstance(u, str) or not u:
        raise Reject(400, "사용자를 확인하세요")
    return u


def find_user(uid):
    row = DB.execute("SELECT * FROM qc_users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return row


def log(did, by, action, note=""):
    DB.execute("INSERT INTO qc_history VALUES(?,?,?,?,?)",
               (did, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), by, action, note))


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")


@app.get("/api/users")
def users():
    return [dict(r) for r in DB.execute("SELECT user_id,name,role FROM qc_users ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    return [dict(r) for r in DB.execute("SELECT lot_id,product,line,qty FROM qc_lots ORDER BY rowid")]


@app.get("/api/symptoms")
def symptoms():
    return [dict(r) for r in DB.execute("SELECT code,label FROM qc_symptoms ORDER BY rowid")]


@app.get("/api/causes")
def causes():
    return [dict(r) for r in DB.execute("SELECT code,label FROM qc_causes ORDER BY rowid")]


@app.get("/api/defects")
def defects():
    with LOCK:
        rows = [shape(r) for r in DB.execute(SELECT + " ORDER BY d.reported_at, d.seq")]
    return {"defects": rows, "summary": {
        "open": sum(1 for d in rows if d["status"] != "closed"),
        "overdue": sum(1 for d in rows if d["overdue"]),
        "rework": sum(d["rework"] for d in rows)}}


@app.post("/api/defects")
async def create_defect(request: Request):
    body = await read_body(request)
    uid = need_user(body)
    severity, symptom, lot_id, qty = body.get("severity"), body.get("symptom"), body.get("lot_id"), body.get("qty")
    if not isinstance(lot_id, str) or not isinstance(symptom, str) or severity not in DAYS:
        raise Reject(400, "입력을 확인하세요")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise Reject(400, "수량을 확인하세요")
    with LOCK:
        find_user(uid)
        lot = DB.execute("SELECT * FROM qc_lots WHERE lot_id=?", (lot_id,)).fetchone()
        if not lot:
            raise Reject(404, "로트를 확인하세요")
        if not DB.execute("SELECT 1 FROM qc_symptoms WHERE code=?", (symptom,)).fetchone():
            raise Reject(400, "입력을 확인하세요")
        if qty > lot["qty"]:
            raise Reject(400, "수량을 확인하세요")
        if DB.execute("SELECT 1 FROM qc_defects WHERE lot_id=? AND symptom=? AND status!='closed'",
                      (lot_id, symptom)).fetchone():
            raise Reject(409, "이미 신고된 불량입니다")
        n = DB.execute("SELECT COUNT(*) FROM qc_defects").fetchone()[0] + 1
        while DB.execute("SELECT 1 FROM qc_defects WHERE defect_id=?", ("F%03d" % n,)).fetchone():
            n += 1
        did = "F%03d" % n
        seq = DB.execute("SELECT COALESCE(MAX(seq),0)+1 FROM qc_defects").fetchone()[0]
        DB.execute("INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (did, lot_id, symptom, severity, qty, "reported", uid, None, None,
                    datetime.now().strftime("%Y-%m-%d %H:%M"), 0, seq))
        log(did, uid, "report")
        DB.commit()
        return JSONResponse(get_one(did), status_code=201)


def state_check(d, needed):
    if d["status"] == "closed":
        raise Reject(409, "종결된 건입니다")
    if d["status"] != needed:
        raise Reject(409, "지금 상태에서는 할 수 없습니다")


@app.post("/api/defects/{defect_id}/{action}")
async def do_action(defect_id: str, action: str, request: Request):
    body = await read_body(request)
    uid = need_user(body)
    if action not in ("analyze", "fix", "verify"):
        raise Reject(404, "찾을 수 없는 동작입니다")
    # 본문만 보면 아는 것 (400)
    if action == "analyze":
        cause, assignee = body.get("cause"), body.get("assignee")
        if not isinstance(cause, str) or not isinstance(assignee, str):
            raise Reject(400, "원인과 담당자를 확인하세요")
    elif action == "fix":
        note = body.get("note")
        note = note.strip() if isinstance(note, str) else ""
        if not 1 <= len(note) <= 500:
            raise Reject(400, "조치 내용을 입력하세요")
    else:
        result = body.get("result")
        if result not in ("pass", "fail"):
            raise Reject(400, "입력을 확인하세요")
    with LOCK:
        d = get_one(defect_id)
        if not d:
            raise Reject(404, "불량 건을 찾을 수 없습니다")
        user = find_user(uid)
        # 권한 (403)
        if action == "analyze":
            if user["role"] != "quality":
                raise Reject(403, "품질팀만 할 수 있습니다")
        elif action == "fix":
            if d["assignee"] != uid:
                raise Reject(403, "담당자만 조치를 등록할 수 있습니다")
        else:
            if user["role"] != "quality":
                raise Reject(403, "품질팀만 할 수 있습니다")
            if d["assignee"] == uid:
                raise Reject(403, "본인 조치는 검증할 수 없습니다")
            if d["reporter"] == uid:
                raise Reject(403, "신고자는 검증할 수 없습니다")
        # 목록에서 찾아야 아는 입력 (400)
        if action == "analyze":
            a = DB.execute("SELECT role FROM qc_users WHERE user_id=?", (assignee,)).fetchone()
            if not DB.execute("SELECT 1 FROM qc_causes WHERE code=?", (cause,)).fetchone() \
                    or not a or a["role"] != "quality":
                raise Reject(400, "원인과 담당자를 확인하세요")
        # 상태 (409)
        state_check(d, {"analyze": "reported", "fix": "fixing", "verify": "verifying"}[action])
        if action == "analyze":
            DB.execute("UPDATE qc_defects SET status='fixing', cause=?, assignee=? WHERE defect_id=?",
                       (cause, assignee, defect_id))
            log(defect_id, uid, action, "%s/%s" % (cause, assignee))
        elif action == "fix":
            DB.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (defect_id,))
            log(defect_id, uid, action, note)
        elif result == "pass":
            DB.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (defect_id,))
            log(defect_id, uid, action, "pass")
        else:
            DB.execute("UPDATE qc_defects SET status='fixing', rework=rework+1 WHERE defect_id=?", (defect_id,))
            log(defect_id, uid, action, "fail")
        DB.commit()
        return get_one(defect_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
