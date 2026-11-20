"""뚝딱건설 위험 작업 허가서 - FastAPI + SQLite"""
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("PERMIT_DB", str(BASE / "permits.db"))

TYPES = {"height": "고소작업", "hot": "화기작업", "confined": "밀폐공간작업"}
CHECKLISTS = {
    "height": ["안전대 착용 및 걸이 설비 확인", "작업발판·안전난간 설치 확인", "하부 출입통제 및 낙하물 방지"],
    "hot": ["소화기 2대 이상 비치", "인화성 물질 10m 이내 제거", "불티 비산방지포 설치 · 화재감시자 배치"],
    "confined": ["산소농도 18% 이상 측정", "유해가스 측정 및 환기 실시", "감시인 배치 · 구조장비 준비"],
}
# 상태 흐름: requested(신청) -> reviewed(안전검토 완료) -> approved(승인) -> in_progress(작업중) -> completed(종료)
#           requested/reviewed -> rejected(반려)
STATUS_KO = {"requested": "검토 대기", "reviewed": "승인 대기", "approved": "승인(작업 가능)",
             "in_progress": "작업중", "completed": "종료", "rejected": "반려"}
ROLE_KO = {"foreman": "작업반장", "safety": "안전담당", "manager": "현장책임자"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, role TEXT, team TEXT);
CREATE TABLE IF NOT EXISTS zones(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS permits(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, zone_id INTEGER NOT NULL REFERENCES zones(id),
  foreman_id INTEGER NOT NULL REFERENCES users(id), work_date TEXT NOT NULL,
  start_time TEXT NOT NULL, end_time TEXT NOT NULL, description TEXT NOT NULL, workers INTEGER NOT NULL,
  status TEXT NOT NULL, checklist TEXT, created_at TEXT, reviewer_id INTEGER, reviewed_at TEXT,
  review_note TEXT, approver_id INTEGER, approved_at TEXT, started_at TEXT, ended_at TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, permit_id INTEGER, at TEXT,
  user_id INTEGER, action TEXT, note TEXT);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def today():
    return date.today().isoformat()


def seed(con):
    users = [(1, "박반장", "foreman", "형틀팀"), (2, "최반장", "foreman", "용접팀"), (3, "정반장", "foreman", "설비팀"),
             (4, "이안전", "safety", "안전관리팀"), (5, "김소장", "manager", "현장소장")]
    con.executemany("INSERT INTO users VALUES(?,?,?,?)", users)
    zones = ["A동 지하1층", "A동 외벽", "B동 옥상", "B동 기계실", "C동 맨홀·집수정", "야적장"]
    con.executemany("INSERT INTO zones(name) VALUES(?)", [(z,) for z in zones])
    t = today()
    d = date.today()
    tm = (d + timedelta(days=1)).isoformat()
    ym = (d - timedelta(days=1)).isoformat()

    def ts(h, m=0):
        return f"{t}T{h:02d}:{m:02d}:00"

    # (type, zone, foreman, date, start, end, desc, workers, status, reviewer, approver, started, ended, note)
    rows = [
        ("height", 2, 1, t, "08:00", "12:00", "A동 외벽 갱폼 해체 및 비계 조립", 6, "in_progress", 4, 5, ts(8, 10), None, ""),
        ("hot", 4, 2, t, "09:00", "15:00", "B동 기계실 배관 용접", 3, "approved", 4, 5, None, None, ""),
        ("confined", 5, 3, t, "13:00", "17:00", "C동 집수정 청소 및 방수 점검", 4, "reviewed", 4, None, None, None,
         "가스측정기 보정 확인 완료"),
        ("height", 3, 1, t, "13:00", "17:00", "B동 옥상 방수층 시공", 5, "requested", None, None, None, None, ""),
        ("hot", 1, 2, t, "10:00", "12:00", "A동 지하1층 철골 절단", 2, "rejected", 4, None, None, None,
         "인화성 자재 적치 상태, 정리 후 재신청"),
        ("height", 2, 3, t, "07:30", "09:30", "A동 외벽 커튼월 앵커 점검", 2, "completed", 4, 5, ts(7, 40), ts(9, 20), ""),
        ("hot", 4, 2, tm, "09:00", "12:00", "B동 기계실 덕트 용접(내일)", 3, "requested", None, None, None, None, ""),
        ("confined", 5, 3, ym, "09:00", "12:00", "C동 맨홀 내부 점검(어제)", 2, "completed", 4, 5,
         f"{ym}T09:05:00", f"{ym}T11:50:00", ""),
    ]
    for ty, z, f, wd, st, et, desc, w, status, rev, appr, sa, ea, note in rows:
        cl = json.dumps([{"item": i, "checked": status != "requested"} for i in CHECKLISTS[ty]], ensure_ascii=False)
        cur = con.execute(
            "INSERT INTO permits(type,zone_id,foreman_id,work_date,start_time,end_time,description,workers,status,"
            "checklist,created_at,reviewer_id,reviewed_at,review_note,approver_id,approved_at,started_at,ended_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ty, z, f, wd, st, et, desc, w, status, cl, ts(6, 30), rev, ts(7, 0) if rev else None, note, appr,
             ts(7, 30) if appr else None, sa, ea))
        pid = cur.lastrowid
        evs = [("신청", f, ts(6, 30), "")]
        if rev:
            evs.append(("반려" if status == "rejected" else "안전검토", rev, ts(7, 0), note))
        if appr:
            evs.append(("승인", appr, ts(7, 30), ""))
        if sa:
            evs.append(("작업 시작", f, sa, ""))
        if ea:
            evs.append(("작업 종료", f, ea, ""))
        con.executemany("INSERT INTO events(permit_id,at,user_id,action,note) VALUES(?,?,?,?,?)",
                        [(pid, a, u, ac, n) for ac, u, a, n in evs])


@asynccontextmanager
async def lifespan(app):
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(con)
    con.commit()
    con.close()
    yield


app = FastAPI(title="뚝딱건설 위험 작업 허가서", lifespan=lifespan)


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


# 데모용 인증: X-User-Id 헤더로 사용자 식별. 실제 운영 시 로그인/토큰으로 교체해야 함.
def current_user(x_user_id: Optional[int] = Header(None), con=Depends(db)):
    u = con.execute("SELECT * FROM users WHERE id=?", (x_user_id,)).fetchone() if x_user_id else None
    if not u:
        raise HTTPException(401, "사용자를 선택하세요")
    return dict(u)


def need_role(u, role):
    if u["role"] != role:
        raise HTTPException(403, "이 작업은 '%s'만 할 수 있습니다" % ROLE_KO[role])


SELECT = """SELECT p.*, z.name zone, f.name foreman, f.team team, r.name reviewer, a.name approver
FROM permits p JOIN zones z ON z.id=p.zone_id JOIN users f ON f.id=p.foreman_id
LEFT JOIN users r ON r.id=p.reviewer_id LEFT JOIN users a ON a.id=p.approver_id"""


def fmt(row):
    d = dict(row)
    d["checklist"] = json.loads(d["checklist"] or "[]")
    d["type_ko"] = TYPES[d["type"]]
    d["status_ko"] = STATUS_KO[d["status"]]
    return d


def get_permit(con, pid):
    r = con.execute(SELECT + " WHERE p.id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "허가서를 찾을 수 없습니다")
    return r


def log(con, pid, uid, action, note=""):
    con.execute("INSERT INTO events(permit_id,at,user_id,action,note) VALUES(?,?,?,?,?)",
                (pid, now(), uid, action, note))


class PermitIn(BaseModel):
    type: str
    zone_id: int
    work_date: str
    start_time: str
    end_time: str
    description: str = Field(min_length=2, max_length=300)
    workers: int = Field(ge=1, le=200)


class ReviewIn(BaseModel):
    checklist: list[bool]
    approve: bool
    note: str = ""


class DecideIn(BaseModel):
    approve: bool
    note: str = ""


@app.get("/api/meta")
def meta(con=Depends(db)):
    return {"users": [dict(r) for r in con.execute("SELECT * FROM users")],
            "zones": [dict(r) for r in con.execute("SELECT * FROM zones")],
            "types": TYPES, "checklists": CHECKLISTS, "status": STATUS_KO, "roles": ROLE_KO, "today": today()}


@app.get("/api/permits")
def list_permits(status: Optional[str] = None, u=Depends(current_user), con=Depends(db)):
    where, args = [], []
    if u["role"] == "foreman":
        where.append("p.foreman_id=?")
        args.append(u["id"])
    if status:
        where.append("p.status=?")
        args.append(status)
    sql = SELECT + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY p.work_date DESC, p.start_time, p.id DESC"
    return [fmt(r) for r in con.execute(sql, args)]


@app.get("/api/permits/{pid}")
def detail(pid: int, u=Depends(current_user), con=Depends(db)):
    p = fmt(get_permit(con, pid))
    if u["role"] == "foreman" and p["foreman_id"] != u["id"]:
        raise HTTPException(403, "본인 허가서만 볼 수 있습니다")
    p["events"] = [dict(r) for r in con.execute(
        "SELECT e.at,e.action,e.note,u.name user FROM events e LEFT JOIN users u ON u.id=e.user_id "
        "WHERE permit_id=? ORDER BY e.id", (pid,))]
    return p


@app.post("/api/permits", status_code=201)
def create(body: PermitIn, u=Depends(current_user), con=Depends(db)):
    need_role(u, "foreman")
    if body.type not in TYPES:
        raise HTTPException(422, "작업 종류가 올바르지 않습니다")
    if not con.execute("SELECT 1 FROM zones WHERE id=?", (body.zone_id,)).fetchone():
        raise HTTPException(422, "구역이 올바르지 않습니다")
    try:
        wd = date.fromisoformat(body.work_date)
        datetime.strptime(body.start_time, "%H:%M")
        datetime.strptime(body.end_time, "%H:%M")
    except ValueError:
        raise HTTPException(422, "날짜/시간 형식이 올바르지 않습니다")
    if wd < date.today():
        raise HTTPException(422, "과거 날짜로는 신청할 수 없습니다")
    if body.end_time <= body.start_time:
        raise HTTPException(422, "종료 시간은 시작 시간보다 늦어야 합니다")
    cl = json.dumps([{"item": i, "checked": False} for i in CHECKLISTS[body.type]], ensure_ascii=False)
    cur = con.execute(
        "INSERT INTO permits(type,zone_id,foreman_id,work_date,start_time,end_time,description,workers,status,"
        "checklist,created_at) VALUES(?,?,?,?,?,?,?,?,'requested',?,?)",
        (body.type, body.zone_id, u["id"], body.work_date, body.start_time, body.end_time,
         body.description.strip(), body.workers, cl, now()))
    log(con, cur.lastrowid, u["id"], "신청")
    return fmt(get_permit(con, cur.lastrowid))


@app.post("/api/permits/{pid}/review")
def review(pid: int, body: ReviewIn, u=Depends(current_user), con=Depends(db)):
    need_role(u, "safety")
    p = get_permit(con, pid)
    if p["status"] != "requested":
        raise HTTPException(409, "검토 대기 상태의 허가서만 검토할 수 있습니다")
    items = json.loads(p["checklist"])
    if len(body.checklist) != len(items):
        raise HTTPException(422, "점검 항목 수가 맞지 않습니다")
    for it, c in zip(items, body.checklist):
        it["checked"] = c
    if body.approve and not all(body.checklist):
        raise HTTPException(422, "모든 안전 점검 항목을 확인해야 검토 완료할 수 있습니다")
    if not body.approve and not body.note.strip():
        raise HTTPException(422, "반려 사유를 입력하세요")
    status = "reviewed" if body.approve else "rejected"
    con.execute("UPDATE permits SET status=?,checklist=?,reviewer_id=?,reviewed_at=?,review_note=? WHERE id=?",
                (status, json.dumps(items, ensure_ascii=False), u["id"], now(), body.note.strip(), pid))
    log(con, pid, u["id"], "안전검토" if body.approve else "반려", body.note.strip())
    return fmt(get_permit(con, pid))


@app.post("/api/permits/{pid}/decide")
def decide(pid: int, body: DecideIn, u=Depends(current_user), con=Depends(db)):
    need_role(u, "manager")
    p = get_permit(con, pid)
    if p["status"] != "reviewed":
        raise HTTPException(409, "안전 검토가 끝난 허가서만 승인할 수 있습니다")
    if not body.approve and not body.note.strip():
        raise HTTPException(422, "반려 사유를 입력하세요")
    if body.approve:
        con.execute("UPDATE permits SET status='approved',approver_id=?,approved_at=? WHERE id=?",
                    (u["id"], now(), pid))
    else:
        con.execute("UPDATE permits SET status='rejected',approver_id=?,approved_at=?,review_note=? WHERE id=?",
                    (u["id"], now(), body.note.strip(), pid))
    log(con, pid, u["id"], "승인" if body.approve else "반려", body.note.strip())
    return fmt(get_permit(con, pid))


def own_permit(con, pid, u):
    need_role(u, "foreman")
    p = get_permit(con, pid)
    if p["foreman_id"] != u["id"]:
        raise HTTPException(403, "본인 허가서만 조작할 수 있습니다")
    return p


@app.post("/api/permits/{pid}/start")
def start(pid: int, u=Depends(current_user), con=Depends(db)):
    p = own_permit(con, pid, u)
    if p["status"] != "approved":
        raise HTTPException(409, "승인된 허가서만 작업을 시작할 수 있습니다 (현재: %s)" % STATUS_KO[p["status"]])
    if p["work_date"] != today():
        raise HTTPException(409, "허가 날짜(%s)에만 작업을 시작할 수 있습니다" % p["work_date"])
    con.execute("UPDATE permits SET status='in_progress',started_at=? WHERE id=? AND status='approved'",
                (now(), pid))
    log(con, pid, u["id"], "작업 시작")
    return fmt(get_permit(con, pid))


@app.post("/api/permits/{pid}/finish")
def finish(pid: int, u=Depends(current_user), con=Depends(db)):
    p = own_permit(con, pid, u)
    if p["status"] != "in_progress":
        raise HTTPException(409, "작업 중인 허가서만 종료할 수 있습니다")
    con.execute("UPDATE permits SET status='completed',ended_at=? WHERE id=? AND status='in_progress'",
                (now(), pid))
    log(con, pid, u["id"], "작업 종료")
    return fmt(get_permit(con, pid))


@app.get("/api/board")
def board(day: Optional[str] = None, u=Depends(current_user), con=Depends(db)):
    if u["role"] == "foreman":
        raise HTTPException(403, "현황판은 안전담당/현장책임자만 볼 수 있습니다")
    day = day or today()
    zones = [dict(r) | {"permits": []} for r in con.execute("SELECT * FROM zones ORDER BY id")]
    by = {z["id"]: z for z in zones}
    for r in con.execute(SELECT + " WHERE p.work_date=? ORDER BY p.start_time", (day,)):
        by[r["zone_id"]]["permits"].append(fmt(r))
    counts = {}
    for z in zones:
        for p in z["permits"]:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        active = [p for p in z["permits"] if p["status"] == "in_progress"]
        z["active_workers"] = sum(p["workers"] for p in active)
        z["in_progress"] = len(active)
        z["pending"] = sum(1 for p in z["permits"] if p["status"] in ("requested", "reviewed"))
    return {"day": day, "zones": zones, "counts": counts}


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 9640)))
