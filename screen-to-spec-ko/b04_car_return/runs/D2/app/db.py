import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RENTAL_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('staff','customer')), pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vehicles(
  id INTEGER PRIMARY KEY, plate TEXT UNIQUE NOT NULL, model TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rentals(
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES users(id),
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  started_at TEXT NOT NULL, due_at TEXT NOT NULL,
  start_fuel INTEGER NOT NULL CHECK(start_fuel BETWEEN 0 AND 8),
  start_odometer INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','returned')),
  returned_at TEXT, end_fuel INTEGER CHECK(end_fuel BETWEEN 0 AND 8), end_odometer INTEGER,
  inspected_by INTEGER REFERENCES users(id), total_charge INTEGER);
CREATE TABLE IF NOT EXISTS damages(
  id INTEGER PRIMARY KEY,
  rental_id INTEGER NOT NULL REFERENCES rentals(id),
  phase TEXT NOT NULL CHECK(phase IN ('pickup','return')),
  part TEXT NOT NULL, grade TEXT NOT NULL CHECK(grade IN ('minor','major','severe')),
  photo TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
  pre_existing_id INTEGER REFERENCES damages(id),
  pre_existing INTEGER NOT NULL DEFAULT 0, fee INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS charges(
  id INTEGER PRIMARY KEY,
  rental_id INTEGER NOT NULL REFERENCES rentals(id),
  kind TEXT NOT NULL CHECK(kind IN ('late','fuel','damage')),
  description TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount >= 0),
  damage_id INTEGER REFERENCES damages(id));
CREATE INDEX IF NOT EXISTS ix_rentals_customer ON rentals(customer_id);
CREATE INDEX IF NOT EXISTS ix_damages_rental ON damages(rental_id);
CREATE INDEX IF NOT EXISTS ix_charges_rental ON charges(rental_id);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None,
                           check_same_thread=False)  # 요청당 연결 1개, 순차 사용. 트랜잭션은 직접 BEGIN
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
