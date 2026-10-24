"""다온소프트 휴가·출장 신청 웹앱 (FastAPI + SQLite)."""
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "daonsoft.db"
TODAY = date.today()

# 공휴일 (주말 외 휴일은 일수 계산에서 제외)
HOLIDAYS = {
    "2026-10-05", "2026-10-09", "2026-12-25",
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-01",
}

# 연차에서 차감되는 휴가 종류와 차감 방식
LEAVE_KINDS = {"연차": 1.0, "반차(오전)": 0.5, "반차(오후)": 0.5, "병가": 1.0, "경조휴가": 1.0}
DEDUCT_KINDS = {"연차", "반차(오전)", "반차(오후)"}
TRIP_KINDS = {"국내출장", "해외출장"}

app = FastAPI(title="다온소프트 휴가·출장 신청")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------- 초기화/시드
def init_db():
    with closing(db()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS employees(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL,
            team TEXT NOT NULL, is_manager INTEGER NOT NULL DEFAULT 0,
            manager_id INTEGER REFERENCES employees(id), annual_total REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id INTEGER NOT NULL REFERENCES employees(id),
            category TEXT NOT NULL, kind TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, days REAL NOT NULL,
            destination TEXT, reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '대기',
            reviewer_id INTEGER REFERENCES employees(id), review_comment TEXT,
            created_at TEXT NOT NULL, reviewed_at TEXT);
        """)
        if c.execute("SELECT COUNT(*) FROM employees").fetchone()[0]:
            return
        emps = [
            # id, 이름, 직함, 팀, 팀장여부, 팀장id, 연차총일수
            (1, "김도윤", "개발1팀장", "개발1팀", 1, None, 20),
            (2, "박서연", "개발2팀장", "개발2팀", 1, None, 22),
            (3, "이준호", "선임연구원", "개발1팀", 0, 1, 17),
            (4, "최유진", "연구원", "개발1팀", 0, 1, 15),
            (5, "정민재", "책임연구원", "개발1팀", 0, 1, 20),
            (6, "한지우", "선임연구원", "개발2팀", 0, 2, 16),
            (7, "오세린", "연구원", "개발2팀", 0, 2, 15),
            (8, "강태현", "책임연구원", "개발2팀", 0, 2, 19),
        ]
        c.executemany("INSERT INTO employees VALUES(?,?,?,?,?,?,?)", emps)

        def d(offset):
            return (TODAY + timedelta(days=offset)).isoformat()

        def ts(offset):
            return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d %H:%M")

        # emp, category, kind, start, end, dest, reason, status, reviewer, comment, created, reviewed
        seeds = [
            (3, "휴가", "연차", d(-60), d(-58), None, "가족 여행", "승인", 1, "잘 다녀오세요.", ts(-70), ts(-69)),
            (3, "휴가", "반차(오후)", d(-20), d(-20), None, "병원 진료", "승인", 1, None, ts(-22), ts(-21)),
            (3, "출장", "국내출장", d(12), d(13), "부산 고객사", "솔루션 현장 점검", "대기", None, None, ts(-1), None),
            (4, "휴가", "연차", d(-45), d(-41), None, "여름휴가", "승인", 1, "일정 공유 부탁드려요.", ts(-55), ts(-54)),
            (4, "휴가", "연차", d(5), d(6), None, "개인 사유", "대기", None, None, ts(-2), None),
            (4, "휴가", "연차", d(-10), d(-10), None, "개인 사유", "반려", 1, "릴리즈 일정과 겹쳐 조정 부탁드립니다.", ts(-14), ts(-13)),
            (5, "출장", "해외출장", d(30), d(34), "싱가포르 파트너사", "해외 파트너 미팅 및 PoC 데모", "대기", None, None, ts(0), None),
            (5, "휴가", "연차", d(-80), d(-78), None, "개인 사유", "승인", 1, None, ts(-90), ts(-89)),
            (6, "휴가", "연차", d(-30), d(-28), None, "결혼기념 여행", "승인", 2, None, ts(-40), ts(-39)),
            (6, "휴가", "반차(오전)", d(3), d(3), None, "자녀 학교 행사", "대기", None, None, ts(-1), None),
            (7, "출장", "국내출장", d(-15), d(-14), "대전 연구소", "기술 워크숍 참석", "승인", 2, None, ts(-20), ts(-19)),
            (7, "휴가", "병가", d(-5), d(-4), None, "감기 몸살", "승인", 2, "쾌유를 빕니다.", ts(-5), ts(-5)),
            (8, "휴가", "연차", d(20), d(24), None, "가족 여행", "대기", None, None, ts(-3), None),
            (8, "휴가", "연차", d(-100), d(-96), None, "해외여행", "승인", 2, None, ts(-110), ts(-109)),
            (1, "출장", "국내출장", d(8), d(9), "광주 지사", "지사 개발자 간담회", "승인", None, "팀장 본인 신청(자동 승인)", ts(-4), ts(-4)),
        ]
        for emp, cat, kind, s, e, dest, reason, st, rev, com, cr, rv in seeds:
            days = calc_days(kind, s, e)
            c.execute(
                "INSERT INTO requests(emp_id,category,kind,start_date,end_date,days,destination,reason,"
                "status,reviewer_id,review_comment,created_at,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (emp, cat, kind, s, e, days, dest, reason, st, rev, com, cr, rv))
        c.commit()


def is_workday(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def calc_days(kind: str, start: str, end: str) -> float:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    n = sum(1 for i in range((e - s).days + 1) if is_workday(s + timedelta(days=i)))
    if kind.startswith("반차"):
        return 0.5 if n else 0.0
    return float(n)


# ---------------------------------------------------------------- 공통 헬퍼
def current_user(c, x_user_id: Optional[int]):
    if x_user_id is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    u = c.execute("SELECT * FROM employees WHERE id=?", (x_user_id,)).fetchone()
    if not u:
        raise HTTPException(401, "존재하지 않는 사용자입니다.")
    return u


def balance(c, emp_id: int) -> dict:
    total = c.execute("SELECT annual_total FROM employees WHERE id=?", (emp_id,)).fetchone()[0]
    marks = ",".join("?" * len(DEDUCT_KINDS))

    def sum_status(status):
        return c.execute(
            f"SELECT COALESCE(SUM(days),0) FROM requests WHERE emp_id=? AND status=? AND kind IN ({marks})",
            (emp_id, status, *DEDUCT_KINDS)).fetchone()[0]

    used, pending = sum_status("승인"), sum_status("대기")
    return {"total": total, "used": used, "pending": pending, "remaining": total - used - pending}


def row_to_req(r) -> dict:
    return dict(r)


# ---------------------------------------------------------------- API
class NewRequest(BaseModel):
    category: Literal["휴가", "출장"]
    kind: str
    start_date: date
    end_date: date
    destination: Optional[str] = None
    reason: str


class Decision(BaseModel):
    action: Literal["승인", "반려"]
    comment: Optional[str] = None


@app.get("/api/employees")
def employees():
    with closing(db()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM employees ORDER BY id")]


@app.get("/api/me")
def me(x_user_id: Optional[int] = Header(None)):
    with closing(db()) as c:
        u = current_user(c, x_user_id)
        return {**dict(u), "balance": balance(c, u["id"])}


@app.get("/api/calc")
def calc(kind: str, start: date, end: date):
    if end < start:
        raise HTTPException(400, "종료일이 시작일보다 빠릅니다.")
    return {"days": calc_days(kind, start.isoformat(), end.isoformat())}


@app.get("/api/requests")
def my_requests(x_user_id: Optional[int] = Header(None)):
    with closing(db()) as c:
        u = current_user(c, x_user_id)
        rows = c.execute(
            "SELECT r.*, v.name AS reviewer_name FROM requests r "
            "LEFT JOIN employees v ON v.id=r.reviewer_id WHERE r.emp_id=? ORDER BY r.id DESC", (u["id"],))
        return [row_to_req(r) for r in rows]


@app.post("/api/requests", status_code=201)
def create_request(body: NewRequest, x_user_id: Optional[int] = Header(None)):
    with closing(db()) as c:
        u = current_user(c, x_user_id)
        valid = LEAVE_KINDS if body.category == "휴가" else TRIP_KINDS
        if body.kind not in valid:
            raise HTTPException(400, "신청 종류가 올바르지 않습니다.")
        if body.end_date < body.start_date:
            raise HTTPException(400, "종료일이 시작일보다 빠릅니다.")
        if body.kind.startswith("반차") and body.start_date != body.end_date:
            raise HTTPException(400, "반차는 하루만 신청할 수 있습니다.")
        if body.category == "출장" and not (body.destination or "").strip():
            raise HTTPException(400, "출장지를 입력해 주세요.")
        if not body.reason.strip():
            raise HTTPException(400, "사유를 입력해 주세요.")
        s, e = body.start_date.isoformat(), body.end_date.isoformat()
        days = calc_days(body.kind, s, e)
        if days == 0:
            raise HTTPException(400, "선택한 기간에 근무일이 없습니다. (주말·공휴일 제외)")
        overlap = c.execute(
            "SELECT 1 FROM requests WHERE emp_id=? AND status IN ('대기','승인') "
            "AND start_date<=? AND end_date>=?", (u["id"], e, s)).fetchone()
        if overlap:
            raise HTTPException(400, "같은 기간에 이미 신청(또는 승인)된 건이 있습니다.")
        if body.kind in DEDUCT_KINDS:
            remaining = balance(c, u["id"])["remaining"]
            if days > remaining:
                raise HTTPException(400, f"잔여 연차가 부족합니다. (신청 {days}일 / 잔여 {remaining}일)")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        status, reviewer, comment, reviewed = "대기", None, None, None
        if u["is_manager"] and u["manager_id"] is None:
            # 상위 결재자가 없는 팀장은 본인 신청이 자동 승인됨
            status, comment, reviewed = "승인", "팀장 본인 신청(자동 승인)", now
        cur = c.execute(
            "INSERT INTO requests(emp_id,category,kind,start_date,end_date,days,destination,reason,"
            "status,reviewer_id,review_comment,created_at,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (u["id"], body.category, body.kind, s, e, days, (body.destination or "").strip() or None,
             body.reason.strip(), status, reviewer, comment, now, reviewed))
        c.commit()
        return {"id": cur.lastrowid, "status": status, "days": days}


@app.post("/api/requests/{rid}/cancel")
def cancel_request(rid: int, x_user_id: Optional[int] = Header(None)):
    with closing(db()) as c:
        u = current_user(c, x_user_id)
        r = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
        if not r or r["emp_id"] != u["id"]:
            raise HTTPException(404, "신청 내역을 찾을 수 없습니다.")
        if r["status"] != "대기":
            raise HTTPException(400, "대기 중인 신청만 취소할 수 있습니다.")
        c.execute("UPDATE requests SET status='취소' WHERE id=?", (rid,))
        c.commit()
        return {"ok": True}


@app.get("/api/approvals")
def approvals(x_user_id: Optional[int] = Header(None)):
    """팀장: 본인 팀원들의 신청 목록 (대기 우선)."""
    with closing(db()) as c:
        u = current_user(c, x_user_id)
        if not u["is_manager"]:
            raise HTTPException(403, "팀장만 접근할 수 있습니다.")
        rows = c.execute(
            "SELECT r.*, e.name AS emp_name, e.title AS emp_title, v.name AS reviewer_name "
            "FROM requests r JOIN employees e ON e.id=r.emp_id "
            "LEFT JOIN employees v ON v.id=r.reviewer_id "
            "WHERE e.manager_id=? AND r.status!='취소' "
            "ORDER BY (r.status='대기') DESC, r.id DESC", (u["id"],)).fetchall()
        out = []
        for r in rows:
            item = row_to_req(r)
            item["balance"] = balance(c, r["emp_id"])
            out.append(item)
        return out


@app.post("/api/requests/{rid}/decision")
def decide(rid: int, body: Decision, x_user_id: Optional[int] = Header(None)):
    with closing(db()) as c:
        u = current_user(c, x_user_id)
        if not u["is_manager"]:
            raise HTTPException(403, "팀장만 승인/반려할 수 있습니다.")
        r = c.execute(
            "SELECT r.*, e.manager_id FROM requests r JOIN employees e ON e.id=r.emp_id WHERE r.id=?",
            (rid,)).fetchone()
        if not r or r["manager_id"] != u["id"]:
            raise HTTPException(404, "담당 팀원의 신청이 아닙니다.")
        if r["status"] != "대기":
            raise HTTPException(400, "이미 처리되었거나 취소된 신청입니다.")
        comment = (body.comment or "").strip() or None
        if body.action == "반려" and not comment:
            raise HTTPException(400, "반려 시에는 사유를 입력해 주세요.")
        if body.action == "승인" and r["kind"] in DEDUCT_KINDS:
            # 대기분은 이미 잔여에서 차감 예약되어 있으므로 총량만 확인
            b = balance(c, r["emp_id"])
            if b["used"] + r["days"] > b["total"]:
                raise HTTPException(400, "신청자의 잔여 연차가 부족해 승인할 수 없습니다.")
        c.execute(
            "UPDATE requests SET status=?, reviewer_id=?, review_comment=?, reviewed_at=? WHERE id=?",
            (body.action, u["id"], comment, datetime.now().strftime("%Y-%m-%d %H:%M"), rid))
        c.commit()
        return {"ok": True, "status": body.action}


@app.get("/api/meta")
def meta():
    return {"leave_kinds": list(LEAVE_KINDS), "trip_kinds": sorted(TRIP_KINDS), "deduct": sorted(DEDUCT_KINDS),
            "today": TODAY.isoformat()}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
