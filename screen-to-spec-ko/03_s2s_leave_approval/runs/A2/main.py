"""다온소프트 휴가 · 출장 신청 — FastAPI + SQLite 데모 앱.

인증은 데모용으로 X-User-Id 헤더(화면 우상단 사용자 전환)만 사용한다.
실서비스에서는 사내 SSO/세션 인증으로 교체해야 한다.
"""
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "daon.db"

KINDS = {
    "annual": {"label": "연차", "deduct": True},
    "half_am": {"label": "오전 반차", "deduct": True},
    "half_pm": {"label": "오후 반차", "deduct": True},
    "sick": {"label": "병가", "deduct": False},
    "special": {"label": "경조휴가", "deduct": False},
    "trip": {"label": "출장", "deduct": False},
}
HALF = {"half_am", "half_pm"}

# 2026 공휴일(대체공휴일 포함) — 근무일 계산에서 제외
HOLIDAYS = {date.fromisoformat(d) for d in [
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01", "2026-03-02",
    "2026-05-01", "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-03", "2026-06-06",
    "2026-07-17", "2026-08-15", "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-26",
    "2026-09-28", "2026-10-03", "2026-10-05", "2026-10-09", "2026-12-25",
]}


def db():
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # 명시적 BEGIN 사용
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def workdays(start: date, end: date) -> float:
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5 and d not in HOLIDAYS:
            n += 1
        d += timedelta(days=1)
    return float(n)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, team TEXT NOT NULL, position TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('employee','manager','ceo')),
  approver_id INTEGER REFERENCES users(id), annual_total REAL NOT NULL, hire_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id), approver_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, days REAL NOT NULL,
  destination TEXT, reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','cancelled')),
  reject_reason TEXT, decided_at TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_req_user ON requests(user_id);
CREATE INDEX IF NOT EXISTS idx_req_approver ON requests(approver_id, status);
"""

USERS = [  # id, 이름, 팀, 직급, 역할, 결재자, 연차, 입사일
    (1, "한도윤", "경영", "대표이사", "ceo", None, 25, "2012-03-02"),
    (2, "김서연", "개발팀", "팀장", "manager", 1, 22, "2016-05-09"),
    (3, "박민준", "개발팀", "선임", "employee", 2, 17, "2019-09-02"),
    (4, "이지우", "개발팀", "사원", "employee", 2, 15, "2024-01-15"),
    (5, "최하은", "개발팀", "사원", "employee", 2, 15, "2025-03-04"),
    (6, "정우진", "영업팀", "팀장", "manager", 1, 20, "2017-02-13"),
    (7, "강예린", "영업팀", "책임", "employee", 6, 18, "2018-07-02"),
    (8, "윤시후", "영업팀", "사원", "employee", 6, 15, "2023-06-01"),
    (9, "임나연", "디자인팀", "팀장", "manager", 1, 19, "2018-04-16"),
    (10, "송재현", "디자인팀", "사원", "employee", 9, 15, "2022-10-04"),
]


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    conn.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?,?)", USERS)
    today = date.today()

    def m(weeks):  # 이번 주 월요일 기준 n주 뒤 월요일
        return today - timedelta(days=today.weekday()) + timedelta(weeks=weeks)

    def add(uid, appr, kind, s, e, dest, reason, status, rej=None, ago=10):
        days = 0.5 if kind in HALF else workdays(s, e)
        created = datetime.now() - timedelta(days=ago)
        decided = created + timedelta(days=1) if status in ("approved", "rejected") else None
        conn.execute(
            "INSERT INTO requests (user_id,approver_id,kind,start_date,end_date,days,destination,reason,"
            "status,reject_reason,decided_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, appr, kind, s.isoformat(), e.isoformat(), days, dest, reason, status, rej,
             decided.isoformat(timespec="seconds") if decided else None,
             created.isoformat(timespec="seconds")))

    d = timedelta
    conn.execute("BEGIN")
    add(3, 2, "annual", m(-12), m(-12) + d(days=4), None, "여름 휴가", "approved", ago=100)
    add(3, 2, "half_pm", m(-4) + d(days=2), m(-4) + d(days=2), None, "병원 진료", "approved", ago=35)
    add(3, 2, "trip", m(1), m(1) + d(days=2), "부산 고객사", "솔루션 현장 설치 지원", "pending", ago=2)
    add(4, 2, "annual", m(-8), m(-8) + d(days=1), None, "개인 사유", "approved", ago=60)
    add(4, 2, "annual", m(2), m(2) + d(days=3), None, "가족 여행", "pending", ago=1)
    add(4, 2, "half_am", m(-2) + d(days=1), m(-2) + d(days=1), None, "관공서 방문", "rejected",
        "해당일 배포 일정이 있어 조정 부탁드립니다.", ago=20)
    add(5, 2, "annual", m(3), m(3) + d(days=1), None, "이사", "pending", ago=0)
    add(5, 2, "trip", m(-6), m(-6) + d(days=1), "대전 R&D센터", "기술 워크숍 참석", "approved", ago=50)
    add(7, 6, "annual", m(-10), m(-10) + d(days=4), None, "리프레시 휴가", "approved", ago=80)
    add(7, 6, "trip", m(1) + d(days=1), m(1) + d(days=3), "광주 지사", "신규 거래처 미팅", "pending", ago=3)
    add(8, 6, "special", m(-3), m(-3) + d(days=2), None, "결혼 휴가", "approved", ago=45)
    add(8, 6, "half_pm", m(1) + d(days=4), m(1) + d(days=4), None, "자녀 학교 행사", "pending", ago=1)
    add(10, 9, "annual", m(-5), m(-5) + d(days=2), None, "개인 사유", "approved", ago=45)
    add(10, 9, "sick", m(-1), m(-1), None, "감기 몸살", "approved", ago=12)
    add(2, 1, "trip", m(2), m(2) + d(days=1), "서울 파트너사", "공동 개발 킥오프", "pending", ago=2)
    add(6, 1, "annual", m(4), m(4) + d(days=4), None, "가족 휴가", "pending", ago=0)
    conn.execute("COMMIT")


@asynccontextmanager
async def lifespan(app: FastAPI):
    with closing(db()) as conn:
        conn.executescript(SCHEMA)
        seed(conn)
    yield


app = FastAPI(title="다온소프트 휴가·출장 신청", lifespan=lifespan)


def current_user(x_user_id: Optional[int] = Header(default=None)):
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (x_user_id,)).fetchone()
    if not row:
        raise HTTPException(401, "사용자를 선택해 주세요.")
    return dict(row)


def balance_of(conn, uid: int):
    total = conn.execute("SELECT annual_total FROM users WHERE id=?", (uid,)).fetchone()[0]
    deduct = tuple(k for k, v in KINDS.items() if v["deduct"])
    q = ",".join("?" * len(deduct))

    def s(status):
        return conn.execute(
            f"SELECT COALESCE(SUM(days),0) FROM requests WHERE user_id=? AND status=? AND kind IN ({q})"
            " AND substr(start_date,1,4)=?", (uid, status, *deduct, str(date.today().year))).fetchone()[0]

    used, pending = s("approved"), s("pending")
    return {"total": total, "used": used, "pending": pending, "remaining": total - used - pending}


@app.get("/api/users")
def list_users():
    with closing(db()) as conn:
        return [dict(r) for r in conn.execute("SELECT id,name,team,position,role FROM users ORDER BY id")]


@app.get("/api/me")
def me(user=Depends(current_user)):
    with closing(db()) as conn:
        appr = conn.execute("SELECT name,position FROM users WHERE id=?", (user["approver_id"],)).fetchone()
        return {**user, "approver": dict(appr) if appr else None, "balance": balance_of(conn, user["id"]),
                "kinds": {k: v["label"] for k, v in KINDS.items()}}


class NewRequest(BaseModel):
    kind: Literal["annual", "half_am", "half_pm", "sick", "special", "trip"]
    start_date: date
    end_date: date
    destination: Optional[str] = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=500)


def compute_days(kind: str, start: date, end: date) -> float:
    if end < start:
        raise HTTPException(422, "종료일이 시작일보다 빠릅니다.")
    if kind in HALF:
        if start != end:
            raise HTTPException(422, "반차는 하루만 선택할 수 있습니다.")
        if workdays(start, end) == 0:
            raise HTTPException(422, "주말·공휴일에는 신청할 수 없습니다.")
        return 0.5
    days = workdays(start, end)
    if days == 0:
        raise HTTPException(422, "선택한 기간에 근무일이 없습니다.")
    return days


@app.get("/api/preview")
def preview(kind: str, start_date: date, end_date: date, user=Depends(current_user)):
    if kind not in KINDS:
        raise HTTPException(422, "잘못된 유형입니다.")
    return {"days": compute_days(kind, start_date, end_date)}


@app.post("/api/requests", status_code=201)
def create_request(body: NewRequest, user=Depends(current_user)):
    reason = body.reason.strip()
    dest = (body.destination or "").strip() or None
    if not reason:
        raise HTTPException(422, "사유를 입력해 주세요.")
    if body.kind == "trip" and not dest:
        raise HTTPException(422, "출장지를 입력해 주세요.")
    if body.kind != "trip":
        dest = None
    if not user["approver_id"]:
        raise HTTPException(422, "결재자가 지정되지 않았습니다.")
    days = compute_days(body.kind, body.start_date, body.end_date)
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            overlap = conn.execute(
                "SELECT 1 FROM requests WHERE user_id=? AND status IN ('pending','approved')"
                " AND start_date<=? AND end_date>=?",
                (user["id"], body.end_date.isoformat(), body.start_date.isoformat())).fetchone()
            if overlap:
                raise HTTPException(409, "같은 기간에 이미 신청한 건이 있습니다.")
            if KINDS[body.kind]["deduct"]:
                bal = balance_of(conn, user["id"])
                if days > bal["remaining"]:
                    raise HTTPException(422, f"잔여 연차({bal['remaining']:g}일)가 부족합니다. 신청: {days:g}일")
            cur = conn.execute(
                "INSERT INTO requests (user_id,approver_id,kind,start_date,end_date,days,destination,reason,"
                "status,created_at) VALUES (?,?,?,?,?,?,?,?,'pending',?)",
                (user["id"], user["approver_id"], body.kind, body.start_date.isoformat(),
                 body.end_date.isoformat(), days, dest, reason, datetime.now().isoformat(timespec="seconds")))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return {"id": cur.lastrowid, "days": days}


REQ_SELECT = ("SELECT r.*, u.name AS user_name, u.team, u.position, a.name AS approver_name "
              "FROM requests r JOIN users u ON u.id=r.user_id JOIN users a ON a.id=r.approver_id ")


@app.get("/api/requests/mine")
def my_requests(user=Depends(current_user)):
    with closing(db()) as conn:
        rows = conn.execute(REQ_SELECT + "WHERE r.user_id=? ORDER BY r.created_at DESC, r.id DESC",
                            (user["id"],)).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/requests/inbox")
def inbox(status: Literal["pending", "done"] = "pending", user=Depends(current_user)):
    if user["role"] == "employee":
        raise HTTPException(403, "결재 권한이 없습니다.")
    cond = "r.status='pending'" if status == "pending" else "r.status IN ('approved','rejected')"
    order = "r.start_date, r.id" if status == "pending" else "r.decided_at DESC"
    with closing(db()) as conn:
        rows = conn.execute(REQ_SELECT + f"WHERE r.approver_id=? AND {cond} ORDER BY {order}",
                            (user["id"],)).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["balance"] = balance_of(conn, r["user_id"])
            out.append(item)
        return out


def transition(rid: int, user, field: str, new_status: str, reject_reason=None):
    """pending 건만 상태 전이. field: 처리 권한자 컬럼(approver_id=결재, user_id=본인 취소)."""
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
        if not row:
            raise HTTPException(404, "신청 건을 찾을 수 없습니다.")
        if row[field] != user["id"]:
            raise HTTPException(403, "권한이 없습니다.")
        cur = conn.execute(
            "UPDATE requests SET status=?, reject_reason=?, decided_at=? WHERE id=? AND status='pending'",
            (new_status, reject_reason, datetime.now().isoformat(timespec="seconds"), rid))
        if cur.rowcount == 0:
            raise HTTPException(409, "이미 처리된 신청입니다.")
    return {"ok": True}


class Reject(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


@app.post("/api/requests/{rid}/approve")
def approve(rid: int, user=Depends(current_user)):
    return transition(rid, user, "approver_id", "approved")


@app.post("/api/requests/{rid}/reject")
def reject(rid: int, body: Reject, user=Depends(current_user)):
    if not body.reason.strip():
        raise HTTPException(422, "반려 사유를 입력해 주세요.")
    return transition(rid, user, "approver_id", "rejected", body.reason.strip())


@app.post("/api/requests/{rid}/cancel")
def cancel(rid: int, user=Depends(current_user)):
    return transition(rid, user, "user_id", "cancelled")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
