"""콩알반도체 불량 신고 · 조치 추적판 (FastAPI + SQLite)"""
import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DEFECT_DB", str(BASE / "defects.db"))

# 심각도별 조치 기한(시간) — 신고 시각 기준
SEVERITY = {
    "치명": {"hours": 24, "rank": 0},
    "높음": {"hours": 72, "rank": 1},
    "보통": {"hours": 168, "rank": 2},
    "낮음": {"hours": 336, "rank": 3},
}
STATUSES = ["신고", "분석중", "조치중", "검증중", "종결"]
DEFECT_TYPES = ["스크래치", "파티클 오염", "패턴 결함", "와이어 본딩 불량", "크랙", "두께 편차",
                "접합 불량", "전기적 특성 이상", "마킹 불량"]
LINES = ["FAB-1", "FAB-2", "패키징-A", "패키징-B", "테스트"]
PROCESSES = ["포토", "식각", "증착", "CMP", "다이싱", "본딩", "몰딩", "최종 테스트"]

app = FastAPI(title="불량 신고 · 조치 추적판")


def now():
    return datetime.now().replace(microsecond=0)


def fmt(dt):
    return dt.isoformat(timespec="seconds")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, team TEXT);
CREATE TABLE IF NOT EXISTS defects(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_no TEXT NOT NULL, line TEXT NOT NULL, process TEXT NOT NULL,
  defect_type TEXT NOT NULL, severity TEXT NOT NULL, qty INTEGER NOT NULL,
  description TEXT NOT NULL, reporter_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL, root_cause TEXT, action_plan TEXT,
  assignee_id INTEGER REFERENCES users(id), action_result TEXT, verify_note TEXT,
  reported_at TEXT NOT NULL, due_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, defect_id INTEGER NOT NULL REFERENCES defects(id),
  at TEXT NOT NULL, actor_id INTEGER REFERENCES users(id), kind TEXT NOT NULL, note TEXT);
"""


def add_event(con, defect_id, actor_id, kind, note="", at=None):
    con.execute("INSERT INTO events(defect_id,at,actor_id,kind,note) VALUES(?,?,?,?,?)",
                (defect_id, fmt(at or now()), actor_id, kind, note))


def seed(con):
    users = [
        (1, "김민준", "worker", "FAB-1 생산"), (2, "이서연", "worker", "FAB-2 생산"),
        (3, "박지훈", "worker", "패키징 생산"), (4, "최유진", "quality", "품질팀"),
        (5, "정도현", "quality", "품질팀"), (6, "한소희", "engineer", "공정기술팀"),
        (7, "오태양", "engineer", "설비팀"), (8, "윤하늘", "engineer", "패키징기술팀"),
    ]
    con.executemany("INSERT INTO users VALUES(?,?,?,?)", users)
    rnd = random.Random(84)
    t0 = now()
    # (경과 시간h, 상태, 심각도, 라인, 공정, 유형, 수량, 설명, 신고자, 담당자, 원인, 조치계획)
    rows = [
        (100, "조치중", "치명", "FAB-1", "식각", "패턴 결함", 25, "웨이퍼 중앙부 패턴 선폭 불균일, 25매 전수 영향", 1, 6,
         "식각 챔버 RF 파워 드리프트", "RF 매칭 네트워크 교체 및 챔버 시즌닝 재실시"),
        (80, "조치중", "높음", "패키징-A", "본딩", "와이어 본딩 불량", 1200, "본딩 풋 리프트 발생, 풀 테스트 기준 미달", 3, 8,
         "캐필러리 마모 한계 초과", "캐필러리 교체 주기 8만 → 5만 타로 단축"),
        (30, "조치중", "치명", "FAB-2", "포토", "파티클 오염", 50, "노광 후 파티클 다수 검출, 수율 급락", 2, 6,
         "스테퍼 척 오염 추정", "척 세정 및 파티클 카운터 재측정"),
        (60, "분석중", "높음", "FAB-1", "CMP", "스크래치", 18, "CMP 후 마이크로 스크래치 18매 발견", 1, None, None, None),
        (200, "분석중", "보통", "테스트", "최종 테스트", "전기적 특성 이상", 340, "Idd 규격 상한 근접 로트 다수", 3, None, None, None),
        (5, "신고", "치명", "패키징-B", "몰딩", "크랙", 800, "몰딩 컴파운드 균열, 외관검사 불합격", 3, None, None, None),
        (20, "신고", "보통", "FAB-2", "증착", "두께 편차", 12, "박막 두께 웨이퍼 에지 +4% 편차", 2, None, None, None),
        (2, "신고", "낮음", "패키징-A", "마킹", "마킹 불량", 60, "레이저 마킹 일부 흐림", 3, None, None, None),
        (50, "검증중", "높음", "패키징-B", "다이싱", "크랙", 150, "다이싱 칩핑 규격 초과", 3, 8,
         "블레이드 이송 속도 과다", "이송 속도 30% 감속, 블레이드 교체"),
        (120, "검증중", "보통", "FAB-1", "증착", "두께 편차", 8, "산화막 두께 하한 근접", 1, 7,
         "가스 유량계(MFC) 보정 이탈", "MFC 재보정 및 PM 주기 단축"),
        (400, "종결", "높음", "FAB-2", "식각", "패턴 결함", 40, "측벽 프로파일 불량", 2, 6,
         "식각 가스 비율 설정 오류", "레시피 복구 및 변경 승인 절차 강화"),
        (300, "종결", "치명", "패키징-A", "본딩", "접합 불량", 2000, "다이 어태치 보이드 과다", 3, 8,
         "에폭시 경화 온도 프로파일 이탈", "오븐 온도 센서 교체, 프로파일 모니터링 추가"),
        (500, "종결", "보통", "테스트", "최종 테스트", "전기적 특성 이상", 90, "프로브 카드 접촉 불량", 3, 7,
         "프로브 니들 마모", "프로브 카드 교체 및 클리닝 주기 단축"),
        (450, "종결", "낮음", "FAB-1", "포토", "스크래치", 3, "레지스트 코팅 표면 얇은 스크래치", 1, 6,
         "웨이퍼 핸들링 암 접촉", "핸들링 암 패드 교체"),
        (90, "종결", "낮음", "FAB-2", "CMP", "스크래치", 2, "슬러리 응집 의심 스크래치", 2, 6,
         "슬러리 필터 막힘", "필터 교체"),
    ]
    for i, (age, st, sev, line, proc, typ, qty, desc, rep, asg, cause, plan) in enumerate(rows, 1):
        rep_at = t0 - timedelta(hours=age)
        due = rep_at + timedelta(hours=SEVERITY[sev]["hours"])
        lot = f"LOT-{(t0 - timedelta(hours=age + 6)).strftime('%y%m%d')}-{rnd.randint(100, 999)}"
        closed = None
        result = verify = None
        if st in ("검증중", "종결"):
            result = "계획대로 조치 완료, 후속 로트 3개 샘플 측정 결과 정상"
        if st == "종결":
            verify = "후속 로트 이상 없음 확인. 재발 방지 항목 표준서 반영."
            closed = min(t0 - timedelta(hours=1), rep_at + timedelta(hours=SEVERITY[sev]["hours"] * rnd.choice([0.6, 0.8, 1.3])))
        con.execute(
            "INSERT INTO defects(id,lot_no,line,process,defect_type,severity,qty,description,reporter_id,status,"
            "root_cause,action_plan,assignee_id,action_result,verify_note,reported_at,due_at,closed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, lot, line, proc, typ, sev, qty, desc, rep, st, cause, plan, asg, result, verify,
             fmt(rep_at), fmt(due), fmt(closed) if closed else None))
        add_event(con, i, rep, "신고", f"{sev} 심각도로 신고", rep_at)
        step = timedelta(hours=min(age, 6) / 3 if age else 0)
        if st != "신고":
            add_event(con, i, 4, "분석 착수", "품질팀 접수", rep_at + step)
        if asg:
            add_event(con, i, 4, "담당자 지정", f"원인: {cause} / 조치: {plan}", rep_at + 2 * step)
        if st in ("검증중", "종결"):
            add_event(con, i, asg, "조치 완료 보고", result, rep_at + 3 * step)
        if st == "종결":
            add_event(con, i, 5, "검증 후 종결", verify, closed)


def init_db():
    con = db()
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(con)
    con.commit()
    con.close()


init_db()


def row_to_dict(r, con=None):
    d = dict(r)
    due = datetime.fromisoformat(d["due_at"])
    end = datetime.fromisoformat(d["closed_at"]) if d["closed_at"] else now()
    d["overdue"] = end > due
    d["hours_left"] = None if d["status"] == "종결" else round((due - now()).total_seconds() / 3600, 1)
    return d


BASE_SQL = """SELECT d.*, rp.name AS reporter_name, a.name AS assignee_name, a.team AS assignee_team
FROM defects d JOIN users rp ON rp.id=d.reporter_id LEFT JOIN users a ON a.id=d.assignee_id"""


@app.get("/api/meta")
def meta():
    return {"severity": SEVERITY, "statuses": STATUSES, "defect_types": DEFECT_TYPES,
            "lines": LINES, "processes": PROCESSES}


@app.get("/api/users")
def users():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM users ORDER BY id")]


@app.get("/api/defects")
def list_defects(status: str = "", severity: str = "", assignee_id: int = 0,
                 overdue: bool = False, q: str = ""):
    sql, args = BASE_SQL + " WHERE 1=1", []
    if status == "open":
        sql += " AND d.status!='종결'"
    elif status:
        sql += " AND d.status=?"; args.append(status)
    if severity:
        sql += " AND d.severity=?"; args.append(severity)
    if assignee_id:
        sql += " AND d.assignee_id=?"; args.append(assignee_id)
    if q:
        sql += " AND (d.lot_no LIKE ? OR d.description LIKE ? OR d.defect_type LIKE ?)"
        args += [f"%{q}%"] * 3
    with db() as con:
        items = [row_to_dict(r) for r in con.execute(sql, args)]
    if overdue:
        items = [i for i in items if i["overdue"] and i["status"] != "종결"]
    # 미종결 우선 → 기한 임박 순
    items.sort(key=lambda i: (i["status"] == "종결", i["due_at"] if i["status"] != "종결" else i["closed_at"] or ""))
    return items


@app.get("/api/summary")
def summary():
    with db() as con:
        items = [row_to_dict(r) for r in con.execute(BASE_SQL)]
        people = [dict(r) for r in con.execute("SELECT * FROM users WHERE role='engineer' ORDER BY id")]
    open_ = [i for i in items if i["status"] != "종결"]
    closed = [i for i in items if i["status"] == "종결"]
    by_status = {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}
    workload = []
    for p in people:
        mine = [i for i in open_ if i["assignee_id"] == p["id"]]
        workload.append({**p, "active": len(mine),
                         "overdue": sum(1 for i in mine if i["overdue"]),
                         "items": [{"id": i["id"], "lot_no": i["lot_no"], "severity": i["severity"],
                                    "status": i["status"], "hours_left": i["hours_left"],
                                    "overdue": i["overdue"]} for i in sorted(mine, key=lambda x: x["due_at"])]})
    unassigned = [i for i in open_ if not i["assignee_id"]]
    return {
        "open": len(open_),
        "overdue": sum(1 for i in open_ if i["overdue"]),
        "due_soon": sum(1 for i in open_ if not i["overdue"] and i["hours_left"] is not None and i["hours_left"] <= 24),
        "unassigned": len(unassigned),
        "closed": len(closed),
        "closed_on_time_rate": round(100 * sum(1 for i in closed if not i["overdue"]) / len(closed)) if closed else None,
        "by_status": by_status,
        "workload": workload,
    }


@app.get("/api/defects/{did}")
def get_defect(did: int):
    with db() as con:
        r = con.execute(BASE_SQL + " WHERE d.id=?", (did,)).fetchone()
        if not r:
            raise HTTPException(404, "신고 건을 찾을 수 없습니다")
        d = row_to_dict(r)
        d["events"] = [dict(e) for e in con.execute(
            "SELECT e.*, u.name AS actor_name FROM events e LEFT JOIN users u ON u.id=e.actor_id "
            "WHERE defect_id=? ORDER BY e.at, e.id", (did,))]
    return d


class NewDefect(BaseModel):
    lot_no: str
    line: str
    process: str
    defect_type: str
    severity: str
    qty: int
    description: str
    reporter_id: int


@app.post("/api/defects", status_code=201)
def create_defect(b: NewDefect):
    if b.severity not in SEVERITY:
        raise HTTPException(422, "심각도가 올바르지 않습니다")
    if b.qty < 1 or not b.lot_no.strip() or not b.description.strip():
        raise HTTPException(422, "로트 번호, 수량, 내용을 확인하세요")
    t = now()
    with db() as con:
        u = con.execute("SELECT * FROM users WHERE id=?", (b.reporter_id,)).fetchone()
        if not u:
            raise HTTPException(422, "신고자를 찾을 수 없습니다")
        cur = con.execute(
            "INSERT INTO defects(lot_no,line,process,defect_type,severity,qty,description,reporter_id,status,reported_at,due_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (b.lot_no.strip(), b.line, b.process, b.defect_type, b.severity, b.qty, b.description.strip(),
             b.reporter_id, "신고", fmt(t), fmt(t + timedelta(hours=SEVERITY[b.severity]["hours"]))))
        add_event(con, cur.lastrowid, b.reporter_id, "신고", f"{b.severity} 심각도로 신고", t)
        return {"id": cur.lastrowid}


class Action(BaseModel):
    actor_id: int
    action: str  # start_analysis | assign | complete | verify | reject | reassign
    root_cause: str = ""
    action_plan: str = ""
    assignee_id: int = 0
    note: str = ""


@app.post("/api/defects/{did}/action")
def act(did: int, b: Action):
    with db() as con:
        d = con.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone()
        actor = con.execute("SELECT * FROM users WHERE id=?", (b.actor_id,)).fetchone()
        if not d or not actor:
            raise HTTPException(404, "대상을 찾을 수 없습니다")
        st, role = d["status"], actor["role"]

        def need(cond, msg):
            if not cond:
                raise HTTPException(403 if "권한" in msg else 409, msg)

        if b.action == "start_analysis":
            need(role == "quality", "품질팀만 분석을 시작할 수 있습니다 (권한)")
            need(st == "신고", "신고 상태에서만 가능합니다")
            con.execute("UPDATE defects SET status='분석중' WHERE id=?", (did,))
            add_event(con, did, b.actor_id, "분석 착수", "품질팀 접수")
        elif b.action in ("assign", "reassign"):
            need(role == "quality", "품질팀만 담당자를 지정할 수 있습니다 (권한)")
            if b.action == "assign":
                need(st == "분석중", "분석중 상태에서만 지정할 수 있습니다")
                need(b.root_cause.strip() and b.action_plan.strip(), "원인과 조치 계획을 입력하세요")
            else:
                need(st in ("조치중", "검증중"), "조치중/검증중에서만 재지정할 수 있습니다")
            asg = con.execute("SELECT * FROM users WHERE id=? AND role='engineer'", (b.assignee_id,)).fetchone()
            need(asg, "담당자는 엔지니어 중에서 선택하세요")
            if b.action == "assign":
                con.execute("UPDATE defects SET status='조치중', root_cause=?, action_plan=?, assignee_id=? WHERE id=?",
                            (b.root_cause.strip(), b.action_plan.strip(), b.assignee_id, did))
                add_event(con, did, b.actor_id, "담당자 지정",
                          f"담당: {asg['name']} / 원인: {b.root_cause.strip()} / 조치: {b.action_plan.strip()}")
            else:
                con.execute("UPDATE defects SET assignee_id=? WHERE id=?", (b.assignee_id, did))
                add_event(con, did, b.actor_id, "담당자 변경", f"{asg['name']} 으로 재지정. {b.note}")
        elif b.action == "complete":
            need(st == "조치중", "조치중 상태에서만 완료 보고할 수 있습니다")
            need(role == "quality" or b.actor_id == d["assignee_id"], "지정된 담당자만 완료 보고할 수 있습니다 (권한)")
            need(b.note.strip(), "조치 결과를 입력하세요")
            con.execute("UPDATE defects SET status='검증중', action_result=? WHERE id=?", (b.note.strip(), did))
            add_event(con, did, b.actor_id, "조치 완료 보고", b.note.strip())
        elif b.action in ("verify", "reject"):
            need(role == "quality", "품질팀만 검증할 수 있습니다 (권한)")
            need(st == "검증중", "검증중 상태에서만 가능합니다")
            need(b.note.strip(), "검증 의견을 입력하세요")
            if b.action == "verify":
                con.execute("UPDATE defects SET status='종결', verify_note=?, closed_at=? WHERE id=?",
                            (b.note.strip(), fmt(now()), did))
                add_event(con, did, b.actor_id, "검증 후 종결", b.note.strip())
            else:
                con.execute("UPDATE defects SET status='조치중', verify_note=? WHERE id=?", (b.note.strip(), did))
                add_event(con, did, b.actor_id, "검증 반려", b.note.strip())
        else:
            raise HTTPException(422, "알 수 없는 동작입니다")
    return get_defect(did)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
