"""다온소프트 신입사원 온보딩 교육 - FastAPI 백엔드.

실행: python -m uvicorn main:app --reload  →  http://127.0.0.1:8000
"""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "onboarding.db"
PASS_SCORE = 80
sessions: dict[str, int] = {}  # token -> employee id (데모용 인메모리 세션)

app = FastAPI(title="다온소프트 신입사원 온보딩 교육")


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
CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY, emp_no TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  dept TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('new','hr')), start_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY, seq INTEGER UNIQUE NOT NULL, title TEXT NOT NULL,
  minutes INTEGER NOT NULL, content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS progress(
  emp_id INTEGER NOT NULL REFERENCES employees(id), lesson_id INTEGER NOT NULL REFERENCES lessons(id),
  completed_at TEXT NOT NULL, PRIMARY KEY(emp_id, lesson_id));
CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY, question TEXT NOT NULL, options TEXT NOT NULL, answer INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY, emp_id INTEGER NOT NULL REFERENCES employees(id),
  score INTEGER NOT NULL, passed INTEGER NOT NULL, taken_at TEXT NOT NULL);
"""

LESSONS = [
    ("회사 소개와 핵심 가치", 10,
     "다온소프트는 2012년 설립된 기업용 소프트웨어 회사로, 물류·제조 고객사를 위한 업무 시스템을 만듭니다.\n\n"
     "핵심 가치는 세 가지입니다.\n- 고객 우선: 고객의 문제를 먼저 이해하고 해결합니다.\n"
     "- 투명한 소통: 문제는 빨리, 공개적으로 공유합니다.\n- 꾸준한 성장: 실패를 기록하고 다음에 활용합니다.\n\n"
     "조직은 개발팀, 디자인팀, 영업팀, 인사팀, 경영지원팀으로 구성되어 있습니다."),
    ("근무 규정과 복지", 15,
     "정규 근무 시간은 09:00~18:00(점심 1시간)이며, 코어타임은 10:00~16:00입니다.\n\n"
     "- 연차: 입사 1년 미만은 매월 1일씩 발생합니다.\n- 휴가·외근은 사내 그룹웨어에서 사전에 신청합니다.\n"
     "- 재택근무는 주 1회, 팀장 승인 후 사용할 수 있습니다.\n- 복지: 점심 식대 지원, 도서·교육비 연 50만 원, 건강검진.\n\n"
     "경비는 지출 후 30일 이내에 영수증과 함께 청구해야 합니다."),
    ("정보보안과 개인정보 보호", 15,
     "고객 데이터와 소스코드는 회사의 핵심 자산입니다.\n\n"
     "- 비밀번호는 12자 이상으로 설정하고 90일마다 변경합니다. 타인과 공유하지 않습니다.\n"
     "- 고객 개인정보는 업무 목적 외로 사용하거나 개인 메신저·메일로 전송하지 않습니다.\n"
     "- 사내 자료는 승인된 클라우드(사내 드라이브)에만 저장합니다. 개인 USB·개인 클라우드는 금지입니다.\n"
     "- 의심스러운 메일의 링크와 첨부파일은 열지 말고 보안담당자(security@daonsoft.example)에게 신고합니다.\n"
     "- 보안 사고를 알게 되면 즉시(1시간 이내) 보고합니다."),
    ("협업 도구와 업무 소통", 10,
     "사내 협업은 다음 도구로 이루어집니다.\n\n"
     "- 메신저: 긴급하지 않은 요청은 채널에 남겨 기록이 공유되도록 합니다.\n"
     "- 이슈 트래커: 모든 작업은 티켓으로 관리하고, 진행 상황을 티켓에 갱신합니다.\n"
     "- 회의: 안건과 시간을 사전에 공유하고, 결정 사항은 회의 후 24시간 이내에 정리합니다.\n"
     "- 막히는 일은 30분 이상 혼자 고민하지 말고 사수 또는 팀 채널에 질문합니다."),
]

QUESTIONS = [
    ("다온소프트의 핵심 가치가 아닌 것은?",
     ["고객 우선", "투명한 소통", "꾸준한 성장", "경쟁 우선"], 3),
    ("입사 1년 미만 직원의 연차는 어떻게 발생하나요?",
     ["매월 1일씩", "입사 시 15일 일괄", "분기마다 3일", "발생하지 않음"], 0),
    ("회사가 권장하는 비밀번호 규칙은?",
     ["8자 이상, 변경 없음", "12자 이상, 90일마다 변경", "6자 이상, 1년마다 변경", "팀원과 공유해 관리"], 1),
    ("의심스러운 메일을 받았을 때 올바른 행동은?",
     ["첨부파일을 열어 확인", "동료에게 전달해 물어봄", "링크·첨부를 열지 않고 보안담당자에게 신고", "무시하고 삭제만 함"], 2),
    ("경비 청구는 지출 후 며칠 이내에 해야 하나요?",
     ["7일", "14일", "30일", "90일"], 2),
]

# (사번, 이름, 부서, 입사일 D-n, 완료 레슨 수, 퀴즈 점수 목록)
EMPLOYEES = [
    ("N2026001", "김민준", "개발팀", 40, 4, [100]),
    ("N2026002", "이서연", "디자인팀", 40, 4, [60, 80]),
    ("N2026003", "박도윤", "영업팀", 33, 4, [60, 40]),
    ("N2026004", "최하은", "개발팀", 33, 4, []),
    ("N2026005", "정우진", "개발팀", 26, 3, []),
    ("N2026006", "강지아", "경영지원팀", 26, 4, [100]),
    ("N2026007", "조현우", "영업팀", 19, 2, []),
    ("N2026008", "윤서아", "디자인팀", 19, 1, []),
    ("N2026009", "임지후", "개발팀", 12, 4, [40]),
    ("N2026010", "한예린", "인사팀", 12, 0, []),
    ("N2026011", "오준서", "개발팀", 5, 1, []),
    ("N2026012", "신유나", "영업팀", 5, 0, []),
]
HR_USER = ("H0001", "박지현", "인사팀")


def init_db(reset: bool = False):
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    with db() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM employees").fetchone()[0]:
            return
        now = datetime.now()
        for i, (title, mins, content) in enumerate(LESSONS, 1):
            con.execute("INSERT INTO lessons(seq,title,minutes,content) VALUES(?,?,?,?)", (i, title, mins, content))
        for q, opts, ans in QUESTIONS:
            con.execute("INSERT INTO questions(question,options,answer) VALUES(?,?,?)",
                        (q, json.dumps(opts, ensure_ascii=False), ans))
        con.execute("INSERT INTO employees(emp_no,name,dept,role,start_date) VALUES(?,?,?,'hr',?)",
                    (*HR_USER, (now - timedelta(days=900)).strftime("%Y-%m-%d")))
        for emp_no, name, dept, ago, done, scores in EMPLOYEES:
            start = now - timedelta(days=ago)
            eid = con.execute("INSERT INTO employees(emp_no,name,dept,role,start_date) VALUES(?,?,?,'new',?)",
                              (emp_no, name, dept, start.strftime("%Y-%m-%d"))).lastrowid
            for seq in range(1, done + 1):
                lid = con.execute("SELECT id FROM lessons WHERE seq=?", (seq,)).fetchone()[0]
                con.execute("INSERT INTO progress VALUES(?,?,?)",
                            (eid, lid, (start + timedelta(days=seq)).strftime("%Y-%m-%d %H:%M:%S")))
            for n, sc in enumerate(scores):
                con.execute("INSERT INTO attempts(emp_id,score,passed,taken_at) VALUES(?,?,?,?)",
                            (eid, sc, int(sc >= PASS_SCORE),
                             (start + timedelta(days=done + 1 + n)).strftime("%Y-%m-%d %H:%M:%S")))


@app.on_event("startup")
def _startup():
    init_db()


# ---------------------------------------------------------------- 인증
class LoginIn(BaseModel):
    emp_no: str


def current_user(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    eid = sessions.get(token)
    if eid is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    with db() as con:
        row = con.execute("SELECT * FROM employees WHERE id=?", (eid,)).fetchone()
    if not row:
        raise HTTPException(401, "로그인이 필요합니다.")
    return dict(row)


def hr_user(user=Depends(current_user)):
    if user["role"] != "hr":
        raise HTTPException(403, "인사팀만 접근할 수 있습니다.")
    return user


@app.post("/api/login")
def login(body: LoginIn):
    # 데모용: 사번만 확인한다. 실사용 시 사내 SSO/비밀번호 인증으로 교체할 것.
    with db() as con:
        row = con.execute("SELECT * FROM employees WHERE emp_no=?", (body.emp_no.strip().upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "등록되지 않은 사번입니다.")
    token = secrets.token_urlsafe(24)
    sessions[token] = row["id"]
    return {"token": token, "user": {k: row[k] for k in ("emp_no", "name", "dept", "role")}}


# ---------------------------------------------------------------- 교육생
def status_of(con, eid: int) -> dict:
    done = {r["seq"] for r in con.execute(
        "SELECT l.seq FROM progress p JOIN lessons l ON l.id=p.lesson_id WHERE p.emp_id=?", (eid,))}
    total = con.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    att = con.execute("SELECT score,passed,taken_at FROM attempts WHERE emp_id=? ORDER BY id", (eid,)).fetchall()
    return {
        "done_seqs": sorted(done), "lessons_done": len(done), "lessons_total": total,
        "attempts": len(att), "last_score": att[-1]["score"] if att else None,
        "best_score": max((a["score"] for a in att), default=None),
        "completed": any(a["passed"] for a in att),
        "completed_at": next((a["taken_at"] for a in att if a["passed"]), None),
    }


@app.get("/api/me")
def me(user=Depends(current_user)):
    with db() as con:
        lessons = [dict(r) for r in con.execute("SELECT id,seq,title,minutes FROM lessons ORDER BY seq")]
        st = status_of(con, user["id"])
    for l in lessons:
        l["done"] = l["seq"] in st["done_seqs"]
        # 이전 레슨까지 모두 완료해야 열림
        l["locked"] = any(s not in st["done_seqs"] for s in range(1, l["seq"]))
    return {"user": {k: user[k] for k in ("emp_no", "name", "dept", "role")}, "status": st, "lessons": lessons,
            "quiz_open": st["lessons_done"] == st["lessons_total"], "pass_score": PASS_SCORE}


def _lesson_for(con, user, seq: int):
    lesson = con.execute("SELECT * FROM lessons WHERE seq=?", (seq,)).fetchone()
    if not lesson:
        raise HTTPException(404, "레슨이 없습니다.")
    done = status_of(con, user["id"])["done_seqs"]
    if any(s not in done for s in range(1, seq)):
        raise HTTPException(403, "이전 레슨을 먼저 완료해 주세요.")
    return lesson, seq in done


@app.get("/api/lessons/{seq}")
def get_lesson(seq: int, user=Depends(current_user)):
    with db() as con:
        lesson, done = _lesson_for(con, user, seq)
    return {**dict(lesson), "done": done}


@app.post("/api/lessons/{seq}/complete")
def complete_lesson(seq: int, user=Depends(current_user)):
    with db() as con:
        lesson, _ = _lesson_for(con, user, seq)
        con.execute("INSERT OR IGNORE INTO progress VALUES(?,?,?)",
                    (user["id"], lesson["id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return {"ok": True}


@app.get("/api/quiz")
def get_quiz(user=Depends(current_user)):
    with db() as con:
        st = status_of(con, user["id"])
        if st["lessons_done"] < st["lessons_total"]:
            raise HTTPException(403, "모든 레슨을 완료해야 퀴즈를 풀 수 있습니다.")
        qs = [{"id": r["id"], "question": r["question"], "options": json.loads(r["options"])}
              for r in con.execute("SELECT * FROM questions ORDER BY id")]
    return {"questions": qs, "pass_score": PASS_SCORE}  # 정답은 내려보내지 않는다


class QuizIn(BaseModel):
    answers: dict[int, int]  # question id -> 선택지 index


@app.post("/api/quiz/submit")
def submit_quiz(body: QuizIn, user=Depends(current_user)):
    with db() as con:
        st = status_of(con, user["id"])
        if st["lessons_done"] < st["lessons_total"]:
            raise HTTPException(403, "모든 레슨을 완료해야 퀴즈를 풀 수 있습니다.")
        qs = con.execute("SELECT id,answer FROM questions").fetchall()
        correct = sum(1 for q in qs if body.answers.get(q["id"]) == q["answer"])
        score = round(correct * 100 / len(qs))
        passed = score >= PASS_SCORE
        con.execute("INSERT INTO attempts(emp_id,score,passed,taken_at) VALUES(?,?,?,?)",
                    (user["id"], score, int(passed), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return {"score": score, "correct": correct, "total": len(qs), "passed": passed, "pass_score": PASS_SCORE}


# ---------------------------------------------------------------- 인사팀
@app.get("/api/hr/overview")
def hr_overview(_=Depends(hr_user)):
    today = datetime.now().date()
    rows = []
    with db() as con:
        for e in con.execute("SELECT * FROM employees WHERE role='new' ORDER BY start_date, emp_no"):
            st = status_of(con, e["id"])
            days = (today - datetime.strptime(e["start_date"], "%Y-%m-%d").date()).days
            if st["completed"]:
                state = "수료"
            elif st["lessons_done"] == 0 and not st["attempts"]:
                state = "미시작"
            else:
                state = "진행중"
            rows.append({"emp_no": e["emp_no"], "name": e["name"], "dept": e["dept"], "start_date": e["start_date"],
                         "days_since_start": days, "lessons_done": st["lessons_done"],
                         "lessons_total": st["lessons_total"], "attempts": st["attempts"],
                         "last_score": st["last_score"], "completed": st["completed"],
                         "completed_at": st["completed_at"], "state": state})
    done = sum(r["completed"] for r in rows)
    return {"summary": {"total": len(rows), "completed": done, "incomplete": len(rows) - done,
                        "rate": round(done * 100 / len(rows)) if rows else 0},
            "employees": rows}


@app.post("/api/admin/reset")
def reset_demo(_=Depends(hr_user)):
    """데모 데이터를 초기 상태로 되돌린다."""
    init_db(reset=True)
    sessions.clear()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
