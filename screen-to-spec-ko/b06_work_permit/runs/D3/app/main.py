import json
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import clock, db, rules

STATUS_LABEL = {
    "requested": "검토 대기", "reviewed": "승인 대기", "approved": "승인(시작 전)",
    "in_progress": "작업 중", "completed": "종료", "rejected": "반려", "expired": "만료",
}
APPLY_ROLES = ("작업반장", "현장책임자")  # 신청 가능 역할 (책임자도 신청 가능하지만 자기 건은 승인 불가)


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    yield


app = FastAPI(title="뚝딱건설 위험 작업 허가서", lifespan=lifespan)


@contextmanager
def tx():
    """쓰기용 트랜잭션. IMMEDIATE 로 잡아 동시 승인 경쟁(충돌 검사 우회)을 막는다."""
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def current_user(x_user_id: int = Header(default=None), con=Depends(get_con)):
    # 데모용 간이 로그인: 헤더의 사용자 id 를 신뢰한다(실서비스라면 인증 필요).
    row = con.execute("SELECT * FROM users WHERE id=?", (x_user_id,)).fetchone() if x_user_id else None
    if not row:
        raise HTTPException(401, "사용자를 선택하세요.")
    return dict(row)


def log(con, pid, user, action, note=None):
    con.execute("INSERT INTO events(permit_id,at,actor_id,action,note) VALUES(?,?,?,?,?)",
                (pid, rules.fmt(clock.now()), user["id"], action, note))


def actions_for(p, user, now):
    st = rules.effective_status(p, now)
    mine = p["applicant_id"] == user["id"]
    acts = []
    if user["role"] == "안전담당" and st == "requested" and not mine:
        acts += ["review", "reject"]
    if user["role"] == "현장책임자" and st == "reviewed" and not mine:
        acts += ["approve", "reject"]
    if mine and st == "approved":
        acts.append("start")
    if mine and st == "in_progress":
        acts.append("end")
    return acts


def view(con, p, user, now):
    st = rules.effective_status(p, now)
    names = {r["id"]: r["name"] for r in con.execute("SELECT id,name FROM users")}
    zone = con.execute("SELECT name FROM zones WHERE id=?", (p["zone_id"],)).fetchone()["name"]
    checks = json.loads(p["checks_json"])
    out = {k: p[k] for k in ("id", "zone_id", "work_type", "description", "created_at", "reviewed_at",
                             "review_comment", "approved_at", "valid_until", "started_at", "ended_at",
                             "reject_reason", "applicant_id")}
    out.update(
        status=st, status_label=STATUS_LABEL[st], zone=zone,
        applicant=names[p["applicant_id"]],
        reviewer=names.get(p["reviewer_id"]), approver=names.get(p["approver_id"]),
        checks=[{"key": k, "label": lab, "ok": bool(checks.get(k))}
                for k, lab in rules.CHECKLISTS[p["work_type"]].items()],
        actions=actions_for(p, user, now),
        # 유효시간이 지났는데 아직 작업 중인 경우(종료 처리 필요)
        overdue=st == "in_progress" and now > rules.parse(p["valid_until"]),
    )
    return out


def get_permit(con, pid):
    p = con.execute("SELECT * FROM permits WHERE id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "허가서를 찾을 수 없습니다.")
    return dict(p)


# ---------- 조회 ----------
@app.get("/api/meta")
def meta(con=Depends(get_con)):
    return {
        "users": [dict(r) for r in con.execute("SELECT * FROM users")],
        "zones": [dict(r) for r in con.execute("SELECT * FROM zones")],
        "checklists": {t: [{"key": k, "label": lab} for k, lab in items.items()]
                       for t, items in rules.CHECKLISTS.items()},
        "now": rules.fmt(clock.now()), "valid_hours": rules.VALID_HOURS,
    }


@app.get("/api/permits")
def list_permits(user=Depends(current_user), con=Depends(get_con)):
    now = clock.now()
    # 작업반장은 자기 허가만, 안전 담당·현장 책임자는 전체
    if user["role"] == "작업반장":
        rows = con.execute("SELECT * FROM permits WHERE applicant_id=? ORDER BY id DESC", (user["id"],))
    else:
        rows = con.execute("SELECT * FROM permits ORDER BY id DESC")
    return [view(con, dict(r), user, now) for r in rows.fetchall()]


@app.get("/api/permits/{pid}")
def one_permit(pid: int, user=Depends(current_user), con=Depends(get_con)):
    p = get_permit(con, pid)
    if user["role"] == "작업반장" and p["applicant_id"] != user["id"]:
        raise HTTPException(403, "본인 허가만 볼 수 있습니다.")
    out = view(con, p, user, clock.now())
    out["history"] = [dict(r) for r in con.execute(
        "SELECT e.at,e.action,e.note,u.name actor FROM events e JOIN users u ON u.id=e.actor_id "
        "WHERE permit_id=? ORDER BY e.id", (pid,))]
    return out


@app.get("/api/dashboard")
def dashboard(user=Depends(current_user), con=Depends(get_con)):
    if user["role"] == "작업반장":
        raise HTTPException(403, "현황판은 안전 담당·현장 책임자만 볼 수 있습니다.")
    now = clock.now()
    today = rules.fmt(now)[:10]
    zones = []
    for z in con.execute("SELECT * FROM zones").fetchall():
        rows = con.execute(
            "SELECT * FROM permits WHERE zone_id=? AND (substr(created_at,1,10)=? OR substr(approved_at,1,10)=? "
            "OR status='in_progress') ORDER BY id", (z["id"], today, today)).fetchall()
        items = [view(con, dict(r), user, now) for r in rows]
        state = ("working" if any(i["status"] == "in_progress" for i in items)
                 else "approved" if any(i["status"] == "approved" for i in items) else "idle")
        zones.append({"id": z["id"], "name": z["name"], "state": state, "permits": items})
    counts = {}
    for z in zones:
        for i in z["permits"]:
            counts[i["status"]] = counts.get(i["status"], 0) + 1
    return {"now": rules.fmt(now), "zones": zones, "counts": counts}


# ---------- 신청 ----------
class NewPermit(BaseModel):
    zone_id: int
    work_type: str
    description: str = Field(default="", max_length=200)
    checks: dict[str, bool] = {}


@app.post("/api/permits", status_code=201)
def create_permit(body: NewPermit, user=Depends(current_user)):
    if user["role"] not in APPLY_ROLES:
        raise HTTPException(403, "허가 신청은 작업반장(또는 현장 책임자)만 할 수 있습니다.")
    missing = rules.missing_checks(body.work_type, body.checks)
    if missing is None:
        raise HTTPException(422, "작업 종류는 고소·화기·밀폐 중 하나여야 합니다.")
    if missing:
        labels = [rules.CHECKLISTS[body.work_type][k] for k in missing]
        raise HTTPException(422, "필수 점검 항목이 비었습니다: " + " / ".join(labels))
    with tx() as con:
        if not con.execute("SELECT 1 FROM zones WHERE id=?", (body.zone_id,)).fetchone():
            raise HTTPException(422, "존재하지 않는 구역입니다.")
        now = rules.fmt(clock.now())
        cur = con.execute(
            "INSERT INTO permits(applicant_id,zone_id,work_type,description,status,checks_json,created_at) "
            "VALUES(?,?,?,?, 'requested', ?, ?)",
            (user["id"], body.zone_id, body.work_type, body.description.strip(),
             json.dumps({k: True for k in rules.CHECKLISTS[body.work_type]}), now))
        log(con, cur.lastrowid, user, "신청")
        return {"id": cur.lastrowid}


# ---------- 상태 전이 ----------
class Decision(BaseModel):
    comment: str = ""


def transition(pid, user, role, from_status, handler):
    with tx() as con:
        p = get_permit(con, pid)
        now = clock.now()
        if user["role"] != role:
            raise HTTPException(403, f"{role}만 할 수 있습니다.")
        if p["applicant_id"] == user["id"]:
            raise HTTPException(403, "본인이 신청한 허가는 검토·승인할 수 없습니다.")
        st = rules.effective_status(p, now)
        if st != from_status:
            raise HTTPException(409, f"현재 상태({STATUS_LABEL[st]})에서는 할 수 없습니다.")
        handler(con, p, now)
        return {"ok": True}


@app.post("/api/permits/{pid}/review")
def review(pid: int, body: Decision, user=Depends(current_user)):
    def h(con, p, now):
        con.execute("UPDATE permits SET status='reviewed',reviewer_id=?,reviewed_at=?,review_comment=? WHERE id=?",
                    (user["id"], rules.fmt(now), body.comment, p["id"]))
        log(con, p["id"], user, "안전 검토 완료", body.comment)
    return transition(pid, user, "안전담당", "requested", h)


@app.post("/api/permits/{pid}/approve")
def approve(pid: int, body: Decision, user=Depends(current_user)):
    def h(con, p, now):
        until = rules.valid_until_for(now)
        if until <= now:
            raise HTTPException(409, "23:59 이후에는 승인할 수 없습니다. 다음 날 처리하세요.")
        others = [dict(r) for r in con.execute(
            "SELECT * FROM permits WHERE zone_id=? AND id<>?", (p["zone_id"], p["id"]))]
        c = rules.find_conflict(p, others, now)
        if c:
            raise HTTPException(
                409, f"같은 구역에서 시간이 겹치는 {c['work_type']} 작업(허가 #{c['id']})이 있어 "
                     f"{p['work_type']} 작업을 함께 승인할 수 없습니다.")
        con.execute("UPDATE permits SET status='approved',approver_id=?,approved_at=?,valid_until=? WHERE id=?",
                    (user["id"], rules.fmt(now), rules.fmt(until), p["id"]))
        log(con, p["id"], user, "승인", f"유효 {rules.fmt(until)} 까지")
    return transition(pid, user, "현장책임자", "reviewed", h)


@app.post("/api/permits/{pid}/reject")
def reject(pid: int, body: Decision, user=Depends(current_user)):
    if user["role"] not in ("안전담당", "현장책임자"):
        raise HTTPException(403, "반려 권한이 없습니다.")
    reason = body.comment.strip()
    if not reason:
        raise HTTPException(422, "반려 사유를 입력하세요.")
    stage = "requested" if user["role"] == "안전담당" else "reviewed"

    def h(con, p, now):
        con.execute("UPDATE permits SET status='rejected',rejected_by=?,rejected_at=?,reject_reason=? WHERE id=?",
                    (user["id"], rules.fmt(now), reason, p["id"]))
        log(con, p["id"], user, "반려", reason)
    return transition(pid, user, user["role"], stage, h)


def own_transition(pid, user, from_status, handler):
    with tx() as con:
        p = get_permit(con, pid)
        now = clock.now()
        if p["applicant_id"] != user["id"]:
            raise HTTPException(403, "신청한 본인만 작업을 시작·종료할 수 있습니다.")
        st = rules.effective_status(p, now)
        if st == "expired":
            raise HTTPException(409, "허가가 만료되었습니다. 새 허가를 신청하세요(연장 불가).")
        if st != from_status:
            raise HTTPException(409, f"현재 상태({STATUS_LABEL[st]})에서는 할 수 없습니다. "
                                     "승인된 허가만 작업을 시작할 수 있습니다.")
        handler(con, p, now)
        return {"ok": True}


@app.post("/api/permits/{pid}/start")
def start(pid: int, user=Depends(current_user)):
    def h(con, p, now):
        con.execute("UPDATE permits SET status='in_progress',started_at=? WHERE id=?", (rules.fmt(now), p["id"]))
        log(con, p["id"], user, "작업 시작")
    return own_transition(pid, user, "approved", h)


@app.post("/api/permits/{pid}/end")
def end(pid: int, user=Depends(current_user)):
    def h(con, p, now):
        con.execute("UPDATE permits SET status='completed',ended_at=? WHERE id=?", (rules.fmt(now), p["id"]))
        log(con, p["id"], user, "작업 종료")
    return own_transition(pid, user, "in_progress", h)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
