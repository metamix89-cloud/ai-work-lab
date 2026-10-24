import csv
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "qc.db")

SEVERITY_DAYS = {"치명": 1, "중": 3, "경": 7}
STATUSES = ("reported", "fixing", "verifying", "closed")

LOCK = threading.RLock()
DB = None


def read_csv(name):
    with open(os.path.join(SEED, name), newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def init_db():
    global DB
    with LOCK:
        if DB is not None:
            DB.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(DB_PATH + suffix)
            except FileNotFoundError:
                pass
        db = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            CREATE TABLE qc_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
            CREATE TABLE qc_lots(lot_id TEXT PRIMARY KEY, product TEXT, line TEXT, qty INTEGER);
            CREATE TABLE qc_symptoms(code TEXT PRIMARY KEY, label TEXT);
            CREATE TABLE qc_causes(code TEXT PRIMARY KEY, label TEXT);
            CREATE TABLE qc_defects(
                defect_id TEXT PRIMARY KEY, lot_id TEXT, symptom TEXT, severity TEXT,
                qty INTEGER, status TEXT, reporter TEXT, assignee TEXT, cause TEXT,
                reported_at TEXT, rework INTEGER);
            CREATE TABLE qc_history(defect_id TEXT, at TEXT, "by" TEXT, action TEXT, note TEXT);
            """
        )
        for r in read_csv("users.csv"):
            db.execute("INSERT INTO qc_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
        for r in read_csv("lots.csv"):
            db.execute("INSERT INTO qc_lots VALUES(?,?,?,?)",
                       (r["lot_id"], r["product"], r["line"], int(r["qty"])))
        for r in read_csv("symptoms.csv"):
            db.execute("INSERT INTO qc_symptoms VALUES(?,?)", (r["code"], r["label"]))
        for r in read_csv("causes.csv"):
            db.execute("INSERT INTO qc_causes VALUES(?,?)", (r["code"], r["label"]))
        for r in read_csv("defects.csv"):
            db.execute(
                "INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (r["defect_id"], r["lot_id"], r["symptom"], r["severity"], int(r["qty"]),
                 r["status"], r["reporter"], r["assignee"] or None, r["cause"] or None,
                 r["reported_at"], int(r["rework"] or 0)),
            )
        db.commit()
        DB = db


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
init_db()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


async def read_body(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def q(sql, args=()):
    return DB.execute(sql, args).fetchall()


def q1(sql, args=()):
    return DB.execute(sql, args).fetchone()


def defect_view(row):
    lot = q1("SELECT product, line FROM qc_lots WHERE lot_id=?", (row["lot_id"],))
    sym = q1("SELECT label FROM qc_symptoms WHERE code=?", (row["symptom"],))
    cause = q1("SELECT label FROM qc_causes WHERE code=?", (row["cause"],)) if row["cause"] else None
    reporter = q1("SELECT name FROM qc_users WHERE user_id=?", (row["reporter"],))
    assignee = q1("SELECT name FROM qc_users WHERE user_id=?", (row["assignee"],)) if row["assignee"] else None
    reported_day = datetime.strptime(row["reported_at"][:10], "%Y-%m-%d").date()
    due = reported_day + timedelta(days=SEVERITY_DAYS.get(row["severity"], 7))
    overdue = row["status"] != "closed" and date.today() > due
    return {
        "defect_id": row["defect_id"],
        "lot_id": row["lot_id"],
        "product": lot["product"] if lot else None,
        "line": lot["line"] if lot else None,
        "symptom": row["symptom"],
        "symptom_label": sym["label"] if sym else row["symptom"],
        "severity": row["severity"],
        "qty": row["qty"],
        "status": row["status"],
        "reporter": row["reporter"],
        "reporter_name": reporter["name"] if reporter else row["reporter"],
        "assignee": row["assignee"],
        "assignee_name": assignee["name"] if assignee else None,
        "cause": row["cause"],
        "cause_label": cause["label"] if cause else None,
        "reported_at": row["reported_at"],
        "due": due.isoformat(),
        "overdue": overdue,
        "rework": row["rework"],
    }


def get_defect_view(defect_id):
    return defect_view(q1("SELECT * FROM qc_defects WHERE defect_id=?", (defect_id,)))


def log(defect_id, user, action, note=""):
    DB.execute('INSERT INTO qc_history(defect_id, at, "by", action, note) VALUES(?,?,?,?,?)',
               (defect_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user, action, note))


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with LOCK:
        return [dict(r) for r in q("SELECT user_id, name, role FROM qc_users ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    with LOCK:
        return [dict(r) for r in q("SELECT lot_id, product, line, qty FROM qc_lots ORDER BY rowid")]


@app.get("/api/symptoms")
def symptoms():
    with LOCK:
        return [dict(r) for r in q("SELECT code, label FROM qc_symptoms ORDER BY rowid")]


@app.get("/api/causes")
def causes():
    with LOCK:
        return [dict(r) for r in q("SELECT code, label FROM qc_causes ORDER BY rowid")]


@app.get("/api/defects")
def defects():
    with LOCK:
        rows = q("SELECT * FROM qc_defects ORDER BY reported_at, defect_id")
        items = [defect_view(r) for r in rows]
    return {
        "defects": items,
        "summary": {
            "open": sum(1 for d in items if d["status"] != "closed"),
            "overdue": sum(1 for d in items if d["overdue"]),
            "rework": sum(d["rework"] for d in items),
        },
    }


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@app.post("/api/defects", status_code=201)
async def create_defect(request: Request):
    body = await read_body(request)
    user_id = body.get("user")
    lot_id, symptom, severity, qty = (body.get(k) for k in ("lot_id", "symptom", "severity", "qty"))
    if not isinstance(user_id, str):
        raise Reject(400, "사용자를 확인하세요")
    if not isinstance(lot_id, str) or not isinstance(symptom, str) or severity not in SEVERITY_DAYS:
        raise Reject(400, "입력을 확인하세요")
    if not is_int(qty) or qty < 1:
        raise Reject(400, "수량을 확인하세요")
    with LOCK:
        if not q1("SELECT 1 FROM qc_users WHERE user_id=?", (user_id,)):
            raise Reject(404, "사용자를 확인하세요")
        lot = q1("SELECT * FROM qc_lots WHERE lot_id=?", (lot_id,))
        if not lot:
            raise Reject(404, "로트를 확인하세요")
        if not q1("SELECT 1 FROM qc_symptoms WHERE code=?", (symptom,)):
            raise Reject(400, "입력을 확인하세요")
        if qty > lot["qty"]:
            raise Reject(400, "수량을 확인하세요")
        if q1("SELECT 1 FROM qc_defects WHERE lot_id=? AND symptom=? AND status!='closed'",
              (lot_id, symptom)):
            raise Reject(409, "이미 신고된 불량입니다")
        existing = {r["defect_id"] for r in q("SELECT defect_id FROM qc_defects")}
        n = len(existing) + 1
        while f"F{n:03d}" in existing:
            n += 1
        defect_id = f"F{n:03d}"
        DB.execute(
            "INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (defect_id, lot_id, symptom, severity, qty, "reported", user_id, None, None,
             datetime.now().strftime("%Y-%m-%d %H:%M"), 0),
        )
        log(defect_id, user_id, "report")
        DB.commit()
        return get_defect_view(defect_id)


@app.post("/api/defects/{defect_id}/{action}")
async def act_on_defect(defect_id: str, action: str, request: Request):
    if action not in ("analyze", "fix", "verify"):
        raise Reject(404, "찾을 수 없습니다")
    body = await read_body(request)
    user_id = body.get("user")
    if not isinstance(user_id, str):
        raise Reject(400, "사용자를 확인하세요")

    # 1) 본문만 보면 아는 것 (400)
    cause = assignee_id = note = result = None
    if action == "analyze":
        cause, assignee_id = body.get("cause"), body.get("assignee")
        if not isinstance(cause, str) or not isinstance(assignee_id, str):
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
        # 2) 없는 건 · 사용자 (404)
        row = q1("SELECT * FROM qc_defects WHERE defect_id=?", (defect_id,))
        if not row:
            raise Reject(404, "불량을 찾을 수 없습니다")
        user = q1("SELECT * FROM qc_users WHERE user_id=?", (user_id,))
        if not user:
            raise Reject(404, "사용자를 확인하세요")

        # 3) 권한 (403)
        is_quality = user["role"] == "quality"
        if action == "analyze":
            if not is_quality:
                raise Reject(403, "품질팀만 할 수 있습니다")
        elif action == "fix":
            if row["assignee"] is None or row["assignee"] != user_id:
                raise Reject(403, "담당자만 조치를 등록할 수 있습니다")
        else:
            if not is_quality:
                raise Reject(403, "품질팀만 할 수 있습니다")
            if row["assignee"] == user_id:
                raise Reject(403, "본인 조치는 검증할 수 없습니다")
            if row["reporter"] == user_id:
                raise Reject(403, "신고자는 검증할 수 없습니다")

        # 원인 · 담당자 확인 (목록을 찾아야 아는 입력 오류)
        if action == "analyze":
            target = q1("SELECT role FROM qc_users WHERE user_id=?", (assignee_id,))
            if not q1("SELECT 1 FROM qc_causes WHERE code=?", (cause,)) \
                    or not target or target["role"] != "quality":
                raise Reject(400, "원인과 담당자를 확인하세요")

        # 4) 상태 (409)
        if row["status"] == "closed":
            raise Reject(409, "종결된 건입니다")
        required = {"analyze": "reported", "fix": "fixing", "verify": "verifying"}[action]
        if row["status"] != required:
            raise Reject(409, "지금 상태에서는 할 수 없습니다")

        if action == "analyze":
            DB.execute("UPDATE qc_defects SET status='fixing', cause=?, assignee=? WHERE defect_id=?",
                       (cause, assignee_id, defect_id))
            log(defect_id, user_id, "analyze", f"{cause}/{assignee_id}")
        elif action == "fix":
            DB.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (defect_id,))
            log(defect_id, user_id, "fix", note)
        elif result == "pass":
            DB.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (defect_id,))
            log(defect_id, user_id, "verify", "pass")
        else:
            DB.execute("UPDATE qc_defects SET status='fixing', rework=rework+1 WHERE defect_id=?",
                       (defect_id,))
            log(defect_id, user_id, "verify", "fail")
        DB.commit()
        return get_defect_view(defect_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
