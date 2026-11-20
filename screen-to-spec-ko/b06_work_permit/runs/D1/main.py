"""뚝딱건설 위험 작업 허가서 - FastAPI + SQLite"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = os.environ.get("PERMIT_DB", str(BASE / "permits.db"))
VALID_HOURS = 8
FMT = "%Y-%m-%dT%H:%M:%S"

# 작업 종류별 필수 점검 항목 (각 3개)
CHECKLISTS = {
    "고소": ["안전대(추락방지 장비) 착용 및 고정점 확인", "작업발판·안전난간 설치 상태 확인", "하부 통제구역 설정 및 출입금지 표지"],
    "화기": ["소화기 비치 및 불티 비산 방지포 설치", "주변 인화성·가연성 물질 제거", "화재감시자 배치"],
    "밀폐": ["산소·유해가스 농도 측정 (적정 공기 확인)", "환기 장치 가동", "외부 감시인 배치 및 비상 연락 체계"],
}
ZONES = ["A동 지하 1층", "A동 옥상", "B동 3층", "C동 기계실", "외부 비계"]
ROLE_NAME = {"foreman": "작업반장", "safety": "안전 담당", "manager": "현장 책임자"}

app = FastAPI(title="뚝딱건설 위험 작업 허가서")


# ---------- DB ----------
@contextmanager
def db(write=False):
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")  # 승인 충돌 검사를 원자적으로
        yield conn
        if write:
            conn.execute("COMMIT")
    except BaseException:
        if write and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def now():
    return datetime.now().replace(microsecond=0)


def ts(d):
    return d.strftime(FMT) if d else None


def parse(s):
    return datetime.strptime(s, FMT) if s else None


def init_db():
    with db(True) as c:
        for ddl in (
            """
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
            """,
            """CREATE TABLE IF NOT EXISTS permits(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT NOT NULL, zone TEXT NOT NULL, description TEXT NOT NULL,
              checks TEXT NOT NULL,
              requester_id INTEGER NOT NULL,
              status TEXT NOT NULL,           -- requested/reviewed/approved/in_progress/ended/rejected
              created_at TEXT NOT NULL,
              reviewer_id INTEGER, reviewed_at TEXT, review_note TEXT,
              approver_id INTEGER, approved_at TEXT, expires_at TEXT,
              started_at TEXT, ended_at TEXT,
              rejected_by INTEGER, rejected_at TEXT, reject_reason TEXT);
            """,
        ):
            c.execute(ddl)
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed(c)


def seed(c):
    users = [
        (1, "김반장", "foreman"), (2, "박반장", "foreman"), (3, "이반장", "foreman"),
        (4, "최안전", "safety"), (5, "정책임", "manager"),
    ]
    c.executemany("INSERT INTO users VALUES(?,?,?)", users)
    n = now()

    def add(typ, zone, desc, req, status, created_ago_h, **kw):
        created = n - timedelta(hours=created_ago_h)
        checks = json.dumps({"items": CHECKLISTS[typ], "checked": [True] * 3}, ensure_ascii=False)
        row = dict(type=typ, zone=zone, description=desc, checks=checks, requester_id=req,
                   status=status, created_at=ts(created))
        for k, v in kw.items():
            row[k] = ts(v) if isinstance(v, datetime) else v
        cols = ",".join(row)
        c.execute(f"INSERT INTO permits({cols}) VALUES({','.join('?' * len(row))})", list(row.values()))

    def appr(ago_h):
        a = n - timedelta(hours=ago_h)
        return dict(reviewer_id=4, reviewed_at=a - timedelta(minutes=20), approver_id=5,
                    approved_at=a, expires_at=expiry(a))

    add("고소", "A동 옥상", "옥상 파라펫 방수 작업", 1, "in_progress", 3, **appr(2), started_at=n - timedelta(hours=1))
    add("화기", "C동 기계실", "배관 용접 (2차 라인)", 2, "approved", 2, **appr(0.5))
    add("고소", "외부 비계", "외벽 마감 도장", 3, "approved", 12, **appr(10))  # 만료 예시
    add("밀폐", "C동 기계실", "집수정 내부 청소", 1, "reviewed", 1, reviewer_id=4,
        reviewed_at=n - timedelta(minutes=15))
    add("화기", "B동 3층", "철골 절단 작업", 2, "requested", 0.3)
    add("밀폐", "B동 3층", "덕트 내부 점검", 3, "ended", 6, **appr(5), started_at=n - timedelta(hours=4),
        ended_at=n - timedelta(hours=2))
    add("고소", "A동 지하 1층", "천장 배관 행거 설치", 3, "rejected", 5, reviewer_id=4,
        reviewed_at=n - timedelta(hours=4), rejected_by=5, rejected_at=n - timedelta(hours=3),
        reject_reason="하부 통제 계획 보완 필요")


def expiry(approved):
    end_of_day = approved.replace(hour=23, minute=59, second=0)
    return ts(min(approved + timedelta(hours=VALID_HOURS), end_of_day))


# ---------- 도메인 ----------
def eff_status(p, t=None):
    """저장 상태 + 만료 판정. 승인됐으나 시작 못한 채 유효시간이 지나면 '만료'."""
    t = t or now()
    s = p["status"]
    if s == "approved" and t >= parse(p["expires_at"]):
        return "expired"
    return s


def window(p):
    """허가가 점유하는 시간 구간 (승인 후 ~ 만료/종료)."""
    start = parse(p["approved_at"])
    end = parse(p["ended_at"]) or parse(p["expires_at"])
    return start, end


def serialize(p, users):
    d = dict(p)
    chk = json.loads(d.pop("checks"))
    d["checklist"] = [{"item": i, "checked": c} for i, c in zip(chk["items"], chk["checked"])]
    d["effective_status"] = eff_status(p)
    d["overdue"] = bool(p["status"] == "in_progress" and p["expires_at"] and now() >= parse(p["expires_at"]))
    for k in ("requester", "reviewer", "approver"):
        d[k + "_name"] = users.get(d[k + "_id"])
    return d


def users_map(c):
    return {r["id"]: r["name"] for r in c.execute("SELECT id,name FROM users")}


def current_user(c, uid):
    if uid is None:
        raise HTTPException(401, "사용자를 선택하세요")
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(401, "알 수 없는 사용자")
    return u


def need_role(u, *roles):
    if u["role"] not in roles:
        raise HTTPException(403, f"{ROLE_NAME[u['role']]}은(는) 이 작업을 할 수 없습니다")


def get_permit(c, pid):
    p = c.execute("SELECT * FROM permits WHERE id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "허가서를 찾을 수 없습니다")
    return p


# ---------- API ----------
class PermitIn(BaseModel):
    type: str
    zone: str
    description: str
    checked: list[bool]


class ReasonIn(BaseModel):
    reason: str = ""


@app.get("/api/meta")
def meta():
    return {"checklists": CHECKLISTS, "zones": ZONES, "valid_hours": VALID_HOURS}


@app.get("/api/users")
def users():
    with db() as c:
        return [dict(r) | {"role_name": ROLE_NAME[r["role"]]} for r in c.execute("SELECT * FROM users")]


@app.post("/api/permits")
def create(body: PermitIn, x_user_id: int | None = Header(None)):
    with db(True) as c:
        u = current_user(c, x_user_id)
        need_role(u, "foreman")
        if body.type not in CHECKLISTS:
            raise HTTPException(422, "작업 종류는 고소·화기·밀폐 중 하나여야 합니다")
        if body.zone not in ZONES:
            raise HTTPException(422, "알 수 없는 구역입니다")
        if not body.description.strip():
            raise HTTPException(422, "작업 내용을 입력하세요")
        items = CHECKLISTS[body.type]
        if len(body.checked) != len(items) or not all(b is True for b in body.checked):
            raise HTTPException(422, "필수 점검 항목이 모두 체크되어야 신청할 수 있습니다")
        checks = json.dumps({"items": items, "checked": [True] * len(items)}, ensure_ascii=False)
        cur = c.execute(
            "INSERT INTO permits(type,zone,description,checks,requester_id,status,created_at) VALUES(?,?,?,?,?,?,?)",
            (body.type, body.zone, body.description.strip(), checks, u["id"], "requested", ts(now())),
        )
        return {"id": cur.lastrowid}


@app.get("/api/permits")
def list_permits(x_user_id: int | None = Header(None)):
    with db() as c:
        u = current_user(c, x_user_id)
        um = users_map(c)
        q = "SELECT * FROM permits"
        args = ()
        if u["role"] == "foreman":  # 작업반장은 자기 허가만
            q += " WHERE requester_id=?"
            args = (u["id"],)
        rows = c.execute(q + " ORDER BY id DESC", args).fetchall()
        return [serialize(r, um) for r in rows]


@app.post("/api/permits/{pid}/review")
def review(pid: int, body: ReasonIn, x_user_id: int | None = Header(None)):
    with db(True) as c:
        u = current_user(c, x_user_id)
        need_role(u, "safety")
        p = get_permit(c, pid)
        if p["status"] != "requested":
            raise HTTPException(409, "검토 대기 상태의 허가서만 검토할 수 있습니다")
        c.execute("UPDATE permits SET status='reviewed',reviewer_id=?,reviewed_at=?,review_note=? WHERE id=?",
                  (u["id"], ts(now()), body.reason.strip() or None, pid))
        return {"ok": True}


@app.post("/api/permits/{pid}/approve")
def approve(pid: int, x_user_id: int | None = Header(None)):
    with db(True) as c:
        u = current_user(c, x_user_id)
        need_role(u, "manager")
        p = get_permit(c, pid)
        if p["requester_id"] == u["id"]:
            raise HTTPException(403, "자신이 신청한 허가는 승인할 수 없습니다")
        if p["status"] != "reviewed":
            raise HTTPException(409, "안전 담당 검토를 마친 허가서만 승인할 수 있습니다")
        t = now()
        new_end = parse(expiry(t))
        # 같은 구역에서 시간이 겹치는 화기 ↔ 밀폐 동시 승인 금지
        other = {"화기": "밀폐", "밀폐": "화기"}.get(p["type"])
        if other:
            for o in c.execute(
                "SELECT * FROM permits WHERE zone=? AND type=? AND status IN ('approved','in_progress')",
                (p["zone"], other)).fetchall():
                s, e = window(o)
                if s < new_end and t < e:
                    raise HTTPException(
                        409, f"같은 구역({p['zone']})에 시간이 겹치는 {other} 작업 허가 #{o['id']}가 있어 "
                             f"{p['type']} 작업을 함께 승인할 수 없습니다 (#{o['id']} 종료/만료 후 승인 가능)")
        c.execute("UPDATE permits SET status='approved',approver_id=?,approved_at=?,expires_at=? WHERE id=?",
                  (u["id"], ts(t), ts(new_end), pid))
        return {"ok": True, "expires_at": ts(new_end)}


@app.post("/api/permits/{pid}/reject")
def reject(pid: int, body: ReasonIn, x_user_id: int | None = Header(None)):
    with db(True) as c:
        u = current_user(c, x_user_id)
        need_role(u, "safety", "manager")
        p = get_permit(c, pid)
        allowed = "requested" if u["role"] == "safety" else "reviewed"
        if p["status"] != allowed:
            raise HTTPException(409, "현재 단계에서 반려할 수 없습니다")
        if not body.reason.strip():
            raise HTTPException(422, "반려 사유를 입력하세요")
        c.execute("UPDATE permits SET status='rejected',rejected_by=?,rejected_at=?,reject_reason=? WHERE id=?",
                  (u["id"], ts(now()), body.reason.strip(), pid))
        return {"ok": True}


@app.post("/api/permits/{pid}/start")
def start(pid: int, x_user_id: int | None = Header(None)):
    with db(True) as c:
        u = current_user(c, x_user_id)
        need_role(u, "foreman")
        p = get_permit(c, pid)
        if p["requester_id"] != u["id"]:
            raise HTTPException(403, "본인이 신청한 허가만 시작할 수 있습니다")
        if p["status"] != "approved":
            raise HTTPException(409, "승인된 허가서만 작업을 시작할 수 있습니다")
        if eff_status(p) == "expired":
            raise HTTPException(409, "허가가 만료되었습니다. 새 허가를 신청하세요 (연장 불가)")
        c.execute("UPDATE permits SET status='in_progress',started_at=? WHERE id=?", (ts(now()), pid))
        return {"ok": True}


@app.post("/api/permits/{pid}/end")
def end(pid: int, x_user_id: int | None = Header(None)):
    with db(True) as c:
        u = current_user(c, x_user_id)
        need_role(u, "foreman")
        p = get_permit(c, pid)
        if p["requester_id"] != u["id"]:
            raise HTTPException(403, "본인이 신청한 허가만 종료할 수 있습니다")
        if p["status"] != "in_progress":
            raise HTTPException(409, "작업 중인 허가서만 종료할 수 있습니다")
        c.execute("UPDATE permits SET status='ended',ended_at=? WHERE id=?", (ts(now()), pid))
        return {"ok": True}


@app.get("/api/board")
def board(x_user_id: int | None = Header(None)):
    """오늘 구역별 허가 현황 (현장 책임자 · 안전 담당)"""
    with db() as c:
        u = current_user(c, x_user_id)
        need_role(u, "manager", "safety")
        um = users_map(c)
        today = now().strftime("%Y-%m-%d")
        out = {z: [] for z in ZONES}
        for r in c.execute("SELECT * FROM permits ORDER BY id DESC"):
            if r["created_at"][:10] == today or (r["approved_at"] or "")[:10] == today or r["status"] == "in_progress":
                out[r["zone"]].append(serialize(r, um))
        return {"date": today, "zones": out}


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 9650)))
