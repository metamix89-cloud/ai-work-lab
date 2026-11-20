import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("PERMIT_DB", str(Path(__file__).resolve().parent.parent / "data" / "permits.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, company TEXT);
CREATE TABLE IF NOT EXISTS zones(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS permits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  applicant_id INTEGER NOT NULL REFERENCES users(id),
  zone_id INTEGER NOT NULL REFERENCES zones(id),
  work_type TEXT NOT NULL CHECK(work_type IN ('고소','화기','밀폐')),
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN ('requested','reviewed','approved','in_progress','completed','rejected')),
  checks_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  reviewer_id INTEGER, reviewed_at TEXT, review_comment TEXT,
  approver_id INTEGER, approved_at TEXT, valid_until TEXT,
  started_at TEXT, ended_at TEXT,
  rejected_by INTEGER, rejected_at TEXT, reject_reason TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, permit_id INTEGER NOT NULL,
  at TEXT NOT NULL, actor_id INTEGER NOT NULL, action TEXT NOT NULL, note TEXT);
"""


def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)  # 명시적 트랜잭션
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    con = connect()
    con.executescript(SCHEMA)
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    if n == 0:
        from .seed import seed
        seed()
