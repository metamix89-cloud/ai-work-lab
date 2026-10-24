"""푸른구청 민원 접수 · 처리 현황판 (FastAPI + SQLite)"""
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "complaints.db"
STATUSES = ["접수", "배정", "처리", "종결"]
CATEGORIES = ["도로·교통", "환경·청소", "복지", "주택·건축", "안전·재난", "문화·체육", "세무·행정"]
PRIORITIES = ["보통", "높음", "긴급"]
DUE_DAYS = {"보통": 7, "높음": 5, "긴급": 2}  # 접수일 기준 처리 기한
FMT = "%Y-%m-%d %H:%M:%S"

app = FastAPI(title="푸른구청 민원 현황판")


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


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
CREATE TABLE IF NOT EXISTS staff (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, dept TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS complaints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_no TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL, content TEXT NOT NULL,
  category TEXT NOT NULL, priority TEXT NOT NULL DEFAULT '보통',
  citizen_name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '접수',
  assignee_id INTEGER REFERENCES staff(id),
  received_at TEXT NOT NULL, due_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS replies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  complaint_id INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
  author TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  complaint_id INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
  message TEXT NOT NULL, created_at TEXT NOT NULL);
"""

STAFF = [
    ("김민준", "건설과"), ("이서연", "건설과"), ("박지호", "청소행정과"),
    ("최유진", "청소행정과"), ("정하늘", "복지정책과"), ("강도윤", "복지정책과"),
    ("조수아", "건축과"), ("윤재원", "안전총괄과"), ("임나은", "문화체육과"),
    ("한지민", "세무과"),
]
CAT_DEPT = {"도로·교통": "건설과", "환경·청소": "청소행정과", "복지": "복지정책과",
            "주택·건축": "건축과", "안전·재난": "안전총괄과", "문화·체육": "문화체육과",
            "세무·행정": "세무과"}

SAMPLES = {
    "도로·교통": [("푸른로 사거리 신호등 고장", "출근 시간대에 신호등이 점멸 상태로 멈춰 있어 사고 위험이 큽니다."),
              ("횡단보도 앞 포트홀 발생", "초등학교 앞 횡단보도 옆에 깊은 파임이 생겨 보행자가 넘어질 뻔했습니다."),
              ("불법 주정차 단속 요청", "상가 앞 이면도로에 상습적으로 불법 주정차 차량이 있어 통행이 어렵습니다.")],
    "환경·청소": [("공원 쓰레기통 넘침", "주말 이후 푸른공원 쓰레기통이 넘쳐 악취가 납니다."),
              ("음식물 쓰레기 수거 지연", "3일째 아파트 단지 음식물 수거가 이뤄지지 않고 있습니다."),
              ("하천변 무단투기 신고", "산책로 하천변에 대형 폐기물이 버려져 있습니다.")],
    "복지": [("긴급복지 지원 문의", "실직 후 생활이 어려워 긴급복지 지원 대상인지 알고 싶습니다."),
           ("독거노인 안부 확인 요청", "옆집 어르신이 며칠째 보이지 않아 확인을 부탁드립니다."),
           ("장애인 콜택시 배차 불만", "배차 대기 시간이 1시간 이상으로 개선이 필요합니다.")],
    "주택·건축": [("옹벽 균열 점검 요청", "빌라 뒤편 옹벽에 금이 가 있어 장마철이 걱정됩니다."),
              ("불법 증축 의심 신고", "인근 건물 옥상에 허가 없는 구조물이 올라가고 있습니다."),
              ("공사장 소음·분진 민원", "신축 공사장 소음이 일요일에도 이어집니다.")],
    "안전·재난": [("가로등 소등 구간 점검", "골목 일대 가로등 3개가 꺼져 야간에 매우 어둡습니다."),
              ("맨홀 뚜껑 덜컹거림", "차량이 지날 때마다 맨홀 뚜껑에서 큰 소리가 납니다."),
              ("빙판길 제설 요청", "경사로가 얼어붙어 낙상 사고 위험이 있습니다.")],
    "문화·체육": [("구립 수영장 강습 신청 오류", "온라인 신청 중 결제 단계에서 계속 오류가 납니다."),
              ("도서관 운영시간 연장 건의", "직장인을 위해 평일 야간 운영을 건의합니다."),
              ("체육공원 조명 불량", "저녁 운동 시 조명이 너무 어둡습니다.")],
    "세무·행정": [("주민세 고지서 이중 부과", "이미 납부했는데 독촉 고지서가 다시 왔습니다."),
              ("전입신고 처리 지연", "신고 후 1주일이 지났는데 처리 완료 문자가 없습니다."),
              ("민원실 대기 시간 불만", "점심시간 대기 인원이 많은데 창구가 줄어 있습니다.")],
}
CITIZENS = ["김영수", "이미영", "박철민", "최은지", "정대현", "한소희", "오세훈", "서지원", "문채원", "배준혁"]
REPLIES = ["접수하신 민원 확인하였으며 현장 점검을 진행하겠습니다.",
           "현장 확인 결과 조치가 필요하여 업체에 시정 요청하였습니다.",
           "요청하신 사항에 대한 조치를 완료하였습니다. 이용에 불편을 드려 죄송합니다."]


def seed(con):
    con.executemany("INSERT INTO staff(name, dept) VALUES (?, ?)", STAFF)
    rnd = random.Random(77)
    base = now()
    n = 0
    plan = ["접수"] * 6 + ["배정"] * 6 + ["처리"] * 7 + ["종결"] * 6
    for st in plan:
        cat = rnd.choice(CATEGORIES)
        title, content = rnd.choice(SAMPLES[cat])
        pri = rnd.choices(PRIORITIES, [6, 3, 1])[0]
        age_h = rnd.randint(6, 24 * 12)
        recv = base - timedelta(hours=age_h)
        due = recv + timedelta(days=DUE_DAYS[pri])
        n += 1
        ticket = f"{recv:%Y%m%d}-{n:03d}"
        assignee = None
        if st != "접수":
            cands = [i + 1 for i, s in enumerate(STAFF) if s[1] == CAT_DEPT[cat]]
            assignee = rnd.choice(cands)
        closed = None
        if st == "종결":
            closed = min(base, recv + timedelta(hours=rnd.randint(12, 24 * 6))).strftime(FMT)
        cur = con.execute(
            "INSERT INTO complaints(ticket_no,title,content,category,priority,citizen_name,phone,"
            "status,assignee_id,received_at,due_at,closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ticket, title, content, cat, pri, rnd.choice(CITIZENS),
             f"010-****-{rnd.randint(1000, 9999)}", st, assignee,
             recv.strftime(FMT), due.strftime(FMT), closed))
        cid = cur.lastrowid
        t = recv
        log = [(t, "민원 접수")]
        if assignee:
            t += timedelta(hours=rnd.randint(1, 5))
            log.append((t, f"담당자 배정: {STAFF[assignee - 1][0]} ({STAFF[assignee - 1][1]})"))
        if st in ("처리", "종결"):
            t += timedelta(hours=rnd.randint(1, 8))
            log.append((t, "상태 변경: 배정 → 처리"))
            t += timedelta(hours=rnd.randint(1, 8))
            con.execute("INSERT INTO replies(complaint_id,author,content,created_at) VALUES (?,?,?,?)",
                        (cid, STAFF[assignee - 1][0], REPLIES[0 if st == "처리" else 2], t.strftime(FMT)))
            log.append((t, "답변 등록"))
        if st == "종결":
            log.append((datetime.strptime(closed, FMT), "상태 변경: 처리 → 종결"))
        con.executemany("INSERT INTO history(complaint_id,message,created_at) VALUES (?,?,?)",
                        [(cid, m, x.strftime(FMT)) for x, m in log])


@app.on_event("startup")
def init():
    with db() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM staff").fetchone()[0] == 0:
            seed(con)


# ---------- helpers ----------
SELECT = """SELECT c.*, s.name AS assignee_name, s.dept AS assignee_dept,
  (SELECT COUNT(*) FROM replies r WHERE r.complaint_id = c.id) AS reply_count
  FROM complaints c LEFT JOIN staff s ON s.id = c.assignee_id"""


def decorate(row) -> dict:
    d = dict(row)
    due = datetime.strptime(d["due_at"], FMT)
    ref = datetime.strptime(d["closed_at"], FMT) if d["closed_at"] else now()
    left = (due - ref).total_seconds() / 3600
    d["hours_left"] = round(left, 1)
    d["overdue"] = left < 0  # 종결 건은 종결 시각 기준(기한 초과 종결 여부)
    d["overdue_open"] = left < 0 and d["status"] != "종결"
    d["due_soon"] = 0 <= left <= 24 and d["status"] != "종결"
    return d


def log(con, cid, msg):
    con.execute("INSERT INTO history(complaint_id,message,created_at) VALUES (?,?,?)",
                (cid, msg, now().strftime(FMT)))


def get_or_404(con, cid):
    row = con.execute(SELECT + " WHERE c.id = ?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "민원을 찾을 수 없습니다.")
    return row


# ---------- models ----------
class NewComplaint(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    content: str = Field(min_length=2, max_length=2000)
    category: str
    priority: str = "보통"
    citizen_name: str = Field(min_length=1, max_length=30)
    phone: str = Field(default="", max_length=30)


class Assign(BaseModel):
    staff_id: int


class StatusChange(BaseModel):
    status: str


class NewReply(BaseModel):
    content: str = Field(min_length=2, max_length=2000)
    author: str | None = None


# ---------- API ----------
@app.get("/api/meta")
def meta():
    with db() as con:
        staff = [dict(r) for r in con.execute("SELECT * FROM staff ORDER BY dept, name")]
    return {"statuses": STATUSES, "categories": CATEGORIES, "priorities": PRIORITIES,
            "cat_dept": CAT_DEPT, "staff": staff}


@app.get("/api/complaints")
def list_complaints():
    with db() as con:
        rows = con.execute(SELECT + " ORDER BY c.due_at").fetchall()
    return [decorate(r) for r in rows]


@app.get("/api/stats")
def stats():
    with db() as con:
        rows = [decorate(r) for r in con.execute(SELECT)]
    return {
        "total": len(rows),
        "by_status": {s: sum(r["status"] == s for r in rows) for s in STATUSES},
        "overdue": sum(r["overdue_open"] for r in rows),
        "due_soon": sum(r["due_soon"] for r in rows),
        "closed_late": sum(r["status"] == "종결" and r["overdue"] for r in rows),
    }


@app.get("/api/complaints/{cid}")
def detail(cid: int):
    with db() as con:
        d = decorate(get_or_404(con, cid))
        d["replies"] = [dict(r) for r in con.execute(
            "SELECT * FROM replies WHERE complaint_id=? ORDER BY id", (cid,))]
        d["history"] = [dict(r) for r in con.execute(
            "SELECT * FROM history WHERE complaint_id=? ORDER BY id", (cid,))]
    return d


@app.post("/api/complaints", status_code=201)
def create(body: NewComplaint):
    if body.category not in CATEGORIES or body.priority not in PRIORITIES:
        raise HTTPException(422, "분류 또는 우선순위가 올바르지 않습니다.")
    t = now()
    with db() as con:
        seq = con.execute("SELECT COUNT(*) FROM complaints").fetchone()[0] + 1
        ticket = f"{t:%Y%m%d}-{seq:03d}"
        cur = con.execute(
            "INSERT INTO complaints(ticket_no,title,content,category,priority,citizen_name,phone,"
            "received_at,due_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (ticket, body.title.strip(), body.content.strip(), body.category, body.priority,
             body.citizen_name.strip(), body.phone.strip(), t.strftime(FMT),
             (t + timedelta(days=DUE_DAYS[body.priority])).strftime(FMT)))
        log(con, cur.lastrowid, "민원 접수")
        return decorate(get_or_404(con, cur.lastrowid))


@app.post("/api/complaints/{cid}/assign")
def assign(cid: int, body: Assign):
    with db() as con:
        c = get_or_404(con, cid)
        if c["status"] == "종결":
            raise HTTPException(409, "종결된 민원은 담당자를 변경할 수 없습니다.")
        s = con.execute("SELECT * FROM staff WHERE id=?", (body.staff_id,)).fetchone()
        if not s:
            raise HTTPException(404, "담당자를 찾을 수 없습니다.")
        new_status = "배정" if c["status"] == "접수" else c["status"]
        con.execute("UPDATE complaints SET assignee_id=?, status=? WHERE id=?",
                    (s["id"], new_status, cid))
        log(con, cid, f"담당자 {'배정' if c['assignee_id'] is None else '변경'}: {s['name']} ({s['dept']})")
        return decorate(get_or_404(con, cid))


@app.post("/api/complaints/{cid}/status")
def change_status(cid: int, body: StatusChange):
    if body.status not in STATUSES:
        raise HTTPException(422, "올바르지 않은 상태입니다.")
    with db() as con:
        c = get_or_404(con, cid)
        cur_i, new_i = STATUSES.index(c["status"]), STATUSES.index(body.status)
        if new_i == cur_i:
            return decorate(c)
        if new_i != cur_i + 1:
            raise HTTPException(409, "상태는 접수 → 배정 → 처리 → 종결 순서로 한 단계씩만 변경할 수 있습니다.")
        if new_i >= 1 and c["assignee_id"] is None:
            raise HTTPException(409, "담당자를 먼저 배정해야 합니다.")
        if body.status == "종결" and c["reply_count"] == 0:
            raise HTTPException(409, "답변을 등록한 뒤에 종결할 수 있습니다.")
        closed = now().strftime(FMT) if body.status == "종결" else None
        con.execute("UPDATE complaints SET status=?, closed_at=? WHERE id=?", (body.status, closed, cid))
        log(con, cid, f"상태 변경: {c['status']} → {body.status}")
        return decorate(get_or_404(con, cid))


@app.post("/api/complaints/{cid}/replies", status_code=201)
def add_reply(cid: int, body: NewReply):
    with db() as con:
        c = get_or_404(con, cid)
        if c["assignee_id"] is None:
            raise HTTPException(409, "담당자 배정 후 답변을 등록할 수 있습니다.")
        author = (body.author or c["assignee_name"]).strip()
        con.execute("INSERT INTO replies(complaint_id,author,content,created_at) VALUES (?,?,?,?)",
                    (cid, author, body.content.strip(), now().strftime(FMT)))
        log(con, cid, "답변 등록")
        return decorate(get_or_404(con, cid))


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/api/reset")
def reset():
    """데모 데이터 초기화"""
    with db() as con:
        con.executescript("DROP TABLE IF EXISTS history; DROP TABLE IF EXISTS replies;"
                          "DROP TABLE IF EXISTS complaints; DROP TABLE IF EXISTS staff;")
        con.executescript(SCHEMA)
        seed(con)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
