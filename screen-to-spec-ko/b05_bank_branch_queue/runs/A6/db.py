import os
import random
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DUDUK_DB", os.path.join(os.path.dirname(__file__), "duduk.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_no TEXT NOT NULL,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  account TEXT NOT NULL,
  service TEXT NOT NULL,
  kind TEXT NOT NULL,            -- reservation | walkin
  status TEXT NOT NULL,          -- reserved|waiting|called|serving|done|noshow
  reserved_at TEXT,
  created_at TEXT NOT NULL,
  checked_in_at TEXT,
  called_at TEXT,
  started_at TEXT,
  finished_at TEXT,
  counter INTEGER
);
CREATE INDEX IF NOT EXISTS ix_status ON tickets(status);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now().replace(microsecond=0)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
        seed(conn)
    conn.close()


def seed(conn):
    """Fictional demo data relative to the current time."""
    random.seed(7)
    t = now()
    names = ["김민수", "이서연", "박지훈", "최유나", "정다은", "강현우", "조은지", "윤성민",
             "장하늘", "임수빈", "한도윤", "오세진", "신예린", "배준호", "홍지아", "문태양"]
    letter = {"예금": "D", "대출": "L", "외환": "F"}
    seq = {}

    def add(name, service, kind, status, reserved=None, created=None, checked=None,
            called=None, started=None, finished=None, counter=None):
        seq[service] = seq.get(service, 0) + 1
        no = f"{letter[service]}{seq[service]:03d}"
        phone = f"010-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
        acct = f"{random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(100000, 999999)}"
        conn.execute(
            "INSERT INTO tickets(ticket_no,name,phone,account,service,kind,status,reserved_at,"
            "created_at,checked_in_at,called_at,started_at,finished_at,counter) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, name, phone, acct, service, kind, status,
             iso(reserved) if reserved else None, iso(created or t),
             iso(checked) if checked else None, iso(called) if called else None,
             iso(started) if started else None, iso(finished) if finished else None, counter))

    m = lambda n: t - timedelta(minutes=n)
    # finished earlier today
    add(names[0], "예금", "walkin", "done", created=m(80), checked=m(80), called=m(72), started=m(71), finished=m(65), counter=1)
    add(names[1], "대출", "reservation", "done", reserved=m(75), created=m(200), checked=m(76), called=m(70), started=m(69), finished=m(50), counter=3)
    add(names[2], "외환", "walkin", "done", created=m(60), checked=m(60), called=m(55), started=m(54), finished=m(45), counter=4)
    add(names[3], "예금", "reservation", "noshow", reserved=m(50), created=m(200))
    # now being served / called
    add(names[4], "예금", "walkin", "serving", created=m(25), checked=m(25), called=m(8), started=m(6), counter=1)
    add(names[5], "대출", "reservation", "called", reserved=m(20), created=m(300), checked=m(22), called=m(1), counter=3)
    # waiting: walk-ins arrived before the reservation holders, who still go first
    add(names[6], "예금", "walkin", "waiting", created=m(18), checked=m(18))
    add(names[7], "외환", "walkin", "waiting", created=m(15), checked=m(15))
    add(names[8], "예금", "reservation", "waiting", reserved=m(5), created=m(500), checked=m(6))
    add(names[9], "대출", "walkin", "waiting", created=m(9), checked=m(9))
    add(names[10], "예금", "walkin", "waiting", created=m(4), checked=m(4))
    # upcoming reservations (not yet arrived)
    add(names[11], "외환", "reservation", "reserved", reserved=t + timedelta(minutes=20), created=m(900))
    add(names[12], "대출", "reservation", "reserved", reserved=t + timedelta(minutes=45), created=m(900))
    add(names[13], "예금", "reservation", "reserved", reserved=t + timedelta(minutes=70), created=m(900))
    # reservation that just crossed the no-show window; the app will flag it on first request
    add(names[14], "예금", "reservation", "reserved", reserved=m(30), created=m(900))
