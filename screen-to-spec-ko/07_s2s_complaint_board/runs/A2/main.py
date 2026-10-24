"""푸른구청 민원 접수 · 처리 현황판 (FastAPI + SQLite)"""
import random
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "complaints.db"
FMT = "%Y-%m-%d %H:%M:%S"
STATUSES = ["received", "assigned", "processing", "closed"]
STATUS_LABEL = {"received": "접수", "assigned": "배정", "processing": "처리", "closed": "종결"}


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now_s(dt=None):
    return (dt or datetime.now()).strftime(FMT)


SCHEMA = """
CREATE TABLE IF NOT EXISTS staff(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept TEXT NOT NULL, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS complaints(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  no TEXT UNIQUE, title TEXT NOT NULL, content TEXT NOT NULL,
  category TEXT NOT NULL, applicant TEXT NOT NULL, contact TEXT DEFAULT '',
  priority TEXT NOT NULL DEFAULT 'normal',
  status TEXT NOT NULL DEFAULT 'received',
  assignee_id INTEGER REFERENCES staff(id),
  received_at TEXT NOT NULL, due_at TEXT NOT NULL,
  answer TEXT, answered_at TEXT, closed_at TEXT);
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  complaint_id INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
  at TEXT NOT NULL, text TEXT NOT NULL);
"""

STAFF = [
    (1, "김도윤", "도로교통과", "주무관"), (2, "이서연", "도로교통과", "팀장"),
    (3, "박지훈", "환경위생과", "주무관"), (4, "최예린", "환경위생과", "주무관"),
    (5, "정민재", "복지정책과", "주무관"), (6, "한소율", "복지정책과", "팀장"),
    (7, "오태현", "건축주택과", "주무관"), (8, "윤하은", "공원녹지과", "주무관"),
]
# 분류 -> 처리 기한(일)
CATEGORIES = {"도로·교통": 7, "환경·위생": 7, "복지": 14, "건축·주택": 14, "공원·녹지": 7, "기타": 14}
CAT_DEPT = {"도로·교통": [1, 2], "환경·위생": [3, 4], "복지": [5, 6], "건축·주택": [7],
            "공원·녹지": [8], "기타": [1, 3, 5]}
SEED = [
    ("도로·교통", "푸른로 12길 횡단보도 신호등 고장", "퇴근 시간대 보행 신호가 켜지지 않아 위험합니다."),
    ("도로·교통", "버스정류장 앞 불법 주정차 단속 요청", "정류장 앞 상습 주차로 버스가 진입하지 못합니다."),
    ("도로·교통", "한빛초 앞 도로 포트홀 보수", "등굣길에 지름 30cm가량 포트홀이 생겼습니다."),
    ("도로·교통", "가로등 3개 소등", "푸른아파트 후문 골목 가로등이 일주일째 꺼져 있습니다."),
    ("환경·위생", "음식물 쓰레기 수거 지연", "3일째 수거가 되지 않아 악취가 심합니다."),
    ("환경·위생", "공사장 소음·분진 민원", "새벽 6시부터 장비 소음이 발생합니다."),
    ("환경·위생", "하천변 무단 투기 폐기물 처리", "대형 폐가구가 방치되어 있습니다."),
    ("환경·위생", "상가 앞 흡연 구역 지정 요청", "간접흡연 피해가 큽니다."),
    ("복지", "독거노인 안부 확인 요청", "옆집 어르신이 며칠째 보이지 않습니다."),
    ("복지", "긴급복지 지원 대상 문의", "실직 후 생계가 어려워 지원 가능 여부를 알고 싶습니다."),
    ("복지", "장애인 콜택시 배차 지연", "평균 대기 시간이 1시간을 넘습니다."),
    ("복지", "어린이집 보육료 지원 신청 절차", "다자녀 가구 추가 지원 기준을 알려주세요."),
    ("건축·주택", "불법 증축 의심 건물 확인", "옥상에 무단 증축 구조물이 보입니다."),
    ("건축·주택", "노후 담장 붕괴 위험", "비가 오면 담장이 기울어집니다."),
    ("건축·주택", "주택 공동 수도 누수 신고", "지하 계량기 부근에서 물이 샙니다."),
    ("공원·녹지", "푸른공원 벤치 파손", "벤치 판자가 부러져 어린이가 다칠 수 있습니다."),
    ("공원·녹지", "가로수 가지치기 요청", "간판과 신호등을 가리고 있습니다."),
    ("공원·녹지", "놀이터 모래 교체 요청", "고양이 배설물이 많습니다."),
    ("기타", "민원 서류 발급 대기 시간 개선", "점심시간 창구가 너무 혼잡합니다."),
    ("기타", "구청 주차장 이용 문의", "방문 민원인 무료 주차 시간을 알고 싶습니다."),
    ("도로·교통", "자전거도로 파손 구간 정비", "블록이 솟아올라 넘어질 뻔했습니다."),
    ("환경·위생", "길고양이 급식소 관련 갈등 중재", "이웃 간 다툼이 있습니다."),
    ("복지", "경로당 프로그램 신설 요청", "스마트폰 교육반을 열어주세요."),
    ("건축·주택", "빈집 정비 요청", "잡초와 쓰레기가 쌓여 있습니다."),
]
NAMES = ["김하준", "이서아", "박민서", "최지우", "정유진", "강도현", "조수빈", "윤재원", "장예은", "임현우"]
ANSWERS = ["현장 확인 후 조치를 완료하였습니다. 이용에 불편을 드려 죄송합니다.",
           "관련 부서와 협의하여 시정 조치하였으며, 재발 방지를 위해 정기 점검하겠습니다.",
           "문의하신 내용은 관련 규정에 따라 안내드립니다. 추가 문의는 대표번호로 연락 바랍니다."]


def log(con, cid, text, at=None):
    con.execute("INSERT INTO history(complaint_id,at,text) VALUES(?,?,?)", (cid, now_s(at), text))


def seed(con):
    rnd = random.Random(77)
    con.executemany("INSERT INTO staff VALUES(?,?,?,?)", STAFF)
    now = datetime.now()
    plan = (["received"] * 5 + ["assigned"] * 5 + ["processing"] * 6 + ["closed"] * 8)
    rnd.shuffle(plan)
    for i, (cat, title, content) in enumerate(SEED):
        st = plan[i]
        age = rnd.choice([1, 2, 3, 5, 6, 8, 9, 10, 12, 15]) if st != "closed" else rnd.randint(4, 20)
        recv = now - timedelta(days=age, hours=rnd.randint(0, 8), minutes=rnd.randint(0, 59))
        due = recv + timedelta(days=CATEGORIES[cat])
        prio = "urgent" if (cat == "복지" and "독거" in title) or rnd.random() < 0.15 else "normal"
        assignee = rnd.choice(CAT_DEPT[cat]) if st != "received" else None
        answer = answered = closed = None
        if st == "closed":
            closed_dt = min(now, recv + timedelta(days=rnd.randint(1, CATEGORIES[cat] + 3)))
            answer, answered, closed = rnd.choice(ANSWERS), now_s(closed_dt), now_s(closed_dt)
        cur = con.execute(
            """INSERT INTO complaints(no,title,content,category,applicant,contact,priority,status,
               assignee_id,received_at,due_at,answer,answered_at,closed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"2026-{i + 1:04d}", title, content, cat, rnd.choice(NAMES),
             f"010-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}",
             prio, st, assignee, now_s(recv), now_s(due), answer, answered, closed))
        cid = cur.lastrowid
        log(con, cid, "민원 접수", recv)
        if assignee:
            log(con, cid, f"담당자 배정: {next(s[1] for s in STAFF if s[0] == assignee)}", recv + timedelta(hours=3))
        if st in ("processing", "closed"):
            log(con, cid, "처리 시작", recv + timedelta(hours=20))
        if st == "closed":
            log(con, cid, "답변 등록", closed_dt)
            log(con, cid, "종결 처리", closed_dt)


@asynccontextmanager
async def lifespan(_app):
    with db() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM complaints").fetchone()[0] == 0:
            seed(con)
    yield


app = FastAPI(title="푸른구청 민원 현황판", lifespan=lifespan)


def row_out(r):
    d = dict(r)
    due = datetime.strptime(d["due_at"], FMT)
    if d["status"] == "closed":
        d["overdue"], d["remaining_hours"] = False, None
        d["closed_late"] = datetime.strptime(d["closed_at"], FMT) > due
    else:
        secs = (due - datetime.now()).total_seconds()
        d["overdue"] = secs < 0
        d["remaining_hours"] = round(secs / 3600, 1)
        d["closed_late"] = False
    return d


BASE_SQL = """SELECT c.*, s.name AS assignee_name, s.dept AS assignee_dept
              FROM complaints c LEFT JOIN staff s ON s.id=c.assignee_id"""


def get_one(con, cid):
    r = con.execute(BASE_SQL + " WHERE c.id=?", (cid,)).fetchone()
    if not r:
        raise HTTPException(404, "민원을 찾을 수 없습니다.")
    return r


@app.get("/api/meta")
def meta():
    return {"categories": CATEGORIES, "statuses": STATUSES, "labels": STATUS_LABEL}


@app.get("/api/staff")
def staff():
    with db() as con:
        rows = con.execute(
            """SELECT s.*, COUNT(c.id) AS open_count FROM staff s
               LEFT JOIN complaints c ON c.assignee_id=s.id AND c.status!='closed'
               GROUP BY s.id ORDER BY s.dept, s.id""").fetchall()
        return [dict(r) for r in rows]


@app.get("/api/complaints")
def list_complaints():
    with db() as con:
        return [row_out(r) for r in con.execute(BASE_SQL + " ORDER BY c.due_at")]


@app.get("/api/complaints/{cid}")
def detail(cid: int):
    with db() as con:
        d = row_out(get_one(con, cid))
        d["history"] = [dict(h) for h in con.execute(
            "SELECT at,text FROM history WHERE complaint_id=? ORDER BY id", (cid,))]
        return d


class NewComplaint(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    category: str
    applicant: str = Field(min_length=1, max_length=30)
    contact: str = ""
    priority: str = "normal"


@app.post("/api/complaints", status_code=201)
def create(body: NewComplaint):
    if body.category not in CATEGORIES:
        raise HTTPException(422, "알 수 없는 분류입니다.")
    if body.priority not in ("normal", "urgent"):
        raise HTTPException(422, "알 수 없는 우선순위입니다.")
    now = datetime.now()
    days = max(3, CATEGORIES[body.category] // 2) if body.priority == "urgent" else CATEGORIES[body.category]
    with db() as con:
        n = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM complaints").fetchone()[0]
        cur = con.execute(
            """INSERT INTO complaints(no,title,content,category,applicant,contact,priority,received_at,due_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (f"2026-{n:04d}", body.title, body.content, body.category, body.applicant, body.contact,
             body.priority, now_s(now), now_s(now + timedelta(days=days))))
        log(con, cur.lastrowid, "민원 접수")
        return row_out(get_one(con, cur.lastrowid))


class Assign(BaseModel):
    staff_id: int


@app.post("/api/complaints/{cid}/assign")
def assign(cid: int, body: Assign):
    with db() as con:
        c = get_one(con, cid)
        if c["status"] == "closed":
            raise HTTPException(409, "종결된 민원은 담당자를 변경할 수 없습니다.")
        s = con.execute("SELECT * FROM staff WHERE id=?", (body.staff_id,)).fetchone()
        if not s:
            raise HTTPException(404, "담당자를 찾을 수 없습니다.")
        new_status = "assigned" if c["status"] == "received" else c["status"]
        con.execute("UPDATE complaints SET assignee_id=?, status=? WHERE id=?", (s["id"], new_status, cid))
        log(con, cid, f"담당자 배정: {s['name']} ({s['dept']})")
        return row_out(get_one(con, cid))


class Answer(BaseModel):
    answer: str = Field(min_length=1, max_length=3000)
    close: bool = False


def _close(con, cid):
    con.execute("UPDATE complaints SET status='closed', closed_at=? WHERE id=?", (now_s(), cid))
    log(con, cid, "종결 처리")


@app.post("/api/complaints/{cid}/answer")
def answer(cid: int, body: Answer):
    with db() as con:
        c = get_one(con, cid)
        if c["status"] == "closed":
            raise HTTPException(409, "이미 종결된 민원입니다.")
        if not c["assignee_id"]:
            raise HTTPException(409, "담당자 배정 후 답변을 등록할 수 있습니다.")
        con.execute("UPDATE complaints SET answer=?, answered_at=?, status='processing' WHERE id=?",
                    (body.answer.strip(), now_s(), cid))
        if c["status"] == "assigned":
            log(con, cid, "처리 시작")
        log(con, cid, "답변 등록" if not c["answer"] else "답변 수정")
        if body.close:
            _close(con, cid)
        return row_out(get_one(con, cid))


class Move(BaseModel):
    status: str


@app.post("/api/complaints/{cid}/status")
def move(cid: int, body: Move):
    """칸반 이동: 한 단계씩 전진만 가능. 배정은 담당자 필요, 종결은 답변 필요."""
    if body.status not in STATUSES:
        raise HTTPException(422, "알 수 없는 상태입니다.")
    with db() as con:
        c = get_one(con, cid)
        cur, new = c["status"], body.status
        if cur == new:
            return row_out(c)
        if cur == "closed":
            raise HTTPException(409, "종결된 민원은 이동할 수 없습니다.")
        ci, ni = STATUSES.index(cur), STATUSES.index(new)
        if ni < ci:
            raise HTTPException(409, "이전 단계로 되돌릴 수 없습니다.")
        if ni - ci > 1:
            raise HTTPException(409, f"'{STATUS_LABEL[STATUSES[ci + 1]]}' 단계를 먼저 거쳐야 합니다.")
        if new == "assigned":
            raise HTTPException(409, "담당자를 선택해 배정해 주세요.")
        if new == "closed":
            if not c["answer"]:
                raise HTTPException(409, "답변을 등록한 뒤 종결할 수 있습니다.")
            _close(con, cid)
        else:  # processing
            if not c["assignee_id"]:
                raise HTTPException(409, "담당자 배정이 필요합니다.")
            con.execute("UPDATE complaints SET status='processing' WHERE id=?", (cid,))
            log(con, cid, "처리 시작")
        return row_out(get_one(con, cid))


@app.get("/api/stats")
def stats():
    with db() as con:
        rows = [row_out(r) for r in con.execute(BASE_SQL)]
    by = {s: 0 for s in STATUSES}
    for r in rows:
        by[r["status"]] += 1
    open_ = [r for r in rows if r["status"] != "closed"]
    closed = [r for r in rows if r["status"] == "closed"]
    return {
        "total": len(rows), "by_status": by,
        "overdue": sum(r["overdue"] for r in open_),
        "due_soon": sum(1 for r in open_ if not r["overdue"] and r["remaining_hours"] <= 48),
        "on_time_rate": round(100 * sum(not r["closed_late"] for r in closed) / len(closed)) if closed else None,
    }


@app.post("/api/reset")
def reset():
    """가상 데이터로 초기화"""
    with db() as con:
        con.executescript("DROP TABLE IF EXISTS history; DROP TABLE IF EXISTS complaints; DROP TABLE IF EXISTS staff;")
        con.executescript(SCHEMA)
        seed(con)
    return {"ok": True}


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
