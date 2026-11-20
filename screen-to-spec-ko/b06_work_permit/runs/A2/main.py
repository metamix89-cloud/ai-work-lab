import os, sqlite3
from datetime import date, datetime, timedelta
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "permits.db")
TYPES = {
    "고소": ["안전대 착용 및 고리 체결 확인", "작업발판·안전난간 상태 확인", "하부 출입통제 구역 설정"],
    "화기": ["소화기 2대 이상 비치", "주변 가연물 제거·방염포 설치", "화재감시자 배치"],
    "밀폐": ["산소·유해가스 농도 측정", "환기 설비 가동", "외부 감시인 배치·비상연락 체계"],
}
ZONES = ["A동 지하1층", "A동 옥상", "B동 3층 외부비계", "B동 기계실", "C동 맨홀·집수정", "야적장"]

app = FastAPI(title="위험 작업 허가서")


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, role TEXT, team TEXT);
    CREATE TABLE IF NOT EXISTS permits(
      id INTEGER PRIMARY KEY, type TEXT, zone TEXT, description TEXT, work_date TEXT,
      start_time TEXT, end_time TEXT, workers INTEGER, foreman_id INTEGER,
      status TEXT, o2 REAL, review_note TEXT, reviewer_id INTEGER, reviewed_at TEXT,
      approver_id INTEGER, decided_at TEXT, decision_note TEXT,
      started_at TEXT, ended_at TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, permit_id INTEGER, at TEXT, who TEXT, action TEXT);
    """)
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        c.executemany("INSERT INTO users(name,role,team) VALUES(?,?,?)", [
            ("김철수", "foreman", "형틀팀"), ("박영호", "foreman", "설비팀"), ("이민재", "foreman", "용접팀"),
            ("최안전", "safety", "안전관리팀"), ("정현장", "manager", "현장소장")])
        t = date.today().isoformat()
        y = (date.today() - timedelta(days=1)).isoformat()
        tm = (date.today() + timedelta(days=1)).isoformat()
        # type, zone, desc, date, st, et, n, foreman, status, o2, review_note, reviewed, decided, decision_note, started, ended
        S = [
            ("고소", "B동 3층 외부비계", "외벽 거푸집 해체", t, "08:00", "12:00", 5, 1, "in_progress", None, "안전대 확인 완료", 1, 1, "승인", 1, 0),
            ("고소", "A동 옥상", "옥상 방수 작업", t, "13:00", "17:00", 3, 1, "approved", None, "난간 설치 확인", 1, 1, "승인", 0, 0),
            ("화기", "B동 기계실", "배관 용접", t, "09:00", "16:00", 2, 3, "in_progress", None, "방염포·감시자 확인", 1, 1, "승인", 1, 0),
            ("화기", "A동 지하1층", "철골 절단", t, "10:00", "15:00", 2, 3, "submitted", None, None, 0, 0, None, 0, 0),
            ("밀폐", "C동 맨홀·집수정", "집수정 청소", t, "09:00", "11:30", 3, 2, "reviewed", 20.8, "산소 20.8% 적정, 환기 가동", 1, 0, None, 0, 0),
            ("밀폐", "C동 맨홀·집수정", "맨홀 배관 점검", t, "14:00", "16:00", 2, 2, "rejected", 17.9, "산소 17.9% 기준 미달 - 재측정 필요", 1, 0, None, 0, 0),
            ("고소", "야적장", "자재 인양 보조", t, "07:30", "09:00", 4, 1, "completed", None, "확인 완료", 1, 1, "승인", 1, 1),
            ("고소", "A동 옥상", "파라펫 보수", tm, "08:00", "12:00", 3, 1, "submitted", None, None, 0, 0, None, 0, 0),
            ("화기", "B동 기계실", "덕트 용접", y, "09:00", "12:00", 2, 3, "completed", None, "확인", 1, 1, "승인", 1, 1),
        ]
        for i, s in enumerate(S):
            ty, zo, de, dt, st, et, n, f, status, o2, rn, rev, dec, dn, started, ended = s
            ts = f"{dt} 06:{10 + i:02d}:00"
            rid = 4 if rev else None
            aid = 5 if dec else None
            c.execute("""INSERT INTO permits(type,zone,description,work_date,start_time,end_time,workers,foreman_id,status,o2,
              review_note,reviewer_id,reviewed_at,approver_id,decided_at,decision_note,started_at,ended_at,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (ty, zo, de, dt, st, et, n, f, status, o2, rn, rid, ts if rev else None, aid, ts if dec else None, dn,
                       f"{dt} {st}:00" if started else None, f"{dt} {et}:00" if ended else None, ts))
            c.execute("INSERT INTO logs(permit_id,at,who,action) VALUES(?,?,?,?)", (i + 1, ts, "시드 데이터", "신청 후 현재 상태: " + status))
    c.commit()
    c.close()


init()


def user(uid):
    if not uid:
        raise HTTPException(401, "사용자를 선택하세요")
    c = db()
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    if not u:
        raise HTTPException(401, "알 수 없는 사용자")
    return u


def need(u, role):
    if u["role"] != role:
        raise HTTPException(403, "권한이 없습니다")


QUERY = """SELECT p.*, f.name foreman_name, f.team foreman_team, r.name reviewer_name, a.name approver_name
  FROM permits p LEFT JOIN users f ON f.id=p.foreman_id LEFT JOIN users r ON r.id=p.reviewer_id
  LEFT JOIN users a ON a.id=p.approver_id """


def get(c, pid):
    p = c.execute(QUERY + "WHERE p.id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "허가서가 없습니다")
    return p


def log(c, pid, u, action):
    c.execute("INSERT INTO logs(permit_id,at,who,action) VALUES(?,?,?,?)", (pid, now(), f"{u['name']}({u['team']})", action))


@app.get("/api/meta")
def meta():
    return {"types": TYPES, "zones": ZONES}


@app.get("/api/users")
def users():
    c = db()
    r = [dict(x) for x in c.execute("SELECT * FROM users")]
    c.close()
    return r


@app.get("/api/permits")
def permits(x_user_id: int = Header(None)):
    u = user(x_user_id)
    c = db()
    if u["role"] == "foreman":
        rows = c.execute(QUERY + "WHERE p.foreman_id=? ORDER BY p.work_date DESC, p.start_time, p.id", (u["id"],))
    else:
        rows = c.execute(QUERY + "ORDER BY p.work_date DESC, p.start_time, p.id")
    r = [dict(x) for x in rows]
    c.close()
    return r


@app.get("/api/permits/{pid}")
def detail(pid: int, x_user_id: int = Header(None)):
    u = user(x_user_id)
    c = db()
    p = get(c, pid)
    if u["role"] == "foreman" and p["foreman_id"] != u["id"]:
        raise HTTPException(403, "본인 허가서만 볼 수 있습니다")
    out = dict(p)
    out["logs"] = [dict(x) for x in c.execute("SELECT * FROM logs WHERE permit_id=? ORDER BY id", (pid,))]
    out["checklist"] = TYPES[p["type"]]
    c.close()
    return out


class New(BaseModel):
    type: str
    zone: str
    description: str
    work_date: str
    start_time: str
    end_time: str
    workers: int


@app.post("/api/permits")
def create(b: New, x_user_id: int = Header(None)):
    u = user(x_user_id)
    need(u, "foreman")
    if b.type not in TYPES:
        raise HTTPException(400, "작업 종류가 올바르지 않습니다")
    if b.zone not in ZONES:
        raise HTTPException(400, "구역이 올바르지 않습니다")
    if not b.description.strip():
        raise HTTPException(400, "작업 내용을 입력하세요")
    if b.workers < 1:
        raise HTTPException(400, "작업 인원은 1명 이상이어야 합니다")
    try:
        d = date.fromisoformat(b.work_date)
    except ValueError:
        raise HTTPException(400, "날짜 형식 오류")
    if d < date.today():
        raise HTTPException(400, "과거 날짜로는 신청할 수 없습니다")
    if b.start_time >= b.end_time:
        raise HTTPException(400, "종료 시간이 시작 시간보다 늦어야 합니다")
    c = db()
    cur = c.execute("""INSERT INTO permits(type,zone,description,work_date,start_time,end_time,workers,foreman_id,status,created_at)
      VALUES(?,?,?,?,?,?,?,?,'submitted',?)""",
                    (b.type, b.zone, b.description.strip(), b.work_date, b.start_time, b.end_time, b.workers, u["id"], now()))
    log(c, cur.lastrowid, u, "신청")
    c.commit()
    c.close()
    return {"id": cur.lastrowid}


class ReviewIn(BaseModel):
    ok: bool
    note: str = ""
    checked: list[int] = []
    o2: float | None = None


@app.post("/api/permits/{pid}/review")
def review(pid: int, b: ReviewIn, x_user_id: int = Header(None)):
    u = user(x_user_id)
    need(u, "safety")
    c = db()
    p = get(c, pid)
    if p["status"] != "submitted":
        raise HTTPException(409, "검토 대기 상태가 아닙니다")
    items = TYPES[p["type"]]
    if b.ok:
        if sorted(set(b.checked)) != list(range(len(items))):
            raise HTTPException(400, "안전조치 항목을 모두 확인해야 적합 처리할 수 있습니다")
        if p["type"] == "밀폐":
            if b.o2 is None:
                raise HTTPException(400, "밀폐 작업은 산소 농도 측정값이 필요합니다")
            if not (19.5 <= b.o2 <= 23.5):
                raise HTTPException(400, f"산소 농도 {b.o2}% 는 적정 범위(19.5~23.5%)를 벗어납니다. 반려하세요")
    elif not b.note.strip():
        raise HTTPException(400, "반려 사유를 입력하세요")
    st = "reviewed" if b.ok else "rejected"
    c.execute("UPDATE permits SET status=?,o2=?,review_note=?,reviewer_id=?,reviewed_at=? WHERE id=?",
              (st, b.o2, b.note.strip(), u["id"], now(), pid))
    log(c, pid, u, "안전 검토 적합" if b.ok else "안전 검토 반려: " + b.note)
    c.commit()
    c.close()
    return {"status": st}


class Decide(BaseModel):
    ok: bool
    note: str = ""


@app.post("/api/permits/{pid}/decide")
def decide(pid: int, b: Decide, x_user_id: int = Header(None)):
    u = user(x_user_id)
    need(u, "manager")
    c = db()
    p = get(c, pid)
    if p["status"] != "reviewed":
        raise HTTPException(409, "안전 검토를 통과한 허가서만 승인할 수 있습니다")
    if not b.ok and not b.note.strip():
        raise HTTPException(400, "반려 사유를 입력하세요")
    st = "approved" if b.ok else "rejected"
    c.execute("UPDATE permits SET status=?,approver_id=?,decided_at=?,decision_note=? WHERE id=?",
              (st, u["id"], now(), b.note.strip(), pid))
    log(c, pid, u, "승인" if b.ok else "반려: " + b.note)
    c.commit()
    c.close()
    return {"status": st}


def own(u, p):
    if u["role"] != "foreman" or p["foreman_id"] != u["id"]:
        raise HTTPException(403, "본인 허가서만 조작할 수 있습니다")


@app.post("/api/permits/{pid}/start")
def start(pid: int, x_user_id: int = Header(None)):
    u = user(x_user_id)
    c = db()
    p = get(c, pid)
    own(u, p)
    if p["status"] != "approved":
        raise HTTPException(409, "승인된 허가서만 작업을 시작할 수 있습니다")
    if p["work_date"] != date.today().isoformat():
        raise HTTPException(409, f"허가된 작업일({p['work_date']})이 아닙니다")
    busy = c.execute("SELECT id FROM permits WHERE zone=? AND status='in_progress' AND type='밀폐' AND id<>?",
                     (p["zone"], pid)).fetchone()
    if busy:
        raise HTTPException(409, "같은 구역에서 밀폐 작업이 진행 중입니다")
    c.execute("UPDATE permits SET status='in_progress',started_at=? WHERE id=?", (now(), pid))
    log(c, pid, u, "작업 시작")
    c.commit()
    c.close()
    return {"status": "in_progress"}


@app.post("/api/permits/{pid}/finish")
def finish(pid: int, x_user_id: int = Header(None)):
    u = user(x_user_id)
    c = db()
    p = get(c, pid)
    own(u, p)
    if p["status"] != "in_progress":
        raise HTTPException(409, "진행 중인 작업만 종료할 수 있습니다")
    c.execute("UPDATE permits SET status='completed',ended_at=? WHERE id=?", (now(), pid))
    log(c, pid, u, "작업 종료")
    c.commit()
    c.close()
    return {"status": "completed"}


@app.get("/api/board")
def board(x_user_id: int = Header(None)):
    u = user(x_user_id)
    if u["role"] == "foreman":
        raise HTTPException(403, "현황판은 안전 담당·현장 책임자용입니다")
    c = db()
    t = date.today().isoformat()
    rows = [dict(x) for x in c.execute(QUERY + "WHERE p.work_date=? ORDER BY p.start_time", (t,))]
    c.close()
    zones = {z: [] for z in ZONES}
    cnt = {}
    for r in rows:
        zones.setdefault(r["zone"], []).append(r)
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    return {"date": t, "counts": cnt, "zones": [{"zone": z, "permits": v} for z, v in zones.items()]}


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 9630)))
