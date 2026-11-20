"""뚝딱건설 위험 작업 허가서 — FastAPI + SQLite.

흐름: 신청(requested) → 안전 담당 검토(reviewed) → 현장 책임자 승인(approved)
      → 작업 시작(in_progress) → 종료(completed).  반려(rejected) / 만료(expired) 가능.

주의: 로그인은 데모용이다. 요청 헤더 X-User-Id 로 사용자를 고르며 비밀번호 검증은 없다.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = Path(os.environ.get("PERMIT_DB", BASE / "permits.db"))

VALID_HOURS = 8
DAY_CUTOFF = (23, 59)  # 그날 23:59 를 넘기지 않는다

# 작업 종류별 필수 점검 항목 (종류마다 3개)
TYPES = {
    "height": {
        "label": "고소 작업",
        "checklist": [
            {"key": "harness", "label": "안전대 착용 및 고정점(생명줄) 확인"},
            {"key": "scaffold", "label": "작업발판·안전난간 설치 상태 점검"},
            {"key": "drop", "label": "하부 출입통제 및 낙하물 방지 조치"},
        ],
    },
    "fire": {
        "label": "화기 작업",
        "checklist": [
            {"key": "extinguisher", "label": "소화기 비치 및 불티 비산 방지포 설치"},
            {"key": "combustibles", "label": "주변 인화성·가연성 물질 제거"},
            {"key": "watcher", "label": "화재 감시자 배치"},
        ],
    },
    "confined": {
        "label": "밀폐 작업",
        "checklist": [
            {"key": "gas", "label": "산소·유해가스 농도 측정 (적정공기 확인)"},
            {"key": "vent", "label": "환기 설비 가동"},
            {"key": "attendant", "label": "감시인 배치 및 비상 구조 장비 확보"},
        ],
    },
}
EXCLUSIVE = {"fire": "confined", "confined": "fire"}  # 같은 구역·겹치는 시간에 동시 승인 금지
LIVE = ("approved", "in_progress")

STATUS_LABEL = {
    "requested": "신청", "reviewed": "검토 완료", "approved": "승인",
    "in_progress": "작업 중", "completed": "종료", "rejected": "반려", "expired": "만료",
}


def now() -> datetime:
    """현재 시각 (테스트에서 이 함수를 바꿔 끼운다)."""
    return datetime.now().replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0, tzinfo=None).isoformat(timespec="seconds")


# --------------------------------------------------------------------- DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('foreman','safety','manager')));
CREATE TABLE IF NOT EXISTS zones(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS permits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL CHECK(type IN ('height','fire','confined')),
  zone_id INTEGER NOT NULL REFERENCES zones(id),
  requester_id INTEGER NOT NULL REFERENCES users(id),
  description TEXT NOT NULL DEFAULT '',
  planned_start TEXT NOT NULL, planned_end TEXT NOT NULL,
  checks TEXT NOT NULL,
  status TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  reviewer_id INTEGER REFERENCES users(id), reviewed_at TEXT,
  approver_id INTEGER REFERENCES users(id), approved_at TEXT, valid_until TEXT,
  rejected_by INTEGER REFERENCES users(id), reject_reason TEXT,
  started_at TEXT, ended_at TEXT);
CREATE INDEX IF NOT EXISTS ix_permits_zone ON permits(zone_id, status);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, permit_id INTEGER NOT NULL,
  actor_id INTEGER, action TEXT NOT NULL, at TEXT NOT NULL, note TEXT);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)  # 수동 트랜잭션
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        sweep(conn)
        yield conn
    finally:
        conn.close()


@contextmanager
def tx():
    """쓰기용: 만료 정리 후 BEGIN IMMEDIATE 로 직렬화(동시 승인 시 겹침 검사 보호)."""
    conn = connect()
    try:
        sweep(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def log(conn, pid, uid, action, note=None):
    conn.execute("INSERT INTO events(permit_id,actor_id,action,at,note) VALUES(?,?,?,?,?)",
                 (pid, uid, action, iso(now()), note))


def sweep(conn):
    """승인됐지만 유효시간이 지난(시작 못 한) 허가를 만료 처리."""
    t = iso(now())
    conn.execute("BEGIN IMMEDIATE")
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM permits WHERE status='approved' AND valid_until < ?", (t,))]
        for pid in ids:
            conn.execute("UPDATE permits SET status='expired' WHERE id=?", (pid,))
            log(conn, pid, None, "expired")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def init_db(seed=True):
    with connect() as c:
        c.executescript(SCHEMA)
        if seed and c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed_data(c)


def seed_data(c):
    users = [(1, "김철수", "foreman"), (2, "이영호", "foreman"), (3, "박안전", "safety"),
             (4, "정세린", "safety"), (5, "한승우", "manager"), (6, "윤재민", "manager")]
    c.executemany("INSERT INTO users VALUES(?,?,?)", users)
    zones = ["A동 지하 1층", "A동 골조 3층", "B동 외벽", "기계실", "옥상"]
    c.executemany("INSERT INTO zones VALUES(?,?)", list(enumerate(zones, 1)))

    n = now()
    day = n.replace(hour=0, minute=0, second=0)

    def at(h, m=0):
        return day.replace(hour=h, minute=m)

    def full(t):
        return json.dumps([i["key"] for i in TYPES[t]["checklist"]])

    def valid_until(approved):
        cap = approved.replace(hour=DAY_CUTOFF[0], minute=DAY_CUTOFF[1], second=0)
        return min(approved + timedelta(hours=VALID_HOURS), cap)

    appr_recent = max(n - timedelta(hours=1), day)
    appr_old = n - timedelta(hours=9)
    appr_done = max(n - timedelta(hours=5), day)
    rows = [
        # (type, zone, req, desc, ps, pe, status, extra)
        ("height", 2, 1, "3층 슬래브 거푸집 해체 및 외부 비계 작업", at(9), at(17), "approved",
         dict(reviewer_id=3, reviewed_at=iso(appr_recent - timedelta(minutes=20)), approver_id=5,
              approved_at=iso(appr_recent), valid_until=iso(valid_until(appr_recent)))),
        ("fire", 4, 2, "배관 용접 (냉각수 라인 신설)", at(8), at(18), "in_progress",
         dict(reviewer_id=4, reviewed_at=iso(n - timedelta(hours=2)), approver_id=6,
              approved_at=iso(max(n - timedelta(hours=2), day)),
              valid_until=iso(valid_until(max(n - timedelta(hours=2), day))),
              started_at=iso(max(n - timedelta(minutes=30), day)))),
        ("confined", 4, 1, "냉각수 저장조 내부 도장 전 점검", at(10), at(15), "reviewed",
         dict(reviewer_id=3, reviewed_at=iso(n - timedelta(minutes=10)))),
        ("height", 3, 2, "외벽 마감 패널 설치", at(13), at(17), "requested", {}),
        ("fire", 5, 1, "옥상 방수 토치 작업", at(8), at(12), "expired",
         dict(reviewer_id=4, reviewed_at=iso(appr_old - timedelta(minutes=30)), approver_id=5,
              approved_at=iso(appr_old), valid_until=iso(valid_until(appr_old)))),
        ("confined", 1, 2, "지하 집수정 청소", at(8), at(11), "completed",
         dict(reviewer_id=3, reviewed_at=iso(appr_done - timedelta(minutes=20)), approver_id=6,
              approved_at=iso(appr_done), valid_until=iso(valid_until(appr_done)),
              started_at=iso(appr_done + timedelta(minutes=10)),
              ended_at=iso(appr_done + timedelta(hours=2)))),
        ("height", 5, 5, "옥상 난간 점검 (현장 책임자 본인 신청)", at(13), at(16), "reviewed",
         dict(reviewer_id=4, reviewed_at=iso(n - timedelta(minutes=5)))),
        ("fire", 2, 1, "철골 가용접", at(9), at(11), "rejected",
         dict(reviewer_id=3, rejected_by=3, reject_reason="불티 비산 방지포 미설치 — 보완 후 재신청")),
    ]
    for t, z, req, desc, ps, pe, st, ex in rows:
        cols = dict(type=t, zone_id=z, requester_id=req, description=desc,
                    planned_start=iso(ps), planned_end=iso(pe), checks=full(t), status=st,
                    requested_at=iso(n - timedelta(hours=10)), **ex)
        c.execute(f"INSERT INTO permits({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                  list(cols.values()))


# --------------------------------------------------------------- 도메인 규칙
def conflicts(conn, p, ref=None):
    """같은 구역에서 시간이 겹치는, 승인된(작업 중 포함) 반대 종류(화기↔밀폐) 허가."""
    other = EXCLUSIVE.get(p["type"])
    if not other:
        return []
    t = iso(ref or now())
    return [dict(r) for r in conn.execute(
        """SELECT id, type, planned_start, planned_end FROM permits
           WHERE zone_id=? AND type=? AND status IN ('approved','in_progress') AND id<>?
             AND planned_start < ?
             AND (CASE WHEN status='in_progress' THEN MAX(planned_end, ?) ELSE planned_end END) > ?""",
        (p["zone_id"], other, p["id"], p["planned_end"], t, p["planned_start"]))]


def compute_valid_until(approved: datetime) -> datetime:
    cap = approved.replace(hour=DAY_CUTOFF[0], minute=DAY_CUTOFF[1], second=0)
    return min(approved + timedelta(hours=VALID_HOURS), cap)


def serialize(conn, r, user):
    p = dict(r)
    p["checks"] = json.loads(p["checks"])
    names = {u["id"]: u["name"] for u in conn.execute("SELECT id,name FROM users")}
    p["requester_name"] = names.get(p["requester_id"])
    p["reviewer_name"] = names.get(p["reviewer_id"])
    p["approver_name"] = names.get(p["approver_id"])
    p["zone_name"] = conn.execute("SELECT name FROM zones WHERE id=?", (p["zone_id"],)).fetchone()[0]
    p["type_label"] = TYPES[p["type"]]["label"]
    p["status_label"] = STATUS_LABEL[p["status"]]
    actions, notice = [], None
    if user:
        mine = p["requester_id"] == user["id"]
        if user["role"] == "safety" and p["status"] == "requested":
            actions.append("review")
        if user["role"] == "manager" and p["status"] == "reviewed":
            if mine:
                notice = "본인이 신청한 허가는 승인할 수 없음"
            else:
                actions.append("approve")
        if mine and p["status"] == "approved":
            actions.append("start")
        if mine and p["status"] == "in_progress":
            actions.append("end")
    p["actions"], p["notice"] = actions, notice
    p["overdue"] = p["status"] == "in_progress" and bool(p["valid_until"]) and iso(now()) > p["valid_until"]
    p["conflicts"] = conflicts(conn, p) if p["status"] in ("requested", "reviewed") else []
    return p


# ------------------------------------------------------------------- API
app = FastAPI(title="뚝딱건설 위험 작업 허가서")


def current_user(x_user_id: int | None = Header(default=None)):
    if x_user_id is None:
        raise HTTPException(401, "사용자를 선택하세요")
    with db() as conn:
        u = conn.execute("SELECT * FROM users WHERE id=?", (x_user_id,)).fetchone()
    if not u:
        raise HTTPException(401, "알 수 없는 사용자")
    return dict(u)


class PermitIn(BaseModel):
    type: str
    zone_id: int
    description: str = Field(default="", max_length=500)
    planned_start: datetime
    planned_end: datetime
    checks: dict[str, bool] = {}


class Decision(BaseModel):
    decision: str  # "ok" | "reject"
    note: str | None = Field(default=None, max_length=300)


@app.get("/api/meta")
def meta():
    with db() as conn:
        return {
            "types": TYPES, "status_label": STATUS_LABEL,
            "users": [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id")],
            "zones": [dict(r) for r in conn.execute("SELECT * FROM zones ORDER BY id")],
            "now": iso(now()),
        }


@app.get("/api/permits")
def list_permits(scope: str = "mine", user=Depends(current_user)):
    """scope: mine(내 신청) | queue(내 역할의 처리 대기) | all"""
    where, args = "1=1", []
    if scope == "mine":
        where, args = "requester_id=?", [user["id"]]
    elif scope == "queue":
        st = {"safety": "requested", "manager": "reviewed"}.get(user["role"])
        where, args = ("status=?", [st]) if st else ("0=1", [])
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM permits WHERE {where} ORDER BY id DESC", args).fetchall()
        return [serialize(conn, r, user) for r in rows]


@app.post("/api/permits", status_code=201)
def create_permit(body: PermitIn, user=Depends(current_user)):
    if user["role"] == "safety":
        raise HTTPException(403, "안전 담당은 허가를 신청하지 않음")
    spec = TYPES.get(body.type)
    if not spec:
        raise HTTPException(422, "작업 종류는 고소·화기·밀폐 중 하나")
    missing = [i["label"] for i in spec["checklist"] if body.checks.get(i["key"]) is not True]
    if missing:
        raise HTTPException(422, {"message": "필수 점검 항목이 비어 있어 신청을 받지 않음", "missing": missing})
    ps, pe = body.planned_start.replace(tzinfo=None), body.planned_end.replace(tzinfo=None)
    if ps >= pe:
        raise HTTPException(422, "작업 종료 예정이 시작 예정보다 늦어야 함")
    if ps.date() != pe.date():
        raise HTTPException(422, "허가는 하루 단위(자정을 넘지 않게)로 신청")
    if pe <= now():
        raise HTTPException(422, "작업 종료 예정 시각이 이미 지남")
    with tx() as conn:
        if not conn.execute("SELECT 1 FROM zones WHERE id=?", (body.zone_id,)).fetchone():
            raise HTTPException(422, "없는 구역")
        cur = conn.execute(
            """INSERT INTO permits(type,zone_id,requester_id,description,planned_start,planned_end,
               checks,status,requested_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (body.type, body.zone_id, user["id"], body.description.strip(), iso(ps), iso(pe),
             json.dumps([i["key"] for i in spec["checklist"]]), "requested", iso(now())))
        log(conn, cur.lastrowid, user["id"], "requested")
        row = conn.execute("SELECT * FROM permits WHERE id=?", (cur.lastrowid,)).fetchone()
        return serialize(conn, row, user)


def _load(conn, pid):
    r = conn.execute("SELECT * FROM permits WHERE id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "허가를 찾을 수 없음")
    return r


def _need_status(r, status, what):
    if r["status"] != status:
        if r["status"] == "expired":
            raise HTTPException(409, "만료된 허가임 — 연장 없이 새 허가를 신청해야 함")
        raise HTTPException(409, f"{what}할 수 없는 상태: {STATUS_LABEL[r['status']]}")


@app.post("/api/permits/{pid}/review")
def review(pid: int, body: Decision, user=Depends(current_user)):
    if user["role"] != "safety":
        raise HTTPException(403, "안전 담당만 검토할 수 있음")
    if body.decision not in ("ok", "reject"):
        raise HTTPException(422, "decision 은 ok 또는 reject")
    with tx() as conn:
        r = _load(conn, pid)
        _need_status(r, "requested", "검토")
        if r["requester_id"] == user["id"]:
            raise HTTPException(403, "본인이 신청한 허가는 검토할 수 없음")
        if body.decision == "ok":
            conn.execute("UPDATE permits SET status='reviewed', reviewer_id=?, reviewed_at=? WHERE id=?",
                         (user["id"], iso(now()), pid))
            log(conn, pid, user["id"], "reviewed", body.note)
        else:
            _reject(conn, pid, user, body.note)
        return serialize(conn, _load(conn, pid), user)


def _reject(conn, pid, user, note):
    if not (note and note.strip()):
        raise HTTPException(422, "반려 사유를 적어야 함")
    conn.execute("UPDATE permits SET status='rejected', rejected_by=?, reject_reason=? WHERE id=?",
                 (user["id"], note.strip(), pid))
    log(conn, pid, user["id"], "rejected", note.strip())


@app.post("/api/permits/{pid}/approve")
def approve(pid: int, body: Decision, user=Depends(current_user)):
    if user["role"] != "manager":
        raise HTTPException(403, "현장 책임자만 승인할 수 있음")
    if body.decision not in ("ok", "reject"):
        raise HTTPException(422, "decision 은 ok 또는 reject")
    with tx() as conn:
        r = _load(conn, pid)
        _need_status(r, "reviewed", "승인")
        if body.decision == "reject":
            _reject(conn, pid, user, body.note)
            return serialize(conn, _load(conn, pid), user)
        if r["requester_id"] == user["id"]:
            raise HTTPException(403, "본인이 신청한 허가는 승인할 수 없음")
        clash = conflicts(conn, r)
        if clash:
            c = clash[0]
            raise HTTPException(409, f"같은 구역에서 시간이 겹치는 {TYPES[c['type']]['label']} 허가 #{c['id']} 가 "
                                     f"승인되어 있어 함께 승인할 수 없음")
        t = now()
        until = compute_valid_until(t)
        if until <= t:
            raise HTTPException(409, "오늘 남은 유효 시간이 없어 승인할 수 없음 — 내일 다시 신청")
        conn.execute("UPDATE permits SET status='approved', approver_id=?, approved_at=?, valid_until=? WHERE id=?",
                     (user["id"], iso(t), iso(until), pid))
        log(conn, pid, user["id"], "approved")
        return serialize(conn, _load(conn, pid), user)


@app.post("/api/permits/{pid}/start")
def start(pid: int, user=Depends(current_user)):
    with tx() as conn:
        r = _load(conn, pid)
        if r["requester_id"] != user["id"]:
            raise HTTPException(403, "신청한 작업반장만 작업을 시작할 수 있음")
        _need_status(r, "approved", "작업 시작")
        if iso(now()) > r["valid_until"]:  # sweep 직후라도 한 번 더 확인
            raise HTTPException(409, "만료된 허가임 — 연장 없이 새 허가를 신청해야 함")
        conn.execute("UPDATE permits SET status='in_progress', started_at=? WHERE id=?", (iso(now()), pid))
        log(conn, pid, user["id"], "started")
        return serialize(conn, _load(conn, pid), user)


@app.post("/api/permits/{pid}/end")
def end(pid: int, user=Depends(current_user)):
    with tx() as conn:
        r = _load(conn, pid)
        if r["requester_id"] != user["id"]:
            raise HTTPException(403, "신청한 작업반장만 작업을 종료할 수 있음")
        _need_status(r, "in_progress", "작업 종료")
        conn.execute("UPDATE permits SET status='completed', ended_at=? WHERE id=?", (iso(now()), pid))
        log(conn, pid, user["id"], "ended")
        return serialize(conn, _load(conn, pid), user)


@app.get("/api/board")
def board(date: str | None = None, user=Depends(current_user)):
    """구역별 허가 현황 (작업 예정일 기준, 기본 오늘)."""
    day = date or now().date().isoformat()
    try:
        datetime.fromisoformat(day)
    except ValueError:
        raise HTTPException(422, "date 형식은 YYYY-MM-DD")
    with db() as conn:
        out = []
        for z in conn.execute("SELECT * FROM zones ORDER BY id"):
            rows = conn.execute("SELECT * FROM permits WHERE zone_id=? AND substr(planned_start,1,10)=? "
                                "ORDER BY planned_start, id", (z["id"], day)).fetchall()
            permits = [serialize(conn, r, user) for r in rows]
            counts = {}
            for p in permits:
                counts[p["status"]] = counts.get(p["status"], 0) + 1
            out.append({"zone_id": z["id"], "zone_name": z["name"], "permits": permits, "counts": counts})
        return {"date": day, "now": iso(now()), "zones": out}


@app.get("/api/permits/{pid}/events")
def permit_events(pid: int, user=Depends(current_user)):
    with db() as conn:
        _load(conn, pid)
        return [dict(r) for r in conn.execute(
            "SELECT e.at, e.action, e.note, u.name AS actor FROM events e "
            "LEFT JOIN users u ON u.id=e.actor_id WHERE permit_id=? ORDER BY e.id", (pid,))]


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 9630)))
