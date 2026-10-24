import csv
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "qc.db"
INDEX = BASE / "static" / "index.html"

SEVERITY_DAYS = {"치명": 1, "중": 3, "경": 7}
STATUSES = ("reported", "fixing", "verifying", "closed")

SCHEMA = """
DROP TABLE IF EXISTS qc_history;
DROP TABLE IF EXISTS qc_defects;
DROP TABLE IF EXISTS qc_causes;
DROP TABLE IF EXISTS qc_symptoms;
DROP TABLE IF EXISTS qc_lots;
DROP TABLE IF EXISTS qc_users;
CREATE TABLE qc_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
CREATE TABLE qc_lots (lot_id TEXT PRIMARY KEY, product TEXT, line TEXT, qty INTEGER);
CREATE TABLE qc_symptoms (code TEXT PRIMARY KEY, label TEXT);
CREATE TABLE qc_causes (code TEXT PRIMARY KEY, label TEXT);
CREATE TABLE qc_defects (
  defect_id TEXT PRIMARY KEY, lot_id TEXT, symptom TEXT, severity TEXT, qty INTEGER,
  status TEXT, reporter TEXT, assignee TEXT, cause TEXT, reported_at TEXT, rework INTEGER,
  seq INTEGER
);
CREATE TABLE qc_history (defect_id TEXT, at TEXT, by TEXT, action TEXT, note TEXT);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    for r in read_csv("users.csv"):
        conn.execute("INSERT INTO qc_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("lots.csv"):
        conn.execute("INSERT INTO qc_lots VALUES (?,?,?,?)", (r["lot_id"], r["product"], r["line"], int(r["qty"])))
    for r in read_csv("symptoms.csv"):
        conn.execute("INSERT INTO qc_symptoms VALUES (?,?)", (r["code"], r["label"]))
    for r in read_csv("causes.csv"):
        conn.execute("INSERT INTO qc_causes VALUES (?,?)", (r["code"], r["label"]))
    for i, r in enumerate(read_csv("defects.csv")):
        conn.execute(
            "INSERT INTO qc_defects VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["defect_id"], r["lot_id"], r["symptom"], r["severity"], int(r["qty"]), r["status"],
             r["reporter"], r["assignee"] or None, r["cause"] or None, r["reported_at"],
             int(r["rework"] or 0), i),
        )
    conn.commit()
    conn.close()


init_db()
app = FastAPI()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


async def read_body(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def defect_json(row, conn=None):
    reported = datetime.strptime(row["reported_at"], "%Y-%m-%d %H:%M")
    due = reported.date() + timedelta(days=SEVERITY_DAYS[row["severity"]])
    lot = LOTS_LOOKUP(conn, row["lot_id"])
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


def LOTS_LOOKUP(conn, lot_id):
    return conn.execute("SELECT * FROM qc_lots WHERE lot_id=?", (lot_id,)).fetchone()


def get_defect_json(conn, defect_id):
    row = conn.execute("SELECT * FROM qc_defects WHERE defect_id=?", (defect_id,)).fetchone()
    return defect_json(row, conn)


def log(conn, defect_id, by, action, note=""):
    conn.execute("INSERT INTO qc_history VALUES (?,?,?,?,?)",
                 (defect_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), by, action, note))


@app.get("/")
def index():
    return FileResponse(INDEX, media_type="text/html")


def table_list(table, cols):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(f"SELECT {cols} FROM {table} ORDER BY rowid")]
    finally:
        conn.close()


@app.get("/api/users")
def users():
    return table_list("qc_users", "user_id, name, role")


@app.get("/api/lots")
def lots():
    return table_list("qc_lots", "lot_id, product, line, qty")


@app.get("/api/symptoms")
def symptoms():
    return table_list("qc_symptoms", "code, label")


@app.get("/api/causes")
def causes():
    return table_list("qc_causes", "code, label")


@app.get("/api/defects")
def defects():
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM qc_defects ORDER BY reported_at, seq").fetchall()
        items = [defect_json(r, conn) for r in rows]
    finally:
        conn.close()
    summary = {
        "open": sum(1 for d in items if d["status"] != "closed"),
        "overdue": sum(1 for d in items if d["overdue"]),
        "rework": sum(d["rework"] for d in items),
    }
    return {"defects": items, "summary": summary}


@app.post("/api/defects")
async def report(request: Request):
    body = await read_body(request)
    user = body.get("user")
    if not isinstance(user, str):
        return err(400, "사용자를 확인하세요")
    lot_id, symptom, severity, qty = body.get("lot_id"), body.get("symptom"), body.get("severity"), body.get("qty")
    if not isinstance(lot_id, str) or not isinstance(symptom, str) or severity not in SEVERITY_DAYS:
        return err(400, "입력을 확인하세요")
    if not is_int(qty) or qty < 1:
        return err(400, "수량을 확인하세요")
    conn = connect()
    try:
        if not conn.execute("SELECT 1 FROM qc_symptoms WHERE code=?", (symptom,)).fetchone():
            return err(400, "입력을 확인하세요")
        if not conn.execute("SELECT 1 FROM qc_users WHERE user_id=?", (user,)).fetchone():
            return err(404, "사용자를 확인하세요")
        lot = LOTS_LOOKUP(conn, lot_id)
        if not lot:
            return err(404, "로트를 확인하세요")
        if qty > lot["qty"]:
            return err(400, "수량을 확인하세요")
        if conn.execute(
            "SELECT 1 FROM qc_defects WHERE lot_id=? AND symptom=? AND status!='closed'", (lot_id, symptom)
        ).fetchone():
            return err(409, "이미 신고된 불량입니다")
        ids = {r[0] for r in conn.execute("SELECT defect_id FROM qc_defects")}
        n = 1
        for i in ids:
            digits = "".join(c for c in i if c.isdigit())
            if digits:
                n = max(n, int(digits) + 1)
        new_id = f"F{n:03d}"
        while new_id in ids:
            n += 1
            new_id = f"F{n:03d}"
        seq = conn.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM qc_defects").fetchone()[0]
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute(
            "INSERT INTO qc_defects VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id, lot_id, symptom, severity, qty, "reported", user, None, None, now, 0, seq),
        )
        log(conn, new_id, user, "report")
        conn.commit()
        return JSONResponse(get_defect_json(conn, new_id), status_code=201)
    finally:
        conn.close()


@app.post("/api/defects/{defect_id}/{action}")
async def act(defect_id: str, action: str, request: Request):
    body = await read_body(request)
    user = body.get("user")
    if not isinstance(user, str):
        return err(400, "사용자를 확인하세요")

    # 400: 본문만 보면 아는 것
    if action == "analyze":
        cause, assignee = body.get("cause"), body.get("assignee")
        if not isinstance(cause, str) or not isinstance(assignee, str):
            return err(400, "원인과 담당자를 확인하세요")
    elif action == "fix":
        note = body.get("note")
        note = note.strip() if isinstance(note, str) else ""
        if not 1 <= len(note) <= 500:
            return err(400, "조치 내용을 입력하세요")
    elif action == "verify":
        if body.get("result") not in ("pass", "fail"):
            return err(400, "입력을 확인하세요")

    conn = connect()
    try:
        # 404: 없는 건 · 사용자
        if action not in ("analyze", "fix", "verify"):
            return err(404, "찾을 수 없습니다")
        row = conn.execute("SELECT * FROM qc_defects WHERE defect_id=?", (defect_id,)).fetchone()
        if not row:
            return err(404, "불량 건을 찾을 수 없습니다")
        u = conn.execute("SELECT * FROM qc_users WHERE user_id=?", (user,)).fetchone()
        if not u:
            return err(404, "사용자를 확인하세요")

        # 403: 권한
        if action == "analyze":
            if u["role"] != "quality":
                return err(403, "품질팀만 할 수 있습니다")
        elif action == "fix":
            if row["assignee"] != user:
                return err(403, "담당자만 조치를 등록할 수 있습니다")
        else:
            if u["role"] != "quality":
                return err(403, "품질팀만 할 수 있습니다")
            if row["assignee"] == user:
                return err(403, "본인 조치는 검증할 수 없습니다")
            if row["reporter"] == user:
                return err(403, "신고자는 검증할 수 없습니다")

        # 400: 목록을 봐야 아는 입력
        if action == "analyze":
            ok_cause = conn.execute("SELECT 1 FROM qc_causes WHERE code=?", (body["cause"],)).fetchone()
            a = conn.execute("SELECT role FROM qc_users WHERE user_id=?", (body["assignee"],)).fetchone()
            if not ok_cause or not a or a["role"] != "quality":
                return err(400, "원인과 담당자를 확인하세요")

        # 409: 상태
        if row["status"] == "closed":
            return err(409, "종결된 건입니다")
        required = {"analyze": "reported", "fix": "fixing", "verify": "verifying"}[action]
        if row["status"] != required:
            return err(409, "지금 상태에서는 할 수 없습니다")

        if action == "analyze":
            conn.execute("UPDATE qc_defects SET cause=?, assignee=?, status='fixing' WHERE defect_id=?",
                         (body["cause"], body["assignee"], defect_id))
            log(conn, defect_id, user, "analyze", f"{body['cause']}/{body['assignee']}")
        elif action == "fix":
            conn.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (defect_id,))
            log(conn, defect_id, user, "fix", body["note"].strip())
        else:
            if body["result"] == "pass":
                conn.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (defect_id,))
            else:
                conn.execute("UPDATE qc_defects SET status='fixing', rework=rework+1 WHERE defect_id=?",
                             (defect_id,))
            log(conn, defect_id, user, "verify", body["result"])
        conn.commit()
        return get_defect_json(conn, defect_id)
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
