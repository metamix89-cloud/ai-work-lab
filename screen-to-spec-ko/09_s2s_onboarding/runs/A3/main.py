"""다온소프트 신입사원 온보딩 교육 - FastAPI + SQLite"""
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "onboarding.db"
PASS_SCORE = 80

app = FastAPI(title="다온소프트 신입사원 온보딩")


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


def hash_pw(pw: str, salt: str = "daonsoft") -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 50_000).hex()


SCHEMA = """
CREATE TABLE employees(
  id INTEGER PRIMARY KEY, emp_no TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  dept TEXT NOT NULL, hired_at TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'trainee',
  pw_hash TEXT NOT NULL);
CREATE TABLE lessons(
  id INTEGER PRIMARY KEY, seq INTEGER UNIQUE NOT NULL, title TEXT NOT NULL,
  summary TEXT NOT NULL, content TEXT NOT NULL);
CREATE TABLE lesson_progress(
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  lesson_id INTEGER NOT NULL REFERENCES lessons(id),
  completed_at TEXT NOT NULL, PRIMARY KEY(employee_id, lesson_id));
CREATE TABLE questions(
  id INTEGER PRIMARY KEY, question TEXT NOT NULL, options TEXT NOT NULL, answer INTEGER NOT NULL);
CREATE TABLE attempts(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
  score INTEGER NOT NULL, passed INTEGER NOT NULL, taken_at TEXT NOT NULL);
CREATE TABLE sessions(token TEXT PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id));
"""

LESSONS = [
    ("다온소프트 소개와 조직문화", "우리가 누구이고 어떻게 일하는지",
     "<h3>회사 개요</h3><p>다온소프트는 2012년 설립된 B2B SaaS 기업으로 물류·제조 고객사를 위한 업무 자동화 솔루션 <b>'다온플로우'</b>를 개발합니다. 본사는 판교, 구성원은 약 180명입니다.</p>"
     "<h3>핵심 가치</h3><ul><li><b>고객 우선</b> - 모든 의사결정은 고객 문제 해결에서 출발합니다.</li><li><b>투명한 소통</b> - 상태와 문제를 일찍, 공개적으로 공유합니다.</li><li><b>작게 만들고 빠르게 배우기</b> - 2주 단위 스프린트로 검증합니다.</li></ul>"
     "<h3>호칭 문화</h3><p>직급 대신 <b>'님'</b>으로 부릅니다. 대표이사도 '민준님'처럼 부르며, 회의에서는 직급과 무관하게 의견을 냅니다.</p>"
     "<h3>조직 구성</h3><p>제품개발본부, 고객성공본부, 영업본부, 경영지원본부로 구성되며, 신입사원은 입사 후 3개월간 멘토(Buddy) 1명이 배정됩니다.</p>"),
    ("근무 규정과 복지", "출퇴근, 휴가, 복지 제도",
     "<h3>근무 시간</h3><p>코어타임은 <b>10:00~16:00</b>이며 그 외 시간은 자율 출퇴근입니다. 주 40시간 근무를 기준으로 하며, 연장 근무는 사전에 팀장 승인이 필요합니다.</p>"
     "<h3>휴가</h3><ul><li>연차는 입사 첫 해 월 1일씩 발생하고 1년 후 15일이 부여됩니다.</li><li>연차는 <b>사용 3일 전</b>까지 그룹웨어로 신청합니다. (병가·경조사는 사후 신청 가능)</li><li>매월 셋째 주 금요일은 '리프레시 데이'로 전사 휴무입니다.</li></ul>"
     "<h3>복지</h3><p>점심 식대 월 25만 원, 자기계발비 연 100만 원, 건강검진 연 1회, 재택근무는 주 2회까지 가능합니다.</p>"
     "<h3>경비 처리</h3><p>법인카드 사용 후 <b>7일 이내</b>에 영수증과 함께 정산합니다.</p>"),
    ("정보보안 기본 수칙", "고객 데이터를 지키는 방법",
     "<h3>왜 중요한가</h3><p>다온소프트는 고객사의 물류·생산 데이터를 다루므로 유출 사고는 신뢰와 계약에 직결됩니다.</p>"
     "<h3>필수 수칙</h3><ul><li>비밀번호는 <b>12자 이상</b>, 서비스마다 다르게 설정하고 90일마다 변경합니다.</li><li>모든 사내 시스템은 <b>2단계 인증(OTP)</b>을 사용합니다.</li><li>고객 데이터는 개인 PC·개인 클라우드·개인 메신저로 반출하지 않습니다.</li><li>자리를 비울 때는 <b>Win+L</b>로 화면을 잠급니다.</li></ul>"
     "<h3>피싱 대응</h3><p>의심 메일의 링크·첨부파일은 열지 말고 <b>보안팀(security@daonsoft.example)</b>에 전달합니다. 이미 열었다면 즉시 네트워크를 분리하고 신고합니다.</p>"
     "<h3>사고 발생 시</h3><p>유출이 의심되면 <b>1시간 이내</b> 보안팀에 보고합니다. 숨기는 것이 가장 큰 위반입니다.</p>"),
    ("업무 도구와 협업 방법", "그룹웨어, 메신저, 개발·문서 도구",
     "<h3>사내 도구</h3><ul><li><b>다온웍스</b>: 그룹웨어 (전자결재, 휴가, 경비)</li><li><b>Slack</b>: 실시간 소통. 긴급이 아니면 스레드로 답합니다.</li><li><b>Jira</b>: 업무·이슈 관리 / <b>Confluence</b>: 문서화</li><li><b>GitLab</b>: 소스 관리 (개발 직군)</li></ul>"
     "<h3>회의 원칙</h3><p>회의는 <b>안건 사전 공유</b>가 없으면 열지 않으며, 기본 30분, 종료 후 24시간 이내 회의록을 Confluence에 남깁니다.</p>"
     "<h3>도움 요청</h3><p>막힌 지 <b>30분</b>이 지나면 멘토나 팀 채널에 질문합니다. IT 지원은 #it-helpdesk, 인사 문의는 #hr-support 채널을 이용하세요.</p>"
     "<h3>온보딩 이후</h3><p>수료 후 1개월 차에 멘토와 1:1 면담, 3개월 차에 팀장 평가 면담이 진행됩니다.</p>"),
]

QUESTIONS = [
    ("다온소프트의 주력 솔루션 이름은?", ["다온플로우", "다온웍스", "다온클라우드", "다온시스템"], 0),
    ("다온소프트의 핵심 가치에 해당하지 않는 것은?", ["고객 우선", "투명한 소통", "작게 만들고 빠르게 배우기", "직급 중심의 의사결정"], 3),
    ("사내 호칭 방식은?", ["직급+님", "이름+님", "영어 닉네임", "성+직급"], 1),
    ("코어타임은 언제인가?", ["09:00~15:00", "10:00~16:00", "11:00~17:00", "09:00~18:00"], 1),
    ("연차는 최소 며칠 전에 신청해야 하는가?", ["당일", "1일 전", "3일 전", "7일 전"], 2),
    ("법인카드 사용 후 정산 기한은?", ["3일 이내", "7일 이내", "14일 이내", "30일 이내"], 1),
    ("비밀번호 정책으로 올바른 것은?", ["8자 이상, 변경 없음", "12자 이상, 90일마다 변경", "6자 이상, 1년마다 변경", "생일 기반 허용"], 1),
    ("피싱 의심 메일을 받았을 때 올바른 행동은?", ["링크를 열어 확인", "동료에게 전달해 함께 확인", "열지 않고 보안팀에 전달", "삭제만 하고 무시"], 2),
    ("정보 유출이 의심될 때 보고 기한은?", ["1시간 이내", "당일 퇴근 전", "다음 영업일", "일주일 이내"], 0),
    ("업무에서 막힌 지 얼마가 지나면 도움을 요청하도록 권장하는가?", ["10분", "30분", "반나절", "하루"], 1),
]

TRAINEES = [  # (사번, 이름, 부서, 입사일, 완료 레슨 수, 시험 점수 이력)
    ("N2610", "김서연", "제품개발본부", "2026-09-01", 4, [90]),
    ("N2611", "이도윤", "제품개발본부", "2026-09-01", 4, [60, 80]),
    ("N2612", "박지호", "영업본부", "2026-09-01", 4, [70]),
    ("N2613", "최유나", "고객성공본부", "2026-09-01", 3, []),
    ("N2614", "정민재", "경영지원본부", "2026-09-15", 2, []),
    ("N2615", "한소율", "제품개발본부", "2026-09-15", 4, []),
    ("N2616", "오태민", "영업본부", "2026-09-15", 0, []),
    ("N2617", "윤하린", "고객성공본부", "2026-10-01", 1, []),
    ("N2618", "강지안", "제품개발본부", "2026-10-01", 4, [50, 70]),
    ("N2619", "송우진", "경영지원본부", "2026-10-01", 4, [100]),
    ("N2620", "임채원", "영업본부", "2026-10-15", 0, []),
    ("N2621", "배나은", "고객성공본부", "2026-10-15", 2, []),
]


def init_db():
    if DB_PATH.exists():
        return
    with db() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO employees(emp_no,name,dept,hired_at,role,pw_hash) VALUES(?,?,?,?,?,?)",
                    ("HR001", "조은지 (인사팀)", "경영지원본부", "2019-03-04", "hr", hash_pw("hr1234")))
        for i, (t, s, c) in enumerate(LESSONS, 1):
            con.execute("INSERT INTO lessons(seq,title,summary,content) VALUES(?,?,?,?)", (i, t, s, c))
        for q, o, a in QUESTIONS:
            con.execute("INSERT INTO questions(question,options,answer) VALUES(?,?,?)",
                        (q, json.dumps(o, ensure_ascii=False), a))
        now = datetime.now()
        for n, (no, name, dept, hired, done, scores) in enumerate(TRAINEES):
            eid = con.execute("INSERT INTO employees(emp_no,name,dept,hired_at,role,pw_hash) VALUES(?,?,?,?,'trainee',?)",
                              (no, name, dept, hired, hash_pw("1234"))).lastrowid
            for lid in range(1, done + 1):
                ts = (now - timedelta(days=10 - lid, hours=n)).isoformat(timespec="seconds")
                con.execute("INSERT INTO lesson_progress VALUES(?,?,?)", (eid, lid, ts))
            for k, sc in enumerate(scores):
                ts = (now - timedelta(days=5 - k, hours=n)).isoformat(timespec="seconds")
                con.execute("INSERT INTO attempts(employee_id,score,passed,taken_at) VALUES(?,?,?,?)",
                            (eid, sc, int(sc >= PASS_SCORE), ts))


init_db()


# ---------------------------------------------------------------- auth
def current_user(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    with db() as con:
        row = con.execute("SELECT e.* FROM sessions s JOIN employees e ON e.id=s.employee_id WHERE s.token=?",
                          (token,)).fetchone()
    if not row:
        raise HTTPException(401, "로그인이 필요합니다.")
    return dict(row)


def hr_user(user=Depends(current_user)):
    if user["role"] != "hr":
        raise HTTPException(403, "인사팀만 접근할 수 있습니다.")
    return user


class LoginIn(BaseModel):
    emp_no: str
    password: str


@app.post("/api/login")
def login(body: LoginIn):
    with db() as con:
        u = con.execute("SELECT * FROM employees WHERE emp_no=?", (body.emp_no.strip().upper(),)).fetchone()
        if not u or not secrets.compare_digest(u["pw_hash"], hash_pw(body.password)):
            raise HTTPException(401, "사번 또는 비밀번호가 올바르지 않습니다.")
        token = secrets.token_urlsafe(24)
        con.execute("INSERT INTO sessions VALUES(?,?)", (token, u["id"]))
    return {"token": token, "name": u["name"], "role": u["role"], "emp_no": u["emp_no"]}


# ---------------------------------------------------------------- trainee
def status_of(con, eid: int):
    done = {r["lesson_id"] for r in con.execute("SELECT lesson_id FROM lesson_progress WHERE employee_id=?", (eid,))}
    best = con.execute("SELECT MAX(score) m, COUNT(*) c, MAX(passed) p FROM attempts WHERE employee_id=?", (eid,)).fetchone()
    return done, best


@app.get("/api/me/overview")
def overview(user=Depends(current_user)):
    with db() as con:
        done, best = status_of(con, user["id"])
        lessons = con.execute("SELECT id,seq,title,summary FROM lessons ORDER BY seq").fetchall()
    items, prev_done = [], True
    for l in lessons:
        d = l["id"] in done
        items.append({**dict(l), "completed": d, "locked": not prev_done})
        prev_done = d
    return {"user": {k: user[k] for k in ("name", "emp_no", "dept", "role")}, "lessons": items,
            "quiz_unlocked": len(done) == len(lessons), "best_score": best["m"], "attempts": best["c"],
            "certified": bool(best["p"]), "pass_score": PASS_SCORE}


@app.get("/api/lessons/{seq}")
def get_lesson(seq: int, user=Depends(current_user)):
    with db() as con:
        l = con.execute("SELECT * FROM lessons WHERE seq=?", (seq,)).fetchone()
        if not l:
            raise HTTPException(404, "레슨이 없습니다.")
        done, _ = status_of(con, user["id"])
        prev = con.execute("SELECT id FROM lessons WHERE seq=?", (seq - 1,)).fetchone()
        if prev and prev["id"] not in done:
            raise HTTPException(403, "이전 레슨을 먼저 완료해 주세요.")
        total = con.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    return {**dict(l), "completed": l["id"] in done, "is_last": seq == total}


@app.post("/api/lessons/{seq}/complete")
def complete_lesson(seq: int, user=Depends(current_user)):
    get_lesson(seq, user)  # 순서 검증
    with db() as con:
        lid = con.execute("SELECT id FROM lessons WHERE seq=?", (seq,)).fetchone()["id"]
        con.execute("INSERT OR IGNORE INTO lesson_progress VALUES(?,?,?)",
                    (user["id"], lid, datetime.now().isoformat(timespec="seconds")))
    return {"ok": True}


def require_all_lessons(con, eid):
    done, _ = status_of(con, eid)
    if len(done) < con.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]:
        raise HTTPException(403, "모든 레슨을 완료해야 퀴즈를 풀 수 있습니다.")


@app.get("/api/quiz")
def quiz(user=Depends(current_user)):
    with db() as con:
        require_all_lessons(con, user["id"])
        qs = con.execute("SELECT id,question,options FROM questions ORDER BY id").fetchall()
    return {"pass_score": PASS_SCORE,
            "questions": [{"id": q["id"], "question": q["question"], "options": json.loads(q["options"])} for q in qs]}


class QuizIn(BaseModel):
    answers: dict[int, int]


@app.post("/api/quiz/submit")
def submit(body: QuizIn, user=Depends(current_user)):
    with db() as con:
        require_all_lessons(con, user["id"])
        qs = con.execute("SELECT id,answer FROM questions").fetchall()
        correct = sum(1 for q in qs if body.answers.get(q["id"]) == q["answer"])
        score = round(correct * 100 / len(qs))
        passed = score >= PASS_SCORE
        con.execute("INSERT INTO attempts(employee_id,score,passed,taken_at) VALUES(?,?,?,?)",
                    (user["id"], score, int(passed), datetime.now().isoformat(timespec="seconds")))
    return {"score": score, "correct": correct, "total": len(qs), "passed": passed, "pass_score": PASS_SCORE}


# ---------------------------------------------------------------- HR
def hr_rows():
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        rows = con.execute("""
          SELECT e.id, e.emp_no, e.name, e.dept, e.hired_at,
            (SELECT COUNT(*) FROM lesson_progress p WHERE p.employee_id=e.id) lessons_done,
            (SELECT MAX(score) FROM attempts a WHERE a.employee_id=e.id) best_score,
            (SELECT COUNT(*) FROM attempts a WHERE a.employee_id=e.id) attempts,
            (SELECT COALESCE(MAX(passed),0) FROM attempts a WHERE a.employee_id=e.id) certified
          FROM employees e WHERE e.role='trainee' ORDER BY e.hired_at, e.emp_no""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["lessons_total"] = total
        d["state"] = ("수료" if d["certified"] else "퀴즈 불합격" if d["attempts"]
                      else "퀴즈 대기" if d["lessons_done"] == total
                      else "수강 중" if d["lessons_done"] else "미시작")
        out.append(d)
    return out


@app.get("/api/hr/incomplete")
def hr_incomplete(_=Depends(hr_user)):
    rows = hr_rows()
    return {"summary": {"total": len(rows), "certified": sum(r["certified"] for r in rows),
                        "incomplete": sum(not r["certified"] for r in rows)},
            "pass_score": PASS_SCORE,
            "incomplete": [r for r in rows if not r["certified"]]}


@app.get("/api/hr/all")
def hr_all(_=Depends(hr_user)):
    return hr_rows()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
