# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R9 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
거부 순서(R9): 본문만 보면 아는 400 → 없는 것 404 → 찾아야 아는 권한 403 → (찾아야 아는 400) → 상태 · 중복 409."""
import csv
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "qc.db")
LOCK = threading.Lock()
app = FastAPI()
DAYS = {"치명": 1, "중": 3, "경": 7}


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE qc_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE qc_lots(lot_id TEXT PRIMARY KEY, product TEXT, line TEXT, qty INTEGER);
    CREATE TABLE qc_symptoms(code TEXT PRIMARY KEY, label TEXT);
    CREATE TABLE qc_causes(code TEXT PRIMARY KEY, label TEXT);
    CREATE TABLE qc_defects(defect_id TEXT PRIMARY KEY, lot_id TEXT, symptom TEXT, severity TEXT, qty INTEGER, status TEXT,
                            reporter TEXT, assignee TEXT, cause TEXT, reported_at TEXT, rework INTEGER);
    CREATE TABLE qc_history(defect_id TEXT, at TEXT, by TEXT, action TEXT, note TEXT);""")
    for name, table, n in (("users.csv", "qc_users", 3), ("lots.csv", "qc_lots", 4), ("symptoms.csv", "qc_symptoms", 2),
                           ("causes.csv", "qc_causes", 2), ("defects.csv", "qc_defects", 11)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def view(c, d):
    lot = c.execute("SELECT * FROM qc_lots WHERE lot_id=?", (d["lot_id"],)).fetchone()
    due = (date.fromisoformat(d["reported_at"][:10]) + timedelta(days=DAYS.get(d["severity"], 7))).isoformat()
    return {"defect_id": d["defect_id"], "lot_id": d["lot_id"], "product": lot["product"] if lot else None, "line": lot["line"] if lot else None,
            "symptom": d["symptom"], "severity": d["severity"], "qty": int(d["qty"]), "status": d["status"], "reporter": d["reporter"],
            "assignee": d["assignee"] or None, "cause": d["cause"] or None, "reported_at": d["reported_at"], "due": due,
            "overdue": d["status"] != "closed" and date.today().isoformat() > due, "rework": int(d["rework"] or 0)}


def need_user(uid):
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, "사용자를 확인하세요")


def find_user(c, uid):
    u = c.execute("SELECT * FROM qc_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    return u


def find_defect(c, did):
    d = c.execute("SELECT * FROM qc_defects WHERE defect_id=?", (did,)).fetchone()
    if not d:
        raise HTTPException(404, "불량 건이 없습니다")
    return d


def is_int(v, lo):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo


def log(c, did, by, action, note=""):
    c.execute("INSERT INTO qc_history VALUES (?,?,?,?,?)", (did, datetime.now().strftime("%Y-%m-%d %H:%M"), by, action, note))


def next_id(c):
    nums = [int(r[0][1:]) for r in c.execute("SELECT defect_id FROM qc_defects") if r[0][1:].isdigit()]
    return "F%03d" % (max(nums + [0]) + 1)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM qc_users ORDER BY rowid")]


@app.get("/api/lots")
def lots():
    c = con()
    return [{"lot_id": l["lot_id"], "product": l["product"], "line": l["line"], "qty": int(l["qty"])} for l in c.execute("SELECT * FROM qc_lots ORDER BY rowid")]


@app.get("/api/symptoms")
def symptoms():
    return [{"code": r["code"], "label": r["label"]} for r in con().execute("SELECT * FROM qc_symptoms ORDER BY rowid")]


@app.get("/api/causes")
def causes():
    return [{"code": r["code"], "label": r["label"]} for r in con().execute("SELECT * FROM qc_causes ORDER BY rowid")]


@app.get("/api/defects")
def defects():
    c = con()
    rows = [view(c, d) for d in c.execute("SELECT * FROM qc_defects ORDER BY reported_at, defect_id").fetchall()]
    return {"defects": rows, "summary": {"open": sum(1 for r in rows if r["status"] != "closed"),
                                        "overdue": sum(1 for r in rows if r["overdue"]), "rework": sum(r["rework"] for r in rows)}}


@app.post("/api/defects", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    qty, sev, sym, lot_id = body.get("qty"), body.get("severity"), body.get("symptom"), body.get("lot_id")
    if not is_int(qty, 1):
        raise HTTPException(400, "수량을 확인하세요")
    with LOCK:
        c = con()
        if sev not in DAYS or not c.execute("SELECT 1 FROM qc_symptoms WHERE code=?", (sym,)).fetchone():
            raise HTTPException(400, "입력을 확인하세요")
        u = find_user(c, body["user"])
        lot = c.execute("SELECT * FROM qc_lots WHERE lot_id=?", (lot_id,)).fetchone()
        if not lot:
            raise HTTPException(404, "로트를 확인하세요")
        if qty > int(lot["qty"]):
            raise HTTPException(400, "수량을 확인하세요")
        if c.execute("SELECT 1 FROM qc_defects WHERE lot_id=? AND symptom=? AND status!='closed'", (lot_id, sym)).fetchone():
            raise HTTPException(409, "이미 신고된 불량입니다")
        did = next_id(c)
        c.execute("INSERT INTO qc_defects VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (did, lot_id, sym, sev, qty, "reported", u["user_id"], "", "", datetime.now().strftime("%Y-%m-%d %H:%M"), 0))
        log(c, did, u["user_id"], "report")
        c.commit()
        return view(c, find_defect(c, did))


@app.post("/api/defects/{did}/{action}")
def do(did: str, action: str, body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    if action == "fix" and not (isinstance(body.get("note"), str) and 1 <= len(body["note"].strip()) <= 500):
        raise HTTPException(400, "조치 내용을 입력하세요")
    if action == "verify" and body.get("result") not in ("pass", "fail"):
        raise HTTPException(400, "입력을 확인하세요")
    if action == "analyze" and not (isinstance(body.get("cause"), str) and isinstance(body.get("assignee"), str)):
        raise HTTPException(400, "원인과 담당자를 확인하세요")
    with LOCK:
        c = con()
        d = find_defect(c, did)
        u = find_user(c, body["user"])
        if action not in ("analyze", "fix", "verify"):
            raise HTTPException(404, "없는 동작입니다")
        if action == "analyze":
            if u["role"] != "quality":
                raise HTTPException(403, "품질팀만 할 수 있습니다")
            a = c.execute("SELECT * FROM qc_users WHERE user_id=?", (body["assignee"],)).fetchone()
            if not c.execute("SELECT 1 FROM qc_causes WHERE code=?", (body["cause"],)).fetchone() or not a or a["role"] != "quality":
                raise HTTPException(400, "원인과 담당자를 확인하세요")
        elif action == "fix":
            if u["user_id"] != (d["assignee"] or ""):
                raise HTTPException(403, "담당자만 조치를 등록할 수 있습니다")
        else:
            if u["role"] != "quality":
                raise HTTPException(403, "품질팀만 할 수 있습니다")
            if u["user_id"] == (d["assignee"] or ""):
                raise HTTPException(403, "본인 조치는 검증할 수 없습니다")
            if u["user_id"] == d["reporter"]:
                raise HTTPException(403, "신고자는 검증할 수 없습니다")
        if d["status"] == "closed":
            raise HTTPException(409, "종결된 건입니다")
        need = {"analyze": "reported", "fix": "fixing", "verify": "verifying"}[action]
        if d["status"] != need:
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        if action == "analyze":
            c.execute("UPDATE qc_defects SET status='fixing', cause=?, assignee=? WHERE defect_id=?", (body["cause"], body["assignee"], did))
        elif action == "fix":
            c.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (did,))
        elif body["result"] == "pass":
            c.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (did,))
        else:
            c.execute("UPDATE qc_defects SET status='fixing', rework=rework+1 WHERE defect_id=?", (did,))
        log(c, did, u["user_id"], action, body.get("note") or body.get("result") or body.get("cause") or "")
        c.commit()
        return view(c, find_defect(c, did))
