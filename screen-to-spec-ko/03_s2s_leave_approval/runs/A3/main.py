"""다온소프트 휴가 · 출장 신청 웹앱 (FastAPI + SQLite)

실행: python -m uvicorn main:app --reload   →  http://127.0.0.1:8000
최초 실행 시 daon.db 가 없으면 가상 데이터로 자동 생성된다. (초기화: daon.db 삭제)
"""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "daon.db"

# 신청 유형: 연차 잔여일수를 차감하는지 여부
TYPES = {
    "연차": True,
    "반차(오전)": True,
    "반차(오후)": True,
    "병가": False,
    "경조휴가": False,
    "출장": False,
}
HALF = {"반차(오전)", "반차(오후)"}

# 법정 공휴일 (평일 계산에서 제외)
HOLIDAYS = {
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 3, 2), date(2026, 5, 5), date(2026, 5, 25), date(2026, 6, 3),
    date(2026, 8, 17), date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26),
    date(2026, 10, 5), date(2026, 10, 9), date(2026, 12, 25),
    date(2027, 1, 1),
}


# ---------------------------------------------------------------- DB
@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


SCHEMA = """
CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    team TEXT NOT NULL,
    position TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('employee', 'manager')),
    manager_id INTEGER REFERENCES employees(id),
    annual_total REAL NOT NULL,
    joined TEXT NOT NULL
);
CREATE TABLE requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id INTEGER NOT NULL REFERENCES employees(id),
    type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    days REAL NOT NULL,
    reason TEXT NOT NULL,
    destination TEXT,
    status TEXT NOT NULL DEFAULT '대기' CHECK (status IN ('대기', '승인', '반려', '취소')),
    approver_id INTEGER REFERENCES employees(id),
    comment TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX idx_req_emp ON requests(emp_id);
CREATE INDEX idx_req_status ON requests(status);
"""


def workdays(start: date, end: date) -> float:
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5 and d not in HOLIDAYS:
            n += 1
        d += timedelta(days=1)
    return float(n)


def next_workday(d: date) -> date:
    while d.weekday() >= 5 or d in HOLIDAYS:
        d += timedelta(days=1)
    return d


def seed():
    today = date.today()
    now = datetime.now().replace(microsecond=0)
    with db() as con:
        con.executescript(SCHEMA)
        emps = [
            # id, 이름, 팀, 직급, 역할, 팀장id, 연차, 입사일
            (1, "박서준", "개발1팀", "팀장", "manager", None, 20, "2016-03-02"),
            (2, "최유리", "개발2팀", "팀장", "manager", None, 21, "2015-07-01"),
            (3, "정하늘", "경영지원팀", "팀장", "manager", None, 22, "2013-01-14"),
            (4, "김민수", "개발1팀", "책임", "employee", 1, 18, "2019-05-20"),
            (5, "이지은", "개발1팀", "선임", "employee", 1, 15, "2021-02-01"),
            (6, "오세훈", "개발1팀", "사원", "employee", 1, 15, "2024-03-04"),
            (7, "한소영", "개발2팀", "책임", "employee", 2, 17, "2020-09-14"),
            (8, "윤태영", "개발2팀", "선임", "employee", 2, 15, "2022-01-10"),
            (9, "강다은", "개발2팀", "사원", "employee", 2, 15, "2025-03-03"),
            (10, "송민재", "경영지원팀", "선임", "employee", 3, 16, "2021-06-07"),
            (11, "임수빈", "경영지원팀", "사원", "employee", 3, 15, "2025-01-06"),
        ]
        con.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)", emps)

        def wd(offset: int) -> date:
            return next_workday(today + timedelta(days=offset))

        # emp, 유형, 시작, 종료, 사유, 출장지, 상태, 승인자, 코멘트, 신청일 오프셋
        samples = [
            # 과거 승인 건 (잔여 연차 차감용)
            (4, "연차", wd(-120), wd(-118), "가족 여행", None, "승인", 1, "잘 다녀오세요.", -135),
            (4, "연차", wd(-60), wd(-60), "개인 사유", None, "승인", 1, None, -66),
            (4, "출장", wd(-40), wd(-38), "고객사 PoC 현장 지원", "부산 센텀 고객사", "승인", 1, None, -50),
            (5, "연차", wd(-90), wd(-86), "여름휴가", None, "승인", 1, None, -110),
            (5, "반차(오후)", wd(-30), wd(-30), "병원 진료", None, "승인", 1, None, -33),
            (6, "연차", wd(-45), wd(-44), "개인 사유", None, "승인", 1, None, -52),
            (7, "연차", wd(-100), wd(-96), "해외 여행", None, "승인", 2, "프로젝트 일정 확인했습니다.", -125),
            (7, "병가", wd(-20), wd(-19), "독감", None, "승인", 2, "빠른 쾌유를 바랍니다.", -20),
            (8, "연차", wd(-70), wd(-70), "이사", None, "승인", 2, None, -75),
            (8, "반차(오전)", wd(-15), wd(-15), "관공서 방문", None, "승인", 2, None, -18),
            (9, "연차", wd(-50), wd(-49), "개인 사유", None, "승인", 2, None, -58),
            (10, "연차", wd(-80), wd(-76), "가족 행사", None, "승인", 3, None, -100),
            (10, "출장", wd(-25), wd(-24), "협력사 계약 미팅", "대전 협력사", "승인", 3, None, -32),
            (11, "연차", wd(-35), wd(-35), "개인 사유", None, "승인", 3, None, -40),
            # 반려
            (6, "연차", wd(-10), wd(-8), "개인 여행", None, "반려", 1, "릴리즈 일정과 겹쳐서 어렵습니다. 다른 날짜로 다시 신청해 주세요.", -14),
            # 예정된 승인 건
            (5, "연차", wd(12), wd(14), "가족 여행", None, "승인", 1, None, -3),
            (8, "출장", wd(9), wd(10), "AWS Summit 참관", "서울 코엑스", "승인", 2, None, -6),
            # 승인 대기 건 (팀장 화면에 노출)
            (4, "연차", wd(20), wd(22), "추석 연휴 이후 휴식", None, "대기", None, None, -1),
            (6, "반차(오전)", wd(5), wd(5), "건강검진", None, "대기", None, None, -1),
            (5, "출장", wd(16), wd(17), "고객사 시스템 이관 지원", "광주 고객사 데이터센터", "대기", None, None, 0),
            (7, "연차", wd(25), wd(26), "개인 사유", None, "대기", None, None, -2),
            (9, "경조휴가", wd(8), wd(10), "결혼 (본인)", None, "대기", None, None, -1),
            (10, "출장", wd(14), wd(15), "ERP 도입 사례 견학", "울산 사업장", "대기", None, None, 0),
            (11, "반차(오후)", wd(4), wd(4), "개인 사유", None, "대기", None, None, 0),
            # 팀장 본인 신청 -> 팀장 상위 승인자가 없으므로 데모에서는 대기로 둠
        ]
        for emp, typ, s, e, reason, dest, status, appr, cmt, created_off in samples:
            days = 0.5 if typ in HALF else workdays(s, e)
            created = (now + timedelta(days=created_off)).isoformat(sep=" ")
            decided = None
            if status != "대기":
                decided = (datetime.fromisoformat(created) + timedelta(hours=5)).isoformat(sep=" ")
            con.execute(
                "INSERT INTO requests (emp_id,type,start_date,end_date,days,reason,destination,"
                "status,approver_id,comment,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (emp, typ, s.isoformat(), e.isoformat(), days, reason, dest, status, appr, cmt, created, decided),
            )


if not DB_PATH.exists():
    seed()

# ---------------------------------------------------------------- API
app = FastAPI(title="다온소프트 휴가·출장 신청")


def current_user(con, user_id: Optional[str]):
    if not user_id or not user_id.isdigit():
        raise HTTPException(401, "로그인이 필요합니다.")
    row = con.execute("SELECT * FROM employees WHERE id=?", (int(user_id),)).fetchone()
    if not row:
        raise HTTPException(401, "존재하지 않는 사용자입니다.")
    return row


def balance_of(con, emp) -> dict:
    year = str(date.today().year)

    def total(status):
        return con.execute(
            "SELECT COALESCE(SUM(days),0) FROM requests WHERE emp_id=? AND status=? "
            "AND type IN ('연차','반차(오전)','반차(오후)') AND substr(start_date,1,4)=?",
            (emp["id"], status, year),
        ).fetchone()[0]

    used, pending = total("승인"), total("대기")
    return {
        "total": emp["annual_total"],
        "used": used,
        "pending": pending,
        "remaining": emp["annual_total"] - used - pending,
        "year": int(year),
    }


def emp_dict(r):
    return {k: r[k] for k in ("id", "name", "team", "position", "role", "joined")}


class NewRequest(BaseModel):
    type: str
    start_date: date
    end_date: date
    reason: str = Field(min_length=2, max_length=200)
    destination: Optional[str] = Field(default=None, max_length=100)


class Decision(BaseModel):
    approve: bool
    comment: Optional[str] = Field(default=None, max_length=200)


def calc_days(typ: str, s: date, e: date) -> float:
    if typ not in TYPES:
        raise HTTPException(400, "알 수 없는 신청 유형입니다.")
    if e < s:
        raise HTTPException(400, "종료일이 시작일보다 빠릅니다.")
    if typ in HALF:
        if s != e:
            raise HTTPException(400, "반차는 하루만 신청할 수 있습니다.")
        return 0.5 if workdays(s, e) else 0.0
    return workdays(s, e)


@app.get("/api/users")
def users():
    with db() as con:
        rows = con.execute("SELECT * FROM employees ORDER BY role DESC, team, id").fetchall()
        return [emp_dict(r) for r in rows]


@app.get("/api/me")
def me(x_user_id: Optional[str] = Header(None)):
    with db() as con:
        u = current_user(con, x_user_id)
        mgr = None
        if u["manager_id"]:
            m = con.execute("SELECT name, position FROM employees WHERE id=?", (u["manager_id"],)).fetchone()
            mgr = f'{m["name"]} {m["position"]}'
        return {**emp_dict(u), "approver": mgr, "balance": balance_of(con, u), "types": list(TYPES)}


@app.get("/api/calc")
def calc(type: str, start_date: date, end_date: date):
    return {"days": calc_days(type, start_date, end_date)}


REQ_SELECT = (
    "SELECT r.*, e.name AS emp_name, e.team AS emp_team, e.position AS emp_position, "
    "a.name AS approver_name FROM requests r JOIN employees e ON e.id=r.emp_id "
    "LEFT JOIN employees a ON a.id=r.approver_id "
)


@app.get("/api/requests")
def list_requests(scope: str = "mine", status: Optional[str] = None, x_user_id: Optional[str] = Header(None)):
    with db() as con:
        u = current_user(con, x_user_id)
        sql, args = REQ_SELECT, []
        if scope == "mine":
            sql += "WHERE r.emp_id=? "
            args.append(u["id"])
        elif scope == "team":
            if u["role"] != "manager":
                raise HTTPException(403, "팀장만 조회할 수 있습니다.")
            sql += "WHERE e.manager_id=? "
            args.append(u["id"])
        else:
            raise HTTPException(400, "scope 값이 올바르지 않습니다.")
        if status:
            sql += "AND r.status=? "
            args.append(status)
        sql += "ORDER BY (r.status='대기') DESC, r.start_date DESC, r.id DESC"
        return [dict(r) for r in con.execute(sql, args).fetchall()]


@app.post("/api/requests", status_code=201)
def create_request(body: NewRequest, x_user_id: Optional[str] = Header(None)):
    with db() as con:
        u = current_user(con, x_user_id)
        if not u["manager_id"]:
            raise HTTPException(400, "상위 승인자가 없어 데모에서는 팀장 계정으로 신청할 수 없습니다.")
        days = calc_days(body.type, body.start_date, body.end_date)
        if days == 0:
            raise HTTPException(400, "선택한 기간에 근무일이 없습니다. (주말·공휴일 제외)")
        if body.type == "출장" and not (body.destination or "").strip():
            raise HTTPException(400, "출장지를 입력해 주세요.")
        if body.start_date.year != body.end_date.year:
            raise HTTPException(400, "연도를 넘나드는 신청은 나누어서 신청해 주세요.")
        dup = con.execute(
            "SELECT 1 FROM requests WHERE emp_id=? AND status IN ('대기','승인') "
            "AND start_date<=? AND end_date>=?",
            (u["id"], body.end_date.isoformat(), body.start_date.isoformat()),
        ).fetchone()
        if dup:
            raise HTTPException(409, "이미 신청된 기간과 겹칩니다.")
        if TYPES[body.type]:
            rem = balance_of(con, u)["remaining"]
            if days > rem:
                raise HTTPException(400, f"잔여 연차가 부족합니다. (신청 {days:g}일 / 잔여 {rem:g}일)")
        cur = con.execute(
            "INSERT INTO requests (emp_id,type,start_date,end_date,days,reason,destination,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (u["id"], body.type, body.start_date.isoformat(), body.end_date.isoformat(), days,
             body.reason.strip(), (body.destination or "").strip() or None,
             datetime.now().replace(microsecond=0).isoformat(sep=" ")),
        )
        return {"id": cur.lastrowid, "days": days}


@app.post("/api/requests/{rid}/cancel")
def cancel_request(rid: int, x_user_id: Optional[str] = Header(None)):
    with db() as con:
        u = current_user(con, x_user_id)
        r = con.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
        if not r or r["emp_id"] != u["id"]:
            raise HTTPException(404, "신청 건을 찾을 수 없습니다.")
        if r["status"] != "대기":
            raise HTTPException(400, "대기 중인 신청만 취소할 수 있습니다.")
        con.execute("UPDATE requests SET status='취소' WHERE id=?", (rid,))
        return {"ok": True}


@app.post("/api/requests/{rid}/decision")
def decide(rid: int, body: Decision, x_user_id: Optional[str] = Header(None)):
    with db() as con:
        u = current_user(con, x_user_id)
        if u["role"] != "manager":
            raise HTTPException(403, "팀장만 승인/반려할 수 있습니다.")
        r = con.execute(
            "SELECT r.*, e.manager_id FROM requests r JOIN employees e ON e.id=r.emp_id WHERE r.id=?", (rid,)
        ).fetchone()
        if not r or r["manager_id"] != u["id"]:
            raise HTTPException(404, "승인 권한이 있는 신청 건이 아닙니다.")
        if r["status"] != "대기":
            raise HTTPException(400, "이미 처리된 신청입니다.")
        if not body.approve and not (body.comment or "").strip():
            raise HTTPException(400, "반려 사유를 입력해 주세요.")
        status = "승인" if body.approve else "반려"
        con.execute(
            "UPDATE requests SET status=?, approver_id=?, comment=?, decided_at=? WHERE id=?",
            (status, u["id"], (body.comment or "").strip() or None,
             datetime.now().replace(microsecond=0).isoformat(sep=" "), rid),
        )
        return {"ok": True, "status": status}


@app.get("/api/team-calendar")
def team_calendar(month: str, x_user_id: Optional[str] = Header(None)):
    """같은 팀의 승인/대기 일정 (month = YYYY-MM)"""
    with db() as con:
        u = current_user(con, x_user_id)
        first = date.fromisoformat(month + "-01")
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        rows = con.execute(
            "SELECT r.type, r.start_date, r.end_date, r.status, e.name FROM requests r "
            "JOIN employees e ON e.id=r.emp_id WHERE e.team=? AND r.status IN ('승인','대기') "
            "AND r.start_date<=? AND r.end_date>=? ORDER BY r.start_date",
            (u["team"], last.isoformat(), first.isoformat()),
        ).fetchall()
        return [dict(r) for r in rows]


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
