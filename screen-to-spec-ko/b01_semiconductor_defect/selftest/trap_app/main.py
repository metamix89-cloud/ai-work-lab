# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수만 모았다. T1 · T2 · T7 만 통과해야 채점기가 맞다(목록 · 기한 계산은 맞고, 권한 · 순서 · 중복이 틀림).
실수: 같은 로트 · 증상 중복을 안 막음 · 작업자도 원인 분석 · 담당자가 아니어도 조치 등록 · 본인 · 신고자도 검증 · 검증 실패를 '신고' 로 되돌림 ·
      건을 본문보다 먼저 찾음(거부 순서) · 화면 없음."""
import csv
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "qc.db")
app = FastAPI()
DAYS = {"치명": 1, "중": 3, "경": 7}


def load():
    if os.path.exists(DB):
        os.remove(DB)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE qc_users(user_id TEXT, name TEXT, role TEXT);
    CREATE TABLE qc_lots(lot_id TEXT, product TEXT, line TEXT, qty INTEGER);
    CREATE TABLE qc_symptoms(code TEXT, label TEXT);
    CREATE TABLE qc_causes(code TEXT, label TEXT);
    CREATE TABLE qc_defects(defect_id TEXT, lot_id TEXT, symptom TEXT, severity TEXT, qty INTEGER, status TEXT,
                            reporter TEXT, assignee TEXT, cause TEXT, reported_at TEXT, rework INTEGER);""")
    for name, table, n in (("users.csv", "qc_users", 3), ("lots.csv", "qc_lots", 4), ("symptoms.csv", "qc_symptoms", 2),
                           ("causes.csv", "qc_causes", 2), ("defects.csv", "qc_defects", 11)):
        with open(os.path.join(SEED, name), encoding="utf-8") as f:
            c.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    c.commit()
    c.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def view(c, d):
    lot = c.execute("SELECT * FROM qc_lots WHERE lot_id=?", (d["lot_id"],)).fetchone()
    due = (date.fromisoformat(d["reported_at"][:10]) + timedelta(days=DAYS[d["severity"]])).isoformat()
    return {"defect_id": d["defect_id"], "lot_id": d["lot_id"], "product": lot["product"], "line": lot["line"], "symptom": d["symptom"],
            "severity": d["severity"], "qty": int(d["qty"]), "status": d["status"], "reporter": d["reporter"], "assignee": d["assignee"] or None,
            "cause": d["cause"] or None, "reported_at": d["reported_at"], "due": due,
            "overdue": d["status"] != "closed" and date.today().isoformat() > due, "rework": int(d["rework"])}


def defect_or_404(c, did):
    d = c.execute("SELECT * FROM qc_defects WHERE defect_id=?", (did,)).fetchone()
    if not d:
        raise HTTPException(404, "불량 건이 없습니다")                    # 실수: 본문(400)보다 먼저
    return d


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>불량 추적판</h1></body></html>"


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM qc_users")]


@app.get("/api/lots")
def lots():
    return [{"lot_id": l["lot_id"], "product": l["product"], "line": l["line"], "qty": int(l["qty"])} for l in con().execute("SELECT * FROM qc_lots")]


@app.get("/api/defects")
def defects():
    c = con()
    rows = [view(c, d) for d in c.execute("SELECT * FROM qc_defects ORDER BY reported_at, defect_id")]
    return {"defects": rows, "summary": {"open": sum(1 for r in rows if r["status"] != "closed"),
                                        "overdue": sum(1 for r in rows if r["overdue"]), "rework": sum(r["rework"] for r in rows)}}


@app.post("/api/defects", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    c = con()
    lot = c.execute("SELECT * FROM qc_lots WHERE lot_id=?", (body.get("lot_id"),)).fetchone()
    if not lot:
        raise HTTPException(404, "로트를 확인하세요")
    qty = body.get("qty")
    if not isinstance(qty, int) or qty < 1 or qty > int(lot["qty"]):
        raise HTTPException(400, "수량을 확인하세요")
    if body.get("severity") not in DAYS or not c.execute("SELECT 1 FROM qc_symptoms WHERE code=?", (body.get("symptom"),)).fetchone():
        raise HTTPException(400, "입력을 확인하세요")
    did = "F%03d" % (c.execute("SELECT COUNT(*) FROM qc_defects").fetchone()[0] + 1)   # 실수: 중복 검사 없음 · id 가 겹칠 수 있음
    c.execute("INSERT INTO qc_defects VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (did, body["lot_id"], body["symptom"], body["severity"], qty, "reported", body.get("user"), "", "", datetime.now().strftime("%Y-%m-%d %H:%M"), 0))
    c.commit()
    return view(c, defect_or_404(c, did))


@app.post("/api/defects/{did}/{action}")
def do(did: str, action: str, body: dict[str, Any] = Body(default={})):
    c = con()
    d = defect_or_404(c, did)
    u = c.execute("SELECT * FROM qc_users WHERE user_id=?", (body.get("user"),)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    if d["status"] == "closed":
        raise HTTPException(409, "종결된 건입니다")                      # 실수: 권한(403)보다 먼저
    if action == "analyze":                                              # 실수: 작업자도 분석 · 담당자 역할 검사 없음
        if d["status"] != "reported":
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        c.execute("UPDATE qc_defects SET status='fixing', cause=?, assignee=? WHERE defect_id=?", (body.get("cause"), body.get("assignee"), did))
    elif action == "fix":                                                # 실수: 담당자가 아니어도 됨
        if d["status"] != "fixing":
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        if not (body.get("note") or "").strip():
            raise HTTPException(400, "조치 내용을 입력하세요")
        c.execute("UPDATE qc_defects SET status='verifying' WHERE defect_id=?", (did,))
    elif action == "verify":                                             # 실수: 본인 · 신고자 · 작업자도 검증, 실패는 '신고' 로
        if d["status"] != "verifying":
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        if body.get("result") == "pass":
            c.execute("UPDATE qc_defects SET status='closed' WHERE defect_id=?", (did,))
        else:
            c.execute("UPDATE qc_defects SET status='reported', rework=rework+1 WHERE defect_id=?", (did,))
    else:
        raise HTTPException(404, "없는 동작입니다")
    c.commit()
    return view(c, defect_or_404(c, did))
