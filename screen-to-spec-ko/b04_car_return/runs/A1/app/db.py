import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("BRL_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "rental.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('staff','customer')), pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vehicles (
  id INTEGER PRIMARY KEY, plate TEXT UNIQUE NOT NULL, model TEXT NOT NULL,
  tank_liters INTEGER NOT NULL, daily_rate INTEGER NOT NULL, odometer INTEGER NOT NULL
);
-- 차량이 현재 안고 있는 흠집(부위당 1건, 최고 등급). 새 대여 시작 시 대여별 'pickup' 기록으로 복사된다.
CREATE TABLE IF NOT EXISTS vehicle_damage (
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id), part TEXT NOT NULL, grade INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT '', photo TEXT, PRIMARY KEY (vehicle_id, part)
);
CREATE TABLE IF NOT EXISTS rentals (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  start_at TEXT NOT NULL, due_at TEXT NOT NULL, start_fuel INTEGER NOT NULL, start_odometer INTEGER NOT NULL,
  daily_rate INTEGER NOT NULL, status TEXT NOT NULL CHECK (status IN ('active','returned')),
  returned_at TEXT, return_fuel INTEGER, return_odometer INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_vehicle ON rentals(vehicle_id) WHERE status = 'active';
CREATE TABLE IF NOT EXISTS rental_damage (
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL REFERENCES rentals(id),
  phase TEXT NOT NULL CHECK (phase IN ('pickup','return')),
  part TEXT NOT NULL, grade INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '', photo TEXT,
  fee INTEGER NOT NULL DEFAULT 0, status TEXT,
  UNIQUE (rental_id, phase, part)
);
CREATE TABLE IF NOT EXISTS invoices (
  rental_id INTEGER PRIMARY KEY REFERENCES rentals(id), late_minutes INTEGER NOT NULL, late_fee INTEGER NOT NULL,
  fuel_short INTEGER NOT NULL, fuel_fee INTEGER NOT NULL, damage_fee INTEGER NOT NULL, total INTEGER NOT NULL,
  created_at TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id)
);
"""


def connect():
    db = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


@contextmanager
def tx(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def hash_pw(password: str, salt: str | None = None):
    salt = salt or os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return salt, h


def check_pw(password: str, salt: str, expected: str) -> bool:
    return hmac.compare_digest(hash_pw(password, salt)[1], expected)


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    db = connect()
    db.executescript(SCHEMA)
    return db
