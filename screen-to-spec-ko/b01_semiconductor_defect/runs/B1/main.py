import csv
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "qc.db"
DUE_DAYS = {"치명": 1, "중": 3, "경": 7}
SEVERITIES = tuple(DUE_DAYS)

app = FastAPI()
lock = threading.RLock()


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE qc_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE qc_lots(lot_id TEXT PRIMARY KEY, product TEXT, line TEXT, qty INTEGER);
        CREATE TABLE qc_symptoms(code TEXT PRIMARY KEY, label TEXT);
        CREATE TABLE qc_causes(code TEXT PRIMARY KEY, label TEXT);
        CREATE TABLE qc_defects(defect_id TEXT PRIMARY KEY, lot_id TEXT, symptom TEXT,
            severity TEXT, qty INTEGER, status TEXT, reporter TEXT, assignee TEXT,
            cause TEXT, reported_at TEXT, rework INTEGER, seq INTEGER);
        CREATE TABLE qc_history(defect_id TEXT, at TEXT, by TEXT, action TEXT, note TEXT);
        """
    )
    for r in read_csv("users.csv"):
        db.execute("INSERT INTO qc_users VALUES(?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("lots.csv"):
        db.execute("INSERT INTO qc_lots VALUES(?,?,?,?)", (r["lot_id"], r["product"], r["line"], int(r["qty"])))
    for r in read_csv("symptoms.csv"):
        db.execute("INSERT INTO qc_symptoms VALUES(?,?)", (r["code"], r["label"]))
    for r in read_csv("causes.csv"):
        db.execute("INSERT INTO qc_causes VALUES(?,?)", (r["code"], r["label"]))
    for i, r in enumerate(read_csv("defects.csv")):
        db.execute(
            "INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["defect_id"], r["lot_id"], r["symptom"], r["severity"], int(r["qty"]),
             r["status"], r["reporter"], r["assignee"] or None, r["cause"] or None,
             r["reported_at"], int(r["rework"] or 0), i),
        )
    db.commit()
    return db


db = init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def due_of(row):
    d = datetime.strptime(row["reported_at"][:10], "%Y-%m-%d").date()
    return d + timedelta(days=DUE_DAYS[row["severity"]])


def shape(row):
    due = due_of(row)
    lot = db.execute("SELECT * FROM qc_lots WHERE lot_id=?", (row["lot_id"],)).fetchone()
    return {
        "defect_id": row["defect_id"],
        "lot_id": row["lot_id"],
        "product": lot["product"] if lot else None,
        "line": lot["line"] if lot else None,
        "symptom": row["symptom"],
        "severity": row["severity"],
        "qty": row["qty"],
        "status": row["status"],
        "reporter": row["reporter"],
        "assignee": row["assignee"],
        "cause": row["cause"],
        "reported_at": row["reported_at"],
        "due": due.isoformat(),
        "overdue": row["status"] != "closed" and date.today() > due,
        "rework": row["rework"],
    }


def history(defect_id, by, action, note=""):
    db.execute(
        "INSERT INTO qc_history VALUES(?,?,?,?,?)",
        (defect_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), by, action, note),
    )


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def rows(table, order):
    with lock:
        return [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]


@app.get("/api/users")
def users():
    return rows("qc_users", "rowid")


@app.get("/api/lots")
def lots():
    return rows("qc_lots", "rowid")


@app.get("/api/symptoms")
def symptoms():
    return rows("qc_symptoms", "rowid")


@app.get("/api/causes")
def causes():
    return rows("qc_causes", "rowid")


@app.get("/api/defects")
def defects():
    with lock:
        out = [shape(r) for r in db.execute("SELECT * FROM qc_defects ORDER BY reported_at, seq")]
    return {
        "defects": out,
        "summary": {
            "open": sum(1 for d in out if d["status"] != "closed"),
            "overdue": sum(1 for d in out if d["overdue"]),
            "rework": sum(d["rework"] for d in out),
        },
    }


def get_user(uid):
    return db.execute("SELECT * FROM qc_users WHERE user_id=?", (uid,)).fetchone()


@app.post("/api/defects")
async def create_defect(request: Request):
    b = await body_of(request)
    uid = b.get("user")
    if not isinstance(uid, str):
        return err(400, "사용자를 확인하세요")
    lot_id, symptom, severity, qty = b.get("lot_id"), b.get("symptom"), b.get("severity"), b.get("qty")
    if severity not in SEVERITIES or not isinstance(lot_id, str) or not isinstance(symptom, str):
        return err(400, "입력을 확인하세요")
    if not is_int(qty) or qty < 1:
        return err(400, "수량을 확인하세요")
    with lock:
        if not db.execute("SELECT 1 FROM qc_symptoms WHERE code=?", (symptom,)).fetchone():
            return err(400, "입력을 확인하세요")
        if not get_user(uid):
            return err(404, "사용자를 확인하세요")
        lot = db.execute("SELECT * FROM qc_lots WHERE lot_id=?", (lot_id,)).fetchone()
        if not lot:
            return err(404, "로트를 확인하세요")
        if qty > lot["qty"]:
            return err(400, "수량을 확인하세요")
        if db.execute(
            "SELECT 1 FROM qc_defects WHERE lot_id=? AND symptom=? AND status!='closed'", (lot_id, symptom)
        ).fetchone():
            return err(409, "이미 신고된 불량입니다")
        nums = [int(r["defect_id"][1:]) for r in db.execute("SELECT defect_id FROM qc_defects")
                if r["defect_id"][1:].isdigit()]
        n = max(nums, default=0) + 1
        did = f"F{n:03d}"
        while db.execute("SELECT 1 FROM qc_defects WHERE defect_id=?", (did,)).fetchone():
            n += 1
            did = f"F{n:03d}"
        seq = db.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM qc_defects").fetchone()[0]
        db.execute(
            "INSERT INTO qc_defects VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (did, lot_id, symptom, severity, qty, "reported", uid, None, None,
             datetime.now().strftime("%Y-%m-%d %H:%M"), 0, seq),
        )
        history(did, uid, "report")
        db.commit()
        row = db.execute("SELECT * FROM qc_defects WHERE defect_id=?", (did,)).fetchone()
        return JSONResponse(shape(row), status_code=201)


@app.post("/api/defects/{defect_id}/{action}")
async def act(defect_id: str, action: str, request: Request):
    b = await body_of(request)
    uid = b.get("user")
    if not isinstance(uid, str):
        return err(400, "사용자를 확인하세요")
    if action not in ("analyze", "fix", "verify"):
        return err(404, "없는 동작입니다")
    note = ""
    with lock:
        # 1) 본문만 보면 아는 것 (400)
        if action == "analyze":
            cause, assignee = b.get("cause"), b.get("assignee")
            ok = (
                isinstance(cause, str) and isinstance(assignee, str)
                and db.execute("SELECT 1 FROM qc_causes WHERE code=?", (cause,)).fetchone()
                and db.execute("SELECT 1 FROM qc_users WHERE user_id=? AND role='quality'", (assignee,)).fetchone()
            )
            if not ok:
                return err(400, "원인과 담당자를 확인하세요")
        elif action == "fix":
            note = b.get("note")
            if not isinstance(note, str) or not (1 <= len(note.strip()) <= 500):
                return err(400, "조치 내용을 입력하세요")
            note = note.strip()
        else:
            if b.get("result") not in ("pass", "fail"):
                return err(400, "입력을 확인하세요")
        # 2) 없는 건 · 사용자 (404)
        row = db.execute("SELECT * FROM qc_defects WHERE defect_id=?", (defect_id,)).fetchone()
        if not row:
            return err(404, "불량 건을 찾을 수 없습니다")
        user = get_user(uid)
        if not user:
            return err(404, "사용자를 찾을 수 없습니다")
        # 3) 권한 (403)
        if action == "analyze":
            if user["role"] != "quality":
                return err(403, "품질팀만 할 수 있습니다")
        elif action == "fix":
            if row["assignee"] != uid:
                return err(403, "담당자만 조치를 등록할 수 있습니다")
        else:
            if user["role"] != "quality":
                return err(403, "품질팀만 할 수 있습니다")
            if row["assignee"] == uid:
                return err(403, "본인 조치는 검증할 수 없습니다")
            if row["reporter"] == uid:
                return err(403, "신고자는 검증할 수 없습니다")
        # 4) 상태 (409)
        if row["status"] == "closed":
            return err(409, "종결된 건입니다")
        need = {"analyze": "reported", "fix": "fixing", "verify": "verifying"}[action]
        if row["status"] != need:
            return err(409, "지금 상태에서는 할 수 없습니다")

        if action == "analyze":
            db.execute("UPDATE qc_defects SET status='fixing', cause=?, assignee=? WHERE defect_id=?",
                       (b["cause"], b["assignee"], defect_id))
            note = f"{b['cause']}/{b['assignee']}"
        elif action == "fix":
            db.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (defect_id,))
        elif b["result"] == "pass":
            db.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (defect_id,))
            note = "pass"
        else:
            db.execute("UPDATE qc_defects SET status='fixing', rework=rework+1 WHERE defect_id=?", (defect_id,))
            note = "fail"
        history(defect_id, uid, action, note)
        db.commit()
        row = db.execute("SELECT * FROM qc_defects WHERE defect_id=?", (defect_id,)).fetchone()
        return shape(row)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
