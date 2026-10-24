import sqlite3
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY, emp_no TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  department TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('trainee','hr')),
  password TEXT NOT NULL, hired_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lesson_progress(
  employee_id INTEGER NOT NULL REFERENCES employees(id), lesson_id INTEGER NOT NULL,
  completed_at TEXT NOT NULL, PRIMARY KEY(employee_id, lesson_id));
CREATE TABLE IF NOT EXISTS quiz_attempts(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
  score INTEGER NOT NULL, passed INTEGER NOT NULL, taken_at TEXT NOT NULL);
"""

# (사번, 이름, 부서, 입사 N일 전, 완료한 레슨 수, 퀴즈 점수 목록)
TRAINEES = [
    ("N2601", "김민준", "제품개발팀", 40, 4, [90]),
    ("N2602", "이서연", "제품개발팀", 40, 4, [60, 80]),
    ("N2603", "박지호", "고객성공팀", 35, 4, [70]),   # 미수료(재응시 필요)
    ("N2604", "최하은", "고객성공팀", 35, 4, []),      # 퀴즈 미응시
    ("N2605", "정우진", "경영지원팀", 21, 3, []),      # 진행 중
    ("N2606", "강수아", "제품개발팀", 14, 2, []),
    ("N2607", "윤도현", "제품개발팀", 7, 0, []),       # 시작 전
    ("N2608", "한지민", "고객성공팀", 7, 4, [100]),
]
HR = [("HR001", "오인사", "인사팀"), ("HR002", "장채용", "인사팀")]


def seed(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM employees").fetchone()[0]:
        con.close()
        return
    now = datetime.now()
    for no, name, dept in HR:
        con.execute("INSERT INTO employees(emp_no,name,department,role,password,hired_at) VALUES(?,?,?,?,?,?)",
                    (no, name, dept, "hr", "hr1234", (now - timedelta(days=900)).date().isoformat()))
    for no, name, dept, ago, lessons, scores in TRAINEES:
        hired = now - timedelta(days=ago)
        cur = con.execute("INSERT INTO employees(emp_no,name,department,role,password,hired_at) VALUES(?,?,?,?,?,?)",
                          (no, name, dept, "trainee", "1234", hired.date().isoformat()))
        eid = cur.lastrowid
        for lid in range(1, lessons + 1):
            con.execute("INSERT INTO lesson_progress VALUES(?,?,?)",
                        (eid, lid, (hired + timedelta(days=lid)).isoformat(timespec="seconds")))
        for i, s in enumerate(scores):
            con.execute("INSERT INTO quiz_attempts(employee_id,score,passed,taken_at) VALUES(?,?,?,?)",
                        (eid, s, int(s >= 80), (hired + timedelta(days=6 + i)).isoformat(timespec="seconds")))
    con.commit()
    con.close()
