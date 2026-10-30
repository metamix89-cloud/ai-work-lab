"""두둑은행 대기 시스템 핵심 로직: DB, 대기열, 호출, 보류, 마스킹."""
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DUDUK_DB", os.path.join(os.path.dirname(__file__), "..", "duduk.db"))
FMT = "%Y-%m-%dT%H:%M:%S"
PRIORITY_MARGIN = timedelta(minutes=10)   # 예약 시각 앞뒤 10분
CALL_TIMEOUT = timedelta(minutes=3)       # 호출 후 3분
SERVICES = {"deposit": ("예금", "A"), "loan": ("대출", "B"), "fx": ("외환", "C")}
WINDOWS = {1: "deposit", 2: "deposit", 3: "loan", 4: "fx"}  # 창구 -> 업무
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

lock = threading.RLock()


def now() -> datetime:  # 테스트에서 교체 가능
    return datetime.now().replace(microsecond=0)


def ts(d: datetime) -> str:
    return d.strftime(FMT)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,                 -- reservation | walkin
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        account_last4 TEXT NOT NULL,        -- 계좌번호는 끝 4자리만 저장
        service TEXT NOT NULL,
        reserved_at TEXT,
        code TEXT UNIQUE,
        ticket_no TEXT,
        arrived_at TEXT,
        is_priority INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,               -- reserved|waiting|called|serving|done|hold
        window INTEGER,
        called_at TEXT, started_at TEXT, finished_at TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_status ON visits(status, service)")


def mask_name(name: str) -> str:
    n = len(name)
    if n <= 1:
        return name + "*"
    if n == 2:
        return name[0] + "*"
    return name[0] + "*" * (n - 2) + name[-1]


def _next_ticket(conn, service, day: str):
    prefix = SERVICES[service][1]
    c = conn.execute("SELECT COUNT(*) FROM visits WHERE service=? AND ticket_no IS NOT NULL AND arrived_at LIKE ?",
                     (service, day + "%")).fetchone()[0]
    return f"{prefix}{c + 1:03d}"


def create_reservation(conn, name, phone, last4, service, reserved_at: datetime):
    with lock:
        for _ in range(10):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            try:
                conn.execute("INSERT INTO visits(kind,name,phone,account_last4,service,reserved_at,code,status)"
                             " VALUES('reservation',?,?,?,?,?,?,'reserved')",
                             (name, phone, last4, service, ts(reserved_at), code))
                return code
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("code generation failed")


def _arrive(conn, vid, t: datetime):
    """도착 처리: 번호표 발급 + 우선 여부 확정(예약 시각 ±10분)."""
    row = conn.execute("SELECT * FROM visits WHERE id=?", (vid,)).fetchone()
    prio = 0
    if row["reserved_at"]:
        r = datetime.strptime(row["reserved_at"], FMT)
        prio = 1 if abs(t - r) <= PRIORITY_MARGIN else 0
    ticket = _next_ticket(conn, row["service"], t.strftime("%Y-%m-%d"))
    conn.execute("UPDATE visits SET ticket_no=?, arrived_at=?, is_priority=?, status='waiting' WHERE id=?",
                 (ticket, ts(t), prio, vid))
    return ticket, prio


def walk_in(conn, name, phone, last4, service):
    with lock:
        cur = conn.execute("INSERT INTO visits(kind,name,phone,account_last4,service,status)"
                           " VALUES('walkin',?,?,?,?,'waiting')", (name, phone, last4, service))
        return _arrive(conn, cur.lastrowid, now())


def check_in(conn, code):
    """예약 고객 도착 확인. 반환: (ticket, priority, name) 또는 None/에러 문자열."""
    with lock:
        row = conn.execute("SELECT * FROM visits WHERE code=?", (code,)).fetchone()
        if not row:
            return None
        if row["status"] != "reserved":
            return "already"
        t = now()
        if row["reserved_at"][:10] != t.strftime("%Y-%m-%d"):
            return "wrong_day"
        ticket, prio = _arrive(conn, row["id"], t)
        return ticket, prio, row["name"]


_ORDER = "is_priority DESC, CASE WHEN is_priority=1 THEN reserved_at ELSE arrived_at END, id"


def waiting_rows(conn, service=None):
    q = "SELECT * FROM visits WHERE status='waiting'"
    args = ()
    if service:
        q += " AND service=?"
        args = (service,)
    return conn.execute(q + " ORDER BY " + _ORDER, args).fetchall()


def window_busy(conn, window):
    return conn.execute("SELECT 1 FROM visits WHERE window=? AND status IN ('called','serving')",
                        (window,)).fetchone() is not None


def call_next(conn, window):
    """창구의 업무 고객 중 다음 사람을 호출. 이미 응대 중이면 'busy', 대기자 없으면 None."""
    with lock:
        if window_busy(conn, window):
            return "busy"
        row = conn.execute("SELECT * FROM visits WHERE status='waiting' AND service=? ORDER BY " + _ORDER + " LIMIT 1",
                           (WINDOWS[window],)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE visits SET status='called', window=?, called_at=? WHERE id=?",
                     (window, ts(now()), row["id"]))
        return row["id"]


def expire_calls(conn):
    """호출 후 3분 안에 안 온 고객은 보류, 그 창구는 다음 번호를 호출."""
    with lock:
        limit = ts(now() - CALL_TIMEOUT)
        rows = conn.execute("SELECT id, window FROM visits WHERE status='called' AND called_at<=?",
                            (limit,)).fetchall()
        for r in rows:
            conn.execute("UPDATE visits SET status='hold' WHERE id=?", (r["id"],))
            call_next(conn, r["window"])


def set_state(conn, window, from_states, to_state):
    """창구가 자기 담당 고객의 상태를 변경. 변경된 행 수 반환."""
    col = {"serving": "started_at", "done": "finished_at"}[to_state]
    marks = ",".join("?" * len(from_states))
    with lock:
        cur = conn.execute(f"UPDATE visits SET status=?, {col}=? WHERE window=? AND status IN ({marks})",
                           (to_state, ts(now()), window, *from_states))
        return cur.rowcount


def display_data(conn):
    """대기 화면용: 번호 · 가린 이름 · 창구 번호만."""
    calling = conn.execute("SELECT ticket_no, name, window, status FROM visits WHERE status IN ('called','serving')"
                           " ORDER BY called_at DESC").fetchall()
    waiting = waiting_rows(conn)[:12]
    return {
        "calling": [{"ticket": r["ticket_no"], "name": mask_name(r["name"]), "window": r["window"],
                     "state": r["status"]} for r in calling],
        "waiting": [{"ticket": r["ticket_no"], "name": mask_name(r["name"])} for r in waiting],
    }


def manager_summary(conn):
    """지점장용: 숫자만. 이름 · 연락처 · 계좌 없음."""
    t = now()
    day = t.strftime("%Y-%m-%d")
    out = {"services": {}, "windows": {}}
    for s, (label, _) in SERVICES.items():
        c = lambda st: conn.execute("SELECT COUNT(*) FROM visits WHERE service=? AND status=? AND "
                                    "COALESCE(arrived_at,reserved_at) LIKE ?", (s, st, day + "%")).fetchone()[0]
        out["services"][s] = {"label": label, "waiting": c("waiting"), "called": c("called"),
                              "serving": c("serving"), "done": c("done"), "hold": c("hold")}
    for w in WINDOWS:
        out["windows"][w] = {"service": SERVICES[WINDOWS[w]][0],
                             "busy": window_busy(conn, w),
                             "done": conn.execute("SELECT COUNT(*) FROM visits WHERE window=? AND status='done' "
                                                  "AND arrived_at LIKE ?", (w, day + "%")).fetchone()[0]}
    q = lambda sql, a=(): conn.execute(sql, a).fetchone()[0]
    out["priority_waiting"] = q("SELECT COUNT(*) FROM visits WHERE status='waiting' AND is_priority=1")
    out["total_waiting"] = q("SELECT COUNT(*) FROM visits WHERE status='waiting'")
    out["reservations_today"] = q("SELECT COUNT(*) FROM visits WHERE kind='reservation' AND reserved_at LIKE ?", (day + "%",))
    out["reservations_arrived"] = q("SELECT COUNT(*) FROM visits WHERE kind='reservation' AND reserved_at LIKE ? "
                                    "AND status!='reserved'", (day + "%",))
    out["reservation_no_show"] = q("SELECT COUNT(*) FROM visits WHERE status='reserved' AND reserved_at<=?",
                                   (ts(t - PRIORITY_MARGIN),))
    out["call_no_show"] = q("SELECT COUNT(*) FROM visits WHERE status='hold' AND called_at LIKE ?", (day + "%",))
    out["walkins_today"] = q("SELECT COUNT(*) FROM visits WHERE kind='walkin' AND arrived_at LIKE ?", (day + "%",))
    longest = conn.execute("SELECT MIN(arrived_at) FROM visits WHERE status='waiting'").fetchone()[0]
    out["longest_wait_min"] = int((t - datetime.strptime(longest, FMT)).total_seconds() // 60) if longest else 0
    return out
