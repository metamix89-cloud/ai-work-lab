"""콩알반도체 불량 신고 · 조치 추적판 (FastAPI + SQLite)"""
import random
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "defects.db"

# 심각도별 조치 기한(시간)
SLA_HOURS = {"치명": 24, "중대": 72, "경미": 168}
STATUSES = ["신고", "분석중", "조치중", "검증중", "종결"]
LINES = ["FAB-1", "FAB-2", "PKG-A", "PKG-B", "TEST-1"]
DEFECT_TYPES = ["웨이퍼 스크래치", "본딩 와이어 단선", "몰딩 보이드", "솔더 브리지",
                "이물 오염", "치수 불량", "마킹 불량", "전기특성 이탈"]
QA_TEAM = ["박서연", "최도윤", "정하은"]
OWNERS = ["김민재", "이준호", "한지우", "오세린", "윤태양"]


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS defects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lot_no TEXT NOT NULL,
  product TEXT NOT NULL,
  line TEXT NOT NULL,
  defect_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  qty INTEGER NOT NULL DEFAULT 0,
  description TEXT NOT NULL,
  reporter TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '신고',
  analyst TEXT,
  root_cause TEXT,
  assignee TEXT,
  action_plan TEXT,
  reported_at TEXT NOT NULL,
  due_at TEXT NOT NULL,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  defect_id INTEGER NOT NULL REFERENCES defects(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  kind TEXT NOT NULL,
  note TEXT
);
"""


def log(con, defect_id, actor, kind, note="", at=None):
    con.execute("INSERT INTO events(defect_id, at, actor, kind, note) VALUES (?,?,?,?,?)",
                (defect_id, iso(at or now()), actor, kind, note))


def seed(con):
    if con.execute("SELECT COUNT(*) FROM defects").fetchone()[0]:
        return
    rnd = random.Random(84)
    products = ["KB-2201 MCU", "KB-3305 PMIC", "KB-4410 SRAM", "KB-5120 센서IC", "KB-6007 드라이버IC"]
    descs = {
        "웨이퍼 스크래치": "웨이퍼 외곽부에 선형 스크래치 발견, 현미경 검사에서 다이 {n}개 영향",
        "본딩 와이어 단선": "와이어 본딩 후 풀 테스트에서 단선 다수 발생",
        "몰딩 보이드": "X-ray 검사에서 몰딩 내부 보이드 확인",
        "솔더 브리지": "리플로우 후 인접 핀 간 솔더 브리지 발생",
        "이물 오염": "표면에 이물 오염 확인, 세정 공정 이후에도 잔류",
        "치수 불량": "패키지 두께가 규격 상한 초과",
        "마킹 불량": "레이저 마킹 흐림 및 위치 틀어짐",
        "전기특성 이탈": "최종 테스트에서 누설전류 규격 이탈 비율 증가",
    }
    # (경과 시간 h, 심각도, 목표 상태)
    plan = [
        (200, "치명", "조치중"), (120, "치명", "분석중"), (30, "치명", "조치중"),
        (20, "치명", "검증중"), (6, "치명", "신고"), (100, "중대", "조치중"),
        (90, "중대", "분석중"), (60, "중대", "검증중"), (40, "중대", "조치중"),
        (10, "중대", "신고"), (5, "중대", "분석중"), (400, "경미", "조치중"),
        (210, "경미", "신고"), (100, "경미", "분석중"), (50, "경미", "조치중"),
        (2, "경미", "신고"), (300, "치명", "종결"), (250, "중대", "종결"),
        (500, "경미", "종결"), (150, "중대", "종결"), (80, "경미", "종결"),
        (160, "경미", "검증중"),
    ]
    for i, (age_h, sev, target) in enumerate(plan):
        t0 = now() - timedelta(hours=age_h)
        dtype = rnd.choice(DEFECT_TYPES)
        lot = f"LOT-2610-{rnd.randint(100, 999)}"
        reporter = rnd.choice(["강현우", "송미래", "임도현", "배수아", "문지호"])
        desc = descs[dtype].format(n=rnd.randint(3, 40))
        cur = con.execute(
            "INSERT INTO defects(lot_no,product,line,defect_type,severity,qty,description,reporter,status,reported_at,due_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (lot, rnd.choice(products), rnd.choice(LINES), dtype, sev, rnd.randint(5, 600), desc, reporter,
             "신고", iso(t0), iso(t0 + timedelta(hours=SLA_HOURS[sev]))))
        did = cur.lastrowid
        log(con, did, reporter, "신고", desc, t0)
        step = t0
        idx = STATUSES.index(target)
        analyst = rnd.choice(QA_TEAM)
        owner = rnd.choice(OWNERS)
        if idx >= 1:
            step += timedelta(hours=min(2, age_h / 4))
            con.execute("UPDATE defects SET status='분석중', analyst=? WHERE id=?", (analyst, did))
            log(con, did, analyst, "접수", "품질팀 접수, 원인 분석 시작", step)
        if idx >= 2:
            step += timedelta(hours=min(6, age_h / 3))
            cause = rnd.choice(["본딩 캐필러리 마모", "클린룸 파티클 증가", "몰딩 컴파운드 수분 흡수",
                                "스텐실 개구부 오염", "장비 PM 주기 초과", "자재 로트 변경에 따른 편차"])
            plan_txt = rnd.choice(["장비 부품 교체 및 조건 재설정", "해당 로트 선별 및 격리 후 재검사",
                                   "작업 표준서 개정 및 교육", "공급사 시정조치 요청"])
            con.execute("UPDATE defects SET status='조치중', root_cause=?, assignee=?, action_plan=? WHERE id=?",
                        (cause, owner, plan_txt, did))
            log(con, did, analyst, "원인분석", f"원인: {cause} / 조치 계획: {plan_txt} / 담당: {owner}", step)
        if idx >= 3:
            step += timedelta(hours=min(8, age_h / 3))
            con.execute("UPDATE defects SET status='검증중' WHERE id=?", (did,))
            log(con, did, owner, "조치완료", "조치 완료, 검증 요청", step)
        if idx >= 4:
            step += timedelta(hours=min(4, age_h / 4))
            con.execute("UPDATE defects SET status='종결', closed_at=? WHERE id=?", (iso(step), did))
            log(con, did, analyst, "종결", "재발 여부 확인, 이상 없음으로 종결", step)
    con.commit()


@asynccontextmanager
async def lifespan(app):
    with closing(db()) as con:
        con.executescript(SCHEMA)
        seed(con)
    yield


app = FastAPI(title="콩알반도체 불량 신고 · 조치 추적판", lifespan=lifespan)


def row_out(r):
    d = dict(r)
    due = datetime.fromisoformat(d["due_at"])
    end = datetime.fromisoformat(d["closed_at"]) if d["closed_at"] else now()
    d["overdue"] = d["status"] != "종결" and due < end
    d["remaining_hours"] = None if d["status"] == "종결" else round((due - now()).total_seconds() / 3600, 1)
    return d


class NewDefect(BaseModel):
    lot_no: str = Field(min_length=1, max_length=40)
    product: str = Field(min_length=1, max_length=60)
    line: str
    defect_type: str
    severity: str
    qty: int = Field(ge=0, le=1_000_000)
    description: str = Field(min_length=1, max_length=1000)
    reporter: str = Field(min_length=1, max_length=30)


class Transition(BaseModel):
    action: str  # accept | analyze | complete | verify | reject | comment
    actor: str = Field(min_length=1, max_length=30)
    note: str = ""
    root_cause: str | None = None
    assignee: str | None = None
    action_plan: str | None = None


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/meta")
def meta():
    return {"sla_hours": SLA_HOURS, "statuses": STATUSES, "lines": LINES, "defect_types": DEFECT_TYPES,
            "qa_team": QA_TEAM, "owners": OWNERS}


@app.get("/api/defects")
def list_defects(status: str | None = None, severity: str | None = None, assignee: str | None = None,
                 overdue: bool = False, q: str | None = None, open_only: bool = False):
    sql, args = "SELECT * FROM defects WHERE 1=1", []
    if status:
        sql += " AND status=?"; args.append(status)
    if severity:
        sql += " AND severity=?"; args.append(severity)
    if assignee:
        sql += " AND assignee=?"; args.append(assignee)
    if open_only:
        sql += " AND status!='종결'"
    if q:
        sql += " AND (lot_no LIKE ? OR product LIKE ? OR description LIKE ?)"
        args += [f"%{q}%"] * 3
    with closing(db()) as con:
        rows = [row_out(r) for r in con.execute(sql, args)]
    if overdue:
        rows = [r for r in rows if r["overdue"]]
    # 기한 초과 → 임박 순, 종결 건은 뒤로
    rows.sort(key=lambda r: (r["status"] == "종결", r["due_at"]))
    return rows


@app.get("/api/summary")
def summary():
    with closing(db()) as con:
        rows = [row_out(r) for r in con.execute("SELECT * FROM defects")]
    open_rows = [r for r in rows if r["status"] != "종결"]
    by_status = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    people = {}
    for r in open_rows:
        who = r["assignee"] or "(미배정)"
        p = people.setdefault(who, {"name": who, "open": 0, "overdue": 0, "critical": 0})
        p["open"] += 1
        p["overdue"] += r["overdue"]
        p["critical"] += r["severity"] == "치명"
    return {
        "total": len(rows),
        "open": len(open_rows),
        "overdue": sum(r["overdue"] for r in open_rows),
        "due_soon": sum(1 for r in open_rows if not r["overdue"] and r["remaining_hours"] <= 12),
        "unassigned": sum(1 for r in open_rows if not r["assignee"]),
        "by_status": by_status,
        "overdue_by_severity": {s: sum(1 for r in open_rows if r["overdue"] and r["severity"] == s) for s in SLA_HOURS},
        "people": sorted(people.values(), key=lambda p: (-p["overdue"], -p["open"])),
    }


@app.post("/api/defects", status_code=201)
def create_defect(body: NewDefect):
    if body.severity not in SLA_HOURS:
        raise HTTPException(422, "심각도는 치명/중대/경미 중 하나여야 합니다.")
    t = now()
    with closing(db()) as con:
        cur = con.execute(
            "INSERT INTO defects(lot_no,product,line,defect_type,severity,qty,description,reporter,status,reported_at,due_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (body.lot_no.strip(), body.product.strip(), body.line, body.defect_type, body.severity, body.qty,
             body.description.strip(), body.reporter.strip(), "신고", iso(t), iso(t + timedelta(hours=SLA_HOURS[body.severity]))))
        log(con, cur.lastrowid, body.reporter.strip(), "신고", body.description.strip(), t)
        con.commit()
        return row_out(con.execute("SELECT * FROM defects WHERE id=?", (cur.lastrowid,)).fetchone())


@app.get("/api/defects/{did}")
def get_defect(did: int):
    with closing(db()) as con:
        r = con.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone()
        if not r:
            raise HTTPException(404, "없는 건입니다.")
        ev = [dict(e) for e in con.execute("SELECT * FROM events WHERE defect_id=? ORDER BY id", (did,))]
    return {**row_out(r), "events": ev}


@app.post("/api/defects/{did}/transition")
def transition(did: int, body: Transition):
    actor, note = body.actor.strip(), body.note.strip()
    with closing(db()) as con:
        r = con.execute("SELECT * FROM defects WHERE id=?", (did,)).fetchone()
        if not r:
            raise HTTPException(404, "없는 건입니다.")
        st = r["status"]

        def need(cond, msg):
            if not cond:
                raise HTTPException(422, msg)

        a = body.action
        if a == "comment":
            need(note, "내용을 입력하세요.")
            log(con, did, actor, "메모", note)
        elif a == "accept":
            need(st == "신고", "신고 상태에서만 접수할 수 있습니다.")
            con.execute("UPDATE defects SET status='분석중', analyst=? WHERE id=?", (actor, did))
            log(con, did, actor, "접수", note or "품질팀 접수, 원인 분석 시작")
        elif a == "analyze":
            need(st == "분석중", "분석중 상태에서만 가능합니다.")
            rc, who, plan = (body.root_cause or "").strip(), (body.assignee or "").strip(), (body.action_plan or "").strip()
            need(rc and who and plan, "원인, 담당자, 조치 계획을 모두 입력하세요.")
            con.execute("UPDATE defects SET status='조치중', root_cause=?, assignee=?, action_plan=? WHERE id=?",
                        (rc, who, plan, did))
            log(con, did, actor, "원인분석", f"원인: {rc} / 조치 계획: {plan} / 담당: {who}")
        elif a == "complete":
            need(st == "조치중", "조치중 상태에서만 가능합니다.")
            need(note, "조치 결과를 입력하세요.")
            con.execute("UPDATE defects SET status='검증중' WHERE id=?", (did,))
            log(con, did, actor, "조치완료", note)
        elif a == "verify":
            need(st == "검증중", "검증중 상태에서만 가능합니다.")
            need(note, "검증 결과를 입력하세요.")
            con.execute("UPDATE defects SET status='종결', closed_at=? WHERE id=?", (iso(now()), did))
            log(con, did, actor, "종결", note)
        elif a == "reject":
            need(st == "검증중", "검증중 상태에서만 가능합니다.")
            need(note, "반려 사유를 입력하세요.")
            con.execute("UPDATE defects SET status='조치중' WHERE id=?", (did,))
            log(con, did, actor, "검증반려", note)
        else:
            raise HTTPException(422, "알 수 없는 동작입니다.")
        con.commit()
    return get_defect(did)


@app.post("/api/reset")
def reset():
    """데모 데이터 초기화"""
    with closing(db()) as con:
        con.executescript("DELETE FROM events; DELETE FROM defects; DELETE FROM sqlite_sequence;")
        seed(con)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
