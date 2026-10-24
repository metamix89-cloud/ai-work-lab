"""콩알반도체 불량 신고 · 조치 추적판 (FastAPI + SQLite)

흐름: 신고(reported) → 분석중(analyzing) → 조치중(in_action) → 검증중(verifying) → 종결(closed)
검증에서 반려되면 조치중으로 되돌아간다. 기한은 심각도별 SLA로 신고 시각에 확정된다.
"""
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TRACKER_DB", os.path.join(BASE, "tracker.db"))

SEVERITY_HOURS = {"critical": 24, "high": 72, "medium": 168, "low": 336}
SEVERITY_LABEL = {"critical": "치명", "high": "높음", "medium": "보통", "low": "낮음"}
STATUS_LABEL = {
    "reported": "신고",
    "analyzing": "원인 분석",
    "in_action": "조치중",
    "verifying": "검증중",
    "closed": "종결",
}
CAUSE_CATEGORIES = ["설비", "자재", "공정 조건", "작업 방법", "환경", "설계", "측정/검사"]
DEFECT_TYPES = ["파티클 오염", "패턴 브리지", "두께 편차", "스크래치", "본딩 리프트", "보이드", "전기특성 불량", "라벨/마킹 오류"]
PROCESSES = ["세정", "포토", "식각", "증착", "CMP", "이온주입", "와이어본딩", "몰딩", "최종테스트"]
SOON_HOURS = 24

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, dept TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS defects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL,
  lot_no TEXT NOT NULL, product TEXT NOT NULL, line TEXT NOT NULL, process TEXT NOT NULL,
  defect_type TEXT NOT NULL, qty INTEGER NOT NULL, severity TEXT NOT NULL, description TEXT NOT NULL,
  reporter_id INTEGER NOT NULL, reported_at TEXT NOT NULL, due_at TEXT NOT NULL,
  status TEXT NOT NULL, analyst_id INTEGER, assignee_id INTEGER,
  cause_category TEXT, root_cause TEXT, action_plan TEXT, action_result TEXT,
  verification_note TEXT, closed_at TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, defect_id INTEGER NOT NULL, at TEXT NOT NULL,
  actor_id INTEGER NOT NULL, kind TEXT NOT NULL, from_status TEXT, to_status TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS ix_def_status ON defects(status);
CREATE INDEX IF NOT EXISTS ix_ev_def ON events(defect_id);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def db():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def next_code(con, year: int) -> str:
    row = con.execute("SELECT COUNT(*) c FROM defects WHERE code LIKE ?", (f"DR-{year}-%",)).fetchone()
    n = row["c"] + 1
    while con.execute("SELECT 1 FROM defects WHERE code=?", (f"DR-{year}-{n:04d}",)).fetchone():
        n += 1
    return f"DR-{year}-{n:04d}"


def add_event(con, defect_id, actor_id, kind, frm=None, to=None, note=None, at=None):
    con.execute(
        "INSERT INTO events(defect_id,at,actor_id,kind,from_status,to_status,note) VALUES(?,?,?,?,?,?,?)",
        (defect_id, at or iso(now()), actor_id, kind, frm, to, note),
    )


# ---------------------------------------------------------------- serialization
def due_state(row, ref: datetime) -> str:
    if row["status"] == "closed":
        return "closed"
    left = parse(row["due_at"]) - ref
    if left.total_seconds() < 0:
        return "overdue"
    if left <= timedelta(hours=SOON_HOURS):
        return "soon"
    return "ok"


def defect_dict(row, users, ref: datetime):
    d = dict(row)
    d["due_state"] = due_state(row, ref)
    d["is_overdue"] = d["due_state"] == "overdue"
    d["late_closed"] = bool(row["closed_at"] and row["closed_at"] > row["due_at"])
    for k in ("reporter", "analyst", "assignee"):
        u = users.get(d[k + "_id"])
        d[k] = {"id": u["id"], "name": u["name"], "dept": u["dept"]} if u else None
    return d


def load_users(con):
    return {r["id"]: dict(r) for r in con.execute("SELECT * FROM users")}


# ---------------------------------------------------------------- auth (선택형 사용자, 로그인 없음)
def current_user(x_user_id: Optional[int] = Header(default=None), con=Depends(db)):
    if x_user_id is None:
        raise HTTPException(401, "사용자를 선택하세요")
    u = con.execute("SELECT * FROM users WHERE id=?", (x_user_id,)).fetchone()
    if not u:
        raise HTTPException(401, "알 수 없는 사용자")
    return dict(u)


# ---------------------------------------------------------------- models
class NewDefect(BaseModel):
    lot_no: str = Field(min_length=1, max_length=40)
    product: str = Field(min_length=1, max_length=60)
    line: str = Field(min_length=1, max_length=20)
    process: str
    defect_type: str
    qty: int = Field(ge=1, le=1_000_000)
    severity: str
    description: str = Field(min_length=2, max_length=1000)


class Transition(BaseModel):
    action: str  # analyze | assign | complete | verify | comment
    cause_category: Optional[str] = None
    root_cause: Optional[str] = None
    assignee_id: Optional[int] = None
    action_plan: Optional[str] = None
    action_result: Optional[str] = None
    result: Optional[str] = None  # verify: ok | reject
    note: Optional[str] = None


def need(val, label):
    if val is None or not str(val).strip():
        raise HTTPException(422, f"{label} 입력이 필요합니다")
    return str(val).strip()


app = FastAPI(title="콩알반도체 불량 신고·조치 추적판")


@app.on_event("startup")
def startup():
    with closing(connect()) as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            import seed
            seed.populate(con)
        con.commit()


@app.get("/api/meta")
def meta():
    return {
        "severity": [{"key": k, "label": SEVERITY_LABEL[k], "hours": h} for k, h in SEVERITY_HOURS.items()],
        "status": [{"key": k, "label": v} for k, v in STATUS_LABEL.items()],
        "cause_categories": CAUSE_CATEGORIES,
        "defect_types": DEFECT_TYPES,
        "processes": PROCESSES,
        "soon_hours": SOON_HOURS,
    }


@app.get("/api/users")
def users(con=Depends(db)):
    return [dict(r) for r in con.execute("SELECT * FROM users ORDER BY id")]


@app.get("/api/defects")
def list_defects(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    assignee_id: Optional[int] = None,
    overdue: bool = False,
    open_only: bool = False,
    q: Optional[str] = None,
    con=Depends(db),
):
    sql, args = "SELECT * FROM defects WHERE 1=1", []
    if status:
        sql += " AND status=?"; args.append(status)
    if severity:
        sql += " AND severity=?"; args.append(severity)
    if assignee_id:
        sql += " AND assignee_id=?"; args.append(assignee_id)
    if open_only:
        sql += " AND status!='closed'"
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (code LIKE ? OR lot_no LIKE ? OR product LIKE ? OR defect_type LIKE ? OR description LIKE ?)"
        args += [like] * 5
    ref = now()
    if overdue:
        sql += " AND status!='closed' AND due_at<?"; args.append(iso(ref))
    rows = con.execute(sql, args).fetchall()
    us = load_users(con)
    items = [defect_dict(r, us, ref) for r in rows]
    # 기한 초과 → 임박 → 일반 순으로, 같은 그룹 안에서는 기한이 빠른 순. 종결건은 맨 아래.
    rank = {"overdue": 0, "soon": 1, "ok": 2, "closed": 3}
    items.sort(key=lambda d: (rank[d["due_state"]], d["due_at"] if d["status"] != "closed" else "", ))
    closed = [d for d in items if d["status"] == "closed"]
    closed.sort(key=lambda d: d["closed_at"], reverse=True)
    return [d for d in items if d["status"] != "closed"] + closed


@app.get("/api/summary")
def summary(con=Depends(db)):
    ref = now()
    us = load_users(con)
    items = [defect_dict(r, us, ref) for r in con.execute("SELECT * FROM defects")]
    open_ = [d for d in items if d["status"] != "closed"]
    week_ago = iso(ref - timedelta(days=7))
    by_status = {k: 0 for k in STATUS_LABEL}
    by_status_overdue = {k: 0 for k in STATUS_LABEL}
    by_sev = {k: {"open": 0, "overdue": 0} for k in SEVERITY_LABEL}
    for d in items:
        by_status[d["status"]] += 1
        if d["is_overdue"]:
            by_status_overdue[d["status"]] += 1
    for d in open_:
        by_sev[d["severity"]]["open"] += 1
        by_sev[d["severity"]]["overdue"] += d["is_overdue"]
    # 담당자별 현황 (조치중 + 검증 대기 중인 건 기준)
    wl = {}
    for d in open_:
        a = d["assignee"]
        if not a:
            continue
        w = wl.setdefault(a["id"], {"id": a["id"], "name": a["name"], "dept": a["dept"],
                                    "in_action": 0, "verifying": 0, "overdue": 0, "next_due": None})
        if d["status"] in ("in_action", "verifying"):
            w[d["status"]] += 1
            w["overdue"] += d["is_overdue"]
            if w["next_due"] is None or d["due_at"] < w["next_due"]:
                w["next_due"] = d["due_at"]
    workload = sorted(wl.values(), key=lambda w: (-w["overdue"], -(w["in_action"] + w["verifying"])))
    workload = [w for w in workload if w["in_action"] + w["verifying"] > 0]
    return {
        "now": iso(ref),
        "open": len(open_),
        "overdue": sum(d["is_overdue"] for d in open_),
        "soon": sum(d["due_state"] == "soon" for d in open_),
        "closed_7d": sum(1 for d in items if d["closed_at"] and d["closed_at"] >= week_ago),
        "unassigned": sum(1 for d in open_ if d["status"] in ("reported", "analyzing")),
        "by_status": by_status,
        "by_status_overdue": by_status_overdue,
        "by_severity": by_sev,
        "workload": workload,
    }


@app.get("/api/defects/{did}")
def get_defect(did: int, con=Depends(db)):
    row = con.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone()
    if not row:
        raise HTTPException(404, "없는 신고입니다")
    us = load_users(con)
    d = defect_dict(row, us, now())
    d["events"] = [
        {**dict(e), "actor": us[e["actor_id"]]["name"] if e["actor_id"] in us else "?"}
        for e in con.execute("SELECT * FROM events WHERE defect_id=? ORDER BY at, id", (did,))
    ]
    return d


@app.post("/api/defects", status_code=201)
def create_defect(body: NewDefect, user=Depends(current_user), con=Depends(db)):
    if body.severity not in SEVERITY_HOURS:
        raise HTTPException(422, "심각도가 올바르지 않습니다")
    if body.process not in PROCESSES or body.defect_type not in DEFECT_TYPES:
        raise HTTPException(422, "공정 또는 불량 유형이 올바르지 않습니다")
    t = now()
    due = t + timedelta(hours=SEVERITY_HOURS[body.severity])
    code = next_code(con, t.year)
    cur = con.execute(
        """INSERT INTO defects(code,lot_no,product,line,process,defect_type,qty,severity,description,
           reporter_id,reported_at,due_at,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (code, body.lot_no.strip(), body.product.strip(), body.line.strip(), body.process, body.defect_type,
         body.qty, body.severity, body.description.strip(), user["id"], iso(t), iso(due), "reported", iso(t)),
    )
    add_event(con, cur.lastrowid, user["id"], "report", None, "reported", body.description.strip(), iso(t))
    return {"id": cur.lastrowid, "code": code}


@app.post("/api/defects/{did}/transition")
def transition(did: int, body: Transition, user=Depends(current_user), con=Depends(db)):
    row = con.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone()
    if not row:
        raise HTTPException(404, "없는 신고입니다")
    st, role, uid, t = row["status"], user["role"], user["id"], iso(now())
    quality = role == "quality"

    def forbid(msg):
        raise HTTPException(403, msg)

    def wrong(msg):
        raise HTTPException(409, msg)

    if st == "closed":
        wrong("이미 종결된 건입니다")

    if body.action == "comment":
        add_event(con, did, uid, "comment", note=need(body.note, "메모"))
        return {"ok": True}

    if body.action == "analyze":
        if not quality: forbid("품질팀만 분석을 시작할 수 있습니다")
        if st != "reported": wrong("신고 상태에서만 분석을 시작할 수 있습니다")
        con.execute("UPDATE defects SET status='analyzing', analyst_id=?, updated_at=? WHERE id=?", (uid, t, did))
        add_event(con, did, uid, "analyze", st, "analyzing", body.note, t)

    elif body.action == "assign":
        if not quality: forbid("품질팀만 원인 확정·담당자 지정을 할 수 있습니다")
        if st not in ("analyzing", "in_action"): wrong("원인 분석 또는 조치 중일 때만 지정할 수 있습니다")
        cat = need(body.cause_category, "원인 분류")
        if cat not in CAUSE_CATEGORIES: raise HTTPException(422, "원인 분류가 올바르지 않습니다")
        cause = need(body.root_cause, "근본 원인")
        plan = need(body.action_plan, "조치 계획")
        a = con.execute("SELECT * FROM users WHERE id=?", (body.assignee_id,)).fetchone()
        if not a or a["role"] == "worker":
            raise HTTPException(422, "조치 담당자는 품질/공정·설비 담당자 중에서 지정하세요")
        kind = "assign" if st == "analyzing" else "reassign"
        con.execute(
            """UPDATE defects SET status='in_action', analyst_id=COALESCE(analyst_id,?), assignee_id=?,
               cause_category=?, root_cause=?, action_plan=?, updated_at=? WHERE id=?""",
            (uid, a["id"], cat, cause, plan, t, did))
        add_event(con, did, uid, kind, st, "in_action", f"담당: {a['name']} · 원인: {cat}", t)

    elif body.action == "complete":
        if st != "in_action": wrong("조치중인 건만 조치 완료로 올릴 수 있습니다")
        if not (quality or row["assignee_id"] == uid): forbid("지정된 담당자만 조치 완료를 등록할 수 있습니다")
        res = need(body.action_result, "조치 결과")
        con.execute("UPDATE defects SET status='verifying', action_result=?, updated_at=? WHERE id=?", (res, t, did))
        add_event(con, did, uid, "complete", st, "verifying", res, t)

    elif body.action == "verify":
        if not quality: forbid("품질팀만 검증할 수 있습니다")
        if st != "verifying": wrong("검증중인 건만 검증할 수 있습니다")
        if row["assignee_id"] == uid: forbid("조치 담당자 본인은 검증할 수 없습니다 (다른 품질팀원이 검증)")
        if body.result == "ok":
            con.execute("UPDATE defects SET status='closed', verification_note=?, closed_at=?, updated_at=? WHERE id=?",
                        (body.note, t, t, did))
            add_event(con, did, uid, "close", st, "closed", body.note or "검증 통과", t)
        elif body.result == "reject":
            note = need(body.note, "반려 사유")
            con.execute("UPDATE defects SET status='in_action', verification_note=?, updated_at=? WHERE id=?",
                        (note, t, did))
            add_event(con, did, uid, "reject", st, "in_action", note, t)
        else:
            raise HTTPException(422, "검증 결과(ok/reject)가 필요합니다")
    else:
        raise HTTPException(422, "알 수 없는 동작입니다")

    return get_defect(did, con)


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
