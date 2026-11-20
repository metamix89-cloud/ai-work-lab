"""뚝딱건설 위험 작업 허가서 - FastAPI + SQLite"""
import json
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "permits.db"

TYPES = {
    "고소": ["안전대 착용 및 고리 체결", "추락방호망/난간 설치", "작업발판 및 사다리 상태 점검", "하부 통제구역 설정"],
    "화기": ["소화기 2대 이상 비치", "불티 비산방지포 설치", "주변 가연물 제거", "화재감시자 배치"],
    "밀폐": ["산소·유해가스 농도 측정", "환기 설비 가동", "외부 감시인 배치", "비상 구조장비 비치"],
}
# 상태: 신청 → 검토완료(안전) → 승인(책임자) → 작업중 → 종료 / 반려 / 취소
STATUSES = ["신청", "검토완료", "승인", "작업중", "종료", "반려", "취소"]

app = FastAPI(title="뚝딱건설 위험 작업 허가서")
SESSIONS: dict[str, int] = {}


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, name TEXT, role TEXT CHECK(role IN ('foreman','safety','manager')), team TEXT);
    CREATE TABLE IF NOT EXISTS zones(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS permits(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL, zone_id INTEGER NOT NULL REFERENCES zones(id),
        foreman_id INTEGER NOT NULL REFERENCES users(id),
        work_date TEXT NOT NULL, start_time TEXT, end_time TEXT,
        description TEXT, workers INTEGER DEFAULT 1, checklist TEXT,
        status TEXT NOT NULL DEFAULT '신청',
        safety_by INTEGER REFERENCES users(id), safety_comment TEXT, safety_at TEXT,
        approved_by INTEGER REFERENCES users(id), approve_comment TEXT, approved_at TEXT,
        started_at TEXT, ended_at TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, permit_id INTEGER REFERENCES permits(id),
        user_id INTEGER, action TEXT, note TEXT, at TEXT);
    """)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(con)
    con.commit()
    con.close()


def log(con, pid, uid, action, note=""):
    con.execute("INSERT INTO events(permit_id,user_id,action,note,at) VALUES(?,?,?,?,?)", (pid, uid, action, note, now()))


def seed(con):
    users = [
        (1, "김철수", "foreman", "철골팀"), (2, "박영호", "foreman", "배관팀"), (3, "최민석", "foreman", "설비팀"),
        (4, "이안전", "safety", "안전관리팀"), (5, "정책임", "manager", "현장소장"),
    ]
    con.executemany("INSERT INTO users VALUES(?,?,?,?)", users)
    zones = ["A동 지상 3층", "A동 옥상", "B동 지하 1층", "B동 지하 정화조", "C동 외부 비계", "주차장 램프"]
    con.executemany("INSERT INTO zones(name) VALUES(?)", [(z,) for z in zones])
    today = date.today()
    t, y, tm = today.isoformat(), (today - timedelta(days=1)).isoformat(), (today + timedelta(days=1)).isoformat()
    # (type, zone, foreman, date, st, et, desc, workers, status, safety_by, approved_by, started, ended)
    rows = [
        ("고소", 5, 1, t, "08:00", "12:00", "외부 비계 4~6단 철골 보강 볼트 체결", 4, "작업중", 4, 5, f"{t} 08:10:00", None),
        ("화기", 3, 2, t, "09:00", "15:00", "지하 1층 배관 용접(스테인리스 소방배관)", 2, "승인", 4, 5, None, None),
        ("밀폐", 4, 3, t, "13:00", "16:00", "정화조 내부 슬러지 제거 및 점검", 3, "검토완료", 4, None, None, None),
        ("고소", 2, 1, t, "10:00", "14:00", "옥상 안전난간 설치", 3, "신청", None, None, None, None),
        ("화기", 1, 2, t, "14:00", "17:00", "3층 철골 보 절단 작업", 2, "신청", None, None, None, None),
        ("고소", 1, 3, t, "07:30", "10:00", "3층 천장 덕트 행거 설치", 2, "종료", 4, 5, f"{t} 07:40:00", f"{t} 09:50:00"),
        ("화기", 6, 2, t, "11:00", "13:00", "램프 구간 방수 토치 작업", 2, "반려", 4, None, None, None),
        ("고소", 5, 1, tm, "08:00", "17:00", "비계 해체 준비", 5, "승인", 4, 5, None, None),
        ("밀폐", 4, 3, y, "09:00", "12:00", "정화조 가스 측정 및 환기", 2, "종료", 4, 5, f"{y} 09:05:00", f"{y} 11:40:00"),
    ]
    for r in rows:
        ty, z, f, d, st, et, desc, w, status, sb, ab, sa, ea = r
        cl = json.dumps({i: True for i in TYPES[ty]}, ensure_ascii=False)
        sc = "점검 이상 없음" if sb else None
        if status == "반려":
            sc = "인근 방수 자재(인화성) 보관 중. 제거 후 재신청 바람"
        cur = con.execute(
            """INSERT INTO permits(type,zone_id,foreman_id,work_date,start_time,end_time,description,workers,checklist,
               status,safety_by,safety_comment,safety_at,approved_by,approve_comment,approved_at,started_at,ended_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ty, z, f, d, st, et, desc, w, cl, status, sb, sc, f"{d} 07:00:00" if sb else None,
             ab, "승인" if ab else None, f"{d} 07:20:00" if ab else None, sa, ea, f"{d} 06:30:00"))
        pid = cur.lastrowid
        log(con, pid, f, "신청")
        if sb:
            log(con, pid, sb, "반려" if status == "반려" else "안전검토", sc or "")
        if ab:
            log(con, pid, ab, "승인")
        if sa:
            log(con, pid, f, "작업 시작")
        if ea:
            log(con, pid, f, "작업 종료")


# ---------- 인증 ----------
def current_user(authorization: str = Header(default="")):
    uid = SESSIONS.get(authorization.replace("Bearer ", ""))
    if not uid:
        raise HTTPException(401, "로그인이 필요합니다")
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    con.close()
    if not u:
        raise HTTPException(401, "로그인이 필요합니다")
    return dict(u)


def need(user, *roles):
    if user["role"] not in roles:
        raise HTTPException(403, "이 작업을 할 권한이 없습니다")


QUERY = """SELECT p.*, z.name AS zone, f.name AS foreman, f.team AS team,
    s.name AS safety_name, a.name AS approver_name
    FROM permits p JOIN zones z ON z.id=p.zone_id JOIN users f ON f.id=p.foreman_id
    LEFT JOIN users s ON s.id=p.safety_by LEFT JOIN users a ON a.id=p.approved_by"""


def row(r):
    d = dict(r)
    d["checklist"] = json.loads(d["checklist"] or "{}")
    return d


def get_permit(con, pid):
    r = con.execute(QUERY + " WHERE p.id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "허가서를 찾을 수 없습니다")
    return r


# ---------- API ----------
class LoginIn(BaseModel):
    user_id: int


class PermitIn(BaseModel):
    type: str
    zone_id: int
    work_date: str
    start_time: str
    end_time: str
    description: str
    workers: int = 1
    checklist: dict[str, bool]


class CommentIn(BaseModel):
    comment: str = ""


@app.get("/api/users")
def users():
    con = db()
    r = [dict(x) for x in con.execute("SELECT * FROM users ORDER BY id")]
    con.close()
    return r


@app.post("/api/login")
def login(body: LoginIn):
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (body.user_id,)).fetchone()
    con.close()
    if not u:
        raise HTTPException(404, "사용자 없음")
    token = secrets.token_hex(16)
    SESSIONS[token] = u["id"]
    return {"token": token, "user": dict(u)}


@app.get("/api/meta")
def meta(user=Depends(current_user)):
    con = db()
    zones = [dict(x) for x in con.execute("SELECT * FROM zones ORDER BY id")]
    con.close()
    return {"types": TYPES, "zones": zones, "statuses": STATUSES, "today": date.today().isoformat()}


@app.get("/api/permits")
def list_permits(user=Depends(current_user)):
    """작업반장: 본인 허가서만. 안전/책임자: 전체."""
    con = db()
    sql, args = QUERY, ()
    if user["role"] == "foreman":
        sql += " WHERE p.foreman_id=?"
        args = (user["id"],)
    rows = [row(r) for r in con.execute(sql + " ORDER BY p.work_date DESC, p.start_time, p.id", args)]
    con.close()
    return rows


@app.get("/api/permits/{pid}")
def one(pid: int, user=Depends(current_user)):
    con = db()
    p = row(get_permit(con, pid))
    if user["role"] == "foreman" and p["foreman_id"] != user["id"]:
        raise HTTPException(403, "본인 허가서만 볼 수 있습니다")
    p["events"] = [dict(e) for e in con.execute(
        "SELECT e.*, u.name AS user FROM events e LEFT JOIN users u ON u.id=e.user_id WHERE permit_id=? ORDER BY e.id", (pid,))]
    con.close()
    return p


@app.post("/api/permits")
def create(body: PermitIn, user=Depends(current_user)):
    need(user, "foreman")
    if body.type not in TYPES:
        raise HTTPException(400, "작업 종류는 고소·화기·밀폐 중 하나여야 합니다")
    try:
        d = date.fromisoformat(body.work_date)
    except ValueError:
        raise HTTPException(400, "작업일 형식이 올바르지 않습니다")
    if d < date.today():
        raise HTTPException(400, "지난 날짜로는 신청할 수 없습니다")
    if not body.description.strip():
        raise HTTPException(400, "작업 내용을 입력하세요")
    if body.start_time >= body.end_time:
        raise HTTPException(400, "종료 시간은 시작 시간보다 늦어야 합니다")
    if body.workers < 1:
        raise HTTPException(400, "작업 인원은 1명 이상이어야 합니다")
    missing = [i for i in TYPES[body.type] if not body.checklist.get(i)]
    if missing:
        raise HTTPException(400, "안전 조치 체크리스트를 모두 확인해야 합니다: " + ", ".join(missing))
    con = db()
    if not con.execute("SELECT 1 FROM zones WHERE id=?", (body.zone_id,)).fetchone():
        raise HTTPException(400, "구역이 올바르지 않습니다")
    cl = json.dumps({i: True for i in TYPES[body.type]}, ensure_ascii=False)
    cur = con.execute(
        """INSERT INTO permits(type,zone_id,foreman_id,work_date,start_time,end_time,description,workers,checklist,status,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,'신청',?)""",
        (body.type, body.zone_id, user["id"], body.work_date, body.start_time, body.end_time,
         body.description.strip(), body.workers, cl, now()))
    log(con, cur.lastrowid, user["id"], "신청")
    con.commit()
    con.close()
    return {"id": cur.lastrowid}


def transition(pid, user, roles, allowed_from, new_status, action, comment="", sets=None, owner_only=False):
    need(user, *roles)
    con = db()
    p = get_permit(con, pid)
    if owner_only and p["foreman_id"] != user["id"]:
        raise HTTPException(403, "본인 허가서만 처리할 수 있습니다")
    if p["status"] not in allowed_from:
        raise HTTPException(409, f"현재 상태({p['status']})에서는 '{action}' 할 수 없습니다")
    return con, p


@app.post("/api/permits/{pid}/review")
def review(pid: int, body: CommentIn, user=Depends(current_user)):
    con, p = transition(pid, user, ["safety"], ["신청"], "검토완료", "안전검토")
    con.execute("UPDATE permits SET status='검토완료', safety_by=?, safety_comment=?, safety_at=? WHERE id=?",
                (user["id"], body.comment, now(), pid))
    log(con, pid, user["id"], "안전검토", body.comment)
    con.commit(); con.close()
    return {"ok": True}


@app.post("/api/permits/{pid}/approve")
def approve(pid: int, body: CommentIn, user=Depends(current_user)):
    con, p = transition(pid, user, ["manager"], ["검토완료"], "승인", "승인")  # 안전 검토 없이는 승인 불가
    con.execute("UPDATE permits SET status='승인', approved_by=?, approve_comment=?, approved_at=? WHERE id=?",
                (user["id"], body.comment, now(), pid))
    log(con, pid, user["id"], "승인", body.comment)
    con.commit(); con.close()
    return {"ok": True}


@app.post("/api/permits/{pid}/reject")
def reject(pid: int, body: CommentIn, user=Depends(current_user)):
    if not body.comment.strip():
        raise HTTPException(400, "반려 사유를 입력하세요")
    con, p = transition(pid, user, ["safety", "manager"], ["신청", "검토완료"] if user["role"] == "manager" else ["신청"], "반려", "반려")
    if user["role"] == "safety":
        con.execute("UPDATE permits SET status='반려', safety_by=?, safety_comment=?, safety_at=? WHERE id=?",
                    (user["id"], body.comment, now(), pid))
    else:
        con.execute("UPDATE permits SET status='반려', approved_by=?, approve_comment=?, approved_at=? WHERE id=?",
                    (user["id"], body.comment, now(), pid))
    log(con, pid, user["id"], "반려", body.comment)
    con.commit(); con.close()
    return {"ok": True}


@app.post("/api/permits/{pid}/start")
def start(pid: int, user=Depends(current_user)):
    con, p = transition(pid, user, ["foreman"], ["승인"], "작업중", "작업 시작", owner_only=True)
    if p["work_date"] != date.today().isoformat():
        raise HTTPException(409, f"허가된 작업일({p['work_date']})에만 작업을 시작할 수 있습니다")
    # 같은 구역에서 이미 같은 종류의 작업이 진행 중이면 중복 시작 방지
    busy = con.execute("SELECT 1 FROM permits WHERE zone_id=? AND type=? AND status='작업중' AND id<>?",
                       (p["zone_id"], p["type"], pid)).fetchone()
    if busy:
        raise HTTPException(409, "같은 구역에서 동일 종류의 작업이 이미 진행 중입니다")
    con.execute("UPDATE permits SET status='작업중', started_at=? WHERE id=?", (now(), pid))
    log(con, pid, user["id"], "작업 시작")
    con.commit(); con.close()
    return {"ok": True}


@app.post("/api/permits/{pid}/finish")
def finish(pid: int, user=Depends(current_user)):
    con, p = transition(pid, user, ["foreman"], ["작업중"], "종료", "작업 종료", owner_only=True)
    con.execute("UPDATE permits SET status='종료', ended_at=? WHERE id=?", (now(), pid))
    log(con, pid, user["id"], "작업 종료")
    con.commit(); con.close()
    return {"ok": True}


@app.post("/api/permits/{pid}/cancel")
def cancel(pid: int, user=Depends(current_user)):
    con, p = transition(pid, user, ["foreman"], ["신청", "검토완료", "승인"], "취소", "취소", owner_only=True)
    con.execute("UPDATE permits SET status='취소' WHERE id=?", (pid,))
    log(con, pid, user["id"], "취소")
    con.commit(); con.close()
    return {"ok": True}


@app.get("/api/board")
def board(user=Depends(current_user)):
    """오늘 구역별 허가 현황판 (안전담당·현장책임자)"""
    need(user, "safety", "manager")
    today = date.today().isoformat()
    con = db()
    zones = [dict(z) for z in con.execute("SELECT * FROM zones ORDER BY id")]
    rows = [row(r) for r in con.execute(QUERY + " WHERE p.work_date=? ORDER BY p.start_time, p.id", (today,))]
    con.close()
    for z in zones:
        z["permits"] = [r for r in rows if r["zone_id"] == z["id"]]
    summary = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return {"date": today, "zones": zones, "summary": summary, "total": len(rows)}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 9650)))
