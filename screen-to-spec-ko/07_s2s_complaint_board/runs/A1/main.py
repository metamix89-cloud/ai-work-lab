"""푸른구청 민원 접수 · 처리 현황판 (FastAPI + SQLite)"""
import random
import sqlite3
from contextlib import closing, asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "complaints.db"
STATUSES = ["접수", "배정", "처리", "종결"]
CATEGORIES = ["도로·교통", "환경·청소", "복지", "주택·건축", "상하수도", "공원·녹지", "기타"]


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


SCHEMA = """
CREATE TABLE IF NOT EXISTS staff(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS complaints(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, content TEXT NOT NULL, category TEXT NOT NULL,
  applicant TEXT NOT NULL, status TEXT NOT NULL DEFAULT '접수',
  assignee_id INTEGER REFERENCES staff(id),
  received_at TEXT NOT NULL, due_date TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS replies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  complaint_id INTEGER NOT NULL REFERENCES complaints(id),
  author TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
"""

SAMPLES = [
    ("도로·교통", "OO초등학교 앞 횡단보도 신호 시간 연장 요청", "등하교 시간에 보행 신호가 너무 짧아 어르신과 아이들이 건너기 어렵습니다."),
    ("도로·교통", "푸른로 사거리 도로 파손(포트홀) 신고", "차량 통행 시 충격이 심하며 우천 시 물이 고여 위험합니다."),
    ("도로·교통", "불법 주정차로 인한 소방도로 막힘", "아파트 후문 앞 소방도로에 상습적으로 차량이 주차되어 있습니다."),
    ("환경·청소", "공원 앞 쓰레기 무단투기 단속 요청", "야간에 종량제 봉투 없이 쓰레기가 투기되고 있습니다."),
    ("환경·청소", "음식물 쓰레기 수거 지연", "3일째 수거가 되지 않아 악취가 심합니다."),
    ("환경·청소", "공사장 소음·분진 민원", "평일 이른 아침부터 공사 소음이 발생합니다."),
    ("복지", "기초생활수급 자격 재심사 문의", "소득 변동이 있어 재심사 절차를 알고 싶습니다."),
    ("복지", "독거노인 안부확인 서비스 신청", "이웃 어르신의 돌봄서비스 신청을 도와주세요."),
    ("복지", "아동수당 지급 누락 확인 요청", "지난달 아동수당이 입금되지 않았습니다."),
    ("주택·건축", "옆 건물 불법 증축 의심 신고", "옥상에 허가 없이 구조물이 설치되고 있는 것 같습니다."),
    ("주택·건축", "노후 담장 붕괴 위험", "골목 담장이 기울어 보행자 안전이 우려됩니다."),
    ("상하수도", "수돗물 탁수 발생", "오전부터 수돗물이 누렇게 나옵니다."),
    ("상하수도", "하수구 역류 및 악취", "장마철마다 골목 하수구에서 물이 역류합니다."),
    ("공원·녹지", "어린이공원 놀이기구 파손", "그네 체인이 끊어져 사고 위험이 있습니다."),
    ("공원·녹지", "가로수 가지치기 요청", "가지가 간판과 전선을 가리고 있습니다."),
    ("공원·녹지", "산책로 가로등 소등", "하천 산책로 가로등 3개가 꺼져 있어 야간에 위험합니다."),
    ("기타", "구청 홈페이지 증명서 발급 오류", "전자 민원 발급 중 결제 단계에서 오류가 납니다."),
    ("기타", "주민센터 운영시간 연장 건의", "직장인을 위해 주 1회 야간 운영을 건의합니다."),
    ("도로·교통", "버스정류장 쉘터 설치 요청", "비와 햇볕을 피할 곳이 없어 불편합니다."),
    ("환경·청소", "길고양이 급식소 관련 갈등 중재", "급식소 위치 문제로 주민 간 분쟁이 있습니다."),
]
NAMES = ["김하늘", "이서준", "박지우", "최민재", "정수아", "강도윤", "조은서", "윤재현", "장서연", "임태양"]
STAFF = [("김푸른", "도로교통과"), ("이맑음", "청소행정과"), ("박온유", "복지정책과"),
         ("최건축", "건축주택과"), ("정수도", "상하수도과"), ("한녹지", "공원녹지과"), ("오민원", "민원여권과")]
STAFF_BY_CAT = {"도로·교통": 1, "환경·청소": 2, "복지": 3, "주택·건축": 4, "상하수도": 5, "공원·녹지": 6, "기타": 7}


def seed(con):
    """오늘 날짜 기준 상대 날짜로 가상 데이터를 만든다(기한 초과 건 포함)."""
    rnd = random.Random(77)
    con.executemany("INSERT INTO staff(id,name,dept) VALUES(?,?,?)",
                    [(i + 1, n, d) for i, (n, d) in enumerate(STAFF)])
    today = date.today()
    plan = ["접수"] * 5 + ["배정"] * 5 + ["처리"] * 6 + ["종결"] * 4
    rnd.shuffle(plan)
    for (cat, title, content), status in zip(SAMPLES, plan):
        ago = rnd.randint(0, 9) if status == "접수" else rnd.randint(3, 14)
        recv = today - timedelta(days=ago)
        due = recv + timedelta(days=rnd.choice([5, 7, 7, 10, 14]))
        staff_id = STAFF_BY_CAT[cat] if status != "접수" else None
        cur = con.execute(
            "INSERT INTO complaints(title,content,category,applicant,status,assignee_id,received_at,due_date)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (title, content, cat, rnd.choice(NAMES), status, staff_id,
             f"{recv} {rnd.randint(9, 17):02d}:{rnd.choice(['00', '15', '30', '45'])}", str(due)))
        cid = cur.lastrowid
        author = STAFF[staff_id - 1][0] if staff_id else None
        if status in ("처리", "종결"):
            con.execute("INSERT INTO replies(complaint_id,author,body,created_at) VALUES(?,?,?,?)",
                        (cid, author, "현장 확인 후 조치 중입니다. 완료되는 대로 안내드리겠습니다.",
                         f"{recv + timedelta(days=1)} 10:00"))
        if status == "종결":
            end = min(today, recv + timedelta(days=rnd.randint(2, 9)))
            con.execute("UPDATE complaints SET closed_at=? WHERE id=?", (f"{end} 15:00", cid))
            con.execute("INSERT INTO replies(complaint_id,author,body,created_at) VALUES(?,?,?,?)",
                        (cid, author, "요청하신 사항을 조치 완료하였습니다. 이용해 주셔서 감사합니다.", f"{end} 15:00"))


@asynccontextmanager
async def lifespan(_):
    with closing(db()) as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM complaints").fetchone()[0] == 0:
            seed(con)
        con.commit()
    yield


app = FastAPI(title="푸른구청 민원 현황판", lifespan=lifespan)

SELECT = """SELECT c.*, s.name AS assignee_name, s.dept AS assignee_dept FROM complaints c
            LEFT JOIN staff s ON s.id = c.assignee_id"""


def shape(row, replies=None):
    d = dict(row)
    if d["status"] == "종결":
        d["days_left"], d["overdue"] = None, False
        d["late_closed"] = bool(d["closed_at"]) and d["closed_at"][:10] > d["due_date"]
    else:
        d["days_left"] = (date.fromisoformat(d["due_date"]) - date.today()).days
        d["overdue"] = d["days_left"] < 0
        d["late_closed"] = False
    if replies is not None:
        d["replies"] = replies
    return d


def get_or_404(con, cid):
    row = con.execute(SELECT + " WHERE c.id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "민원을 찾을 수 없습니다.")
    return row


@app.get("/api/meta")
def meta():
    with closing(db()) as con:
        staff = [dict(r) for r in con.execute("SELECT * FROM staff ORDER BY id")]
    return {"statuses": STATUSES, "categories": CATEGORIES, "staff": staff}


@app.get("/api/complaints")
def list_complaints():
    with closing(db()) as con:
        rows = con.execute(SELECT + " ORDER BY c.due_date, c.id").fetchall()
    return [shape(r) for r in rows]


@app.get("/api/complaints/{cid}")
def detail(cid: int):
    with closing(db()) as con:
        row = get_or_404(con, cid)
        reps = [dict(r) for r in con.execute(
            "SELECT * FROM replies WHERE complaint_id=? ORDER BY id", (cid,))]
    return shape(row, reps)


class NewComplaint(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    category: str
    applicant: str = Field(min_length=1, max_length=30)
    due_days: int = Field(default=7, ge=1, le=60)


@app.post("/api/complaints", status_code=201)
def create(body: NewComplaint):
    if body.category not in CATEGORIES:
        raise HTTPException(422, "알 수 없는 분류입니다.")
    due = date.today() + timedelta(days=body.due_days)
    with closing(db()) as con:
        cur = con.execute(
            "INSERT INTO complaints(title,content,category,applicant,received_at,due_date) VALUES(?,?,?,?,?,?)",
            (body.title.strip(), body.content.strip(), body.category, body.applicant.strip(), now(), str(due)))
        con.commit()
        return shape(get_or_404(con, cur.lastrowid))


class Assign(BaseModel):
    staff_id: int


@app.post("/api/complaints/{cid}/assign")
def assign(cid: int, body: Assign):
    with closing(db()) as con:
        c = get_or_404(con, cid)
        if c["status"] == "종결":
            raise HTTPException(409, "종결된 민원은 담당자를 바꿀 수 없습니다.")
        if not con.execute("SELECT 1 FROM staff WHERE id=?", (body.staff_id,)).fetchone():
            raise HTTPException(422, "존재하지 않는 담당자입니다.")
        status = "배정" if c["status"] == "접수" else c["status"]
        con.execute("UPDATE complaints SET assignee_id=?, status=? WHERE id=?", (body.staff_id, status, cid))
        con.commit()
        return shape(get_or_404(con, cid))


class Move(BaseModel):
    status: str


@app.post("/api/complaints/{cid}/status")
def move(cid: int, body: Move):
    if body.status not in STATUSES:
        raise HTTPException(422, "알 수 없는 상태입니다.")
    with closing(db()) as con:
        c = get_or_404(con, cid)
        cur, new = STATUSES.index(c["status"]), STATUSES.index(body.status)
        if cur == new:
            return shape(c)
        if c["status"] == "종결":
            raise HTTPException(409, "종결된 민원은 상태를 바꿀 수 없습니다.")
        if new < cur:
            raise HTTPException(409, "이전 단계로 되돌릴 수 없습니다.")
        if body.status == "종결":
            raise HTTPException(409, "종결은 답변 등록(종결 처리)으로만 가능합니다.")
        if not c["assignee_id"]:
            raise HTTPException(409, "담당자를 먼저 배정해 주세요.")
        con.execute("UPDATE complaints SET status=? WHERE id=?", (body.status, cid))
        con.commit()
        return shape(get_or_404(con, cid))


class Reply(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    close: bool = False


@app.post("/api/complaints/{cid}/reply", status_code=201)
def reply(cid: int, body: Reply):
    with closing(db()) as con:
        c = get_or_404(con, cid)
        if c["status"] == "종결":
            raise HTTPException(409, "이미 종결된 민원입니다.")
        if not c["assignee_id"]:
            raise HTTPException(409, "담당자 배정 후 답변을 등록할 수 있습니다.")
        con.execute("INSERT INTO replies(complaint_id,author,body,created_at) VALUES(?,?,?,?)",
                    (cid, c["assignee_name"], body.body.strip(), now()))
        if body.close:
            con.execute("UPDATE complaints SET status='종결', closed_at=? WHERE id=?", (now(), cid))
        elif c["status"] == "배정":
            con.execute("UPDATE complaints SET status='처리' WHERE id=?", (cid,))
        con.commit()
        return shape(get_or_404(con, cid))


@app.get("/api/stats")
def stats():
    with closing(db()) as con:
        rows = [shape(r) for r in con.execute(SELECT)]
    return {
        "total": len(rows),
        "by_status": {s: sum(r["status"] == s for r in rows) for s in STATUSES},
        "overdue": sum(r["overdue"] for r in rows),
        "due_soon": sum(r["days_left"] is not None and 0 <= r["days_left"] <= 2 for r in rows),
    }


app.mount("/static", StaticFiles(directory=BASE / "static", check_dir=False), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
