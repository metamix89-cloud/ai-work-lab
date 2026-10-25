import hashlib
import hmac
import os
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("RENTAL_DB", BASE / "data" / "rental.db"))
UPLOAD_DIR = BASE / "data" / "uploads"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('staff','customer')));
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vehicles(
  id INTEGER PRIMARY KEY, plate TEXT UNIQUE NOT NULL, model TEXT NOT NULL,
  daily_rate INTEGER NOT NULL, tank_l INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rentals(
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id),
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  start_at TEXT NOT NULL, due_at TEXT NOT NULL, start_odometer INTEGER NOT NULL, start_fuel INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','returned')),
  returned_at TEXT, ret_odometer INTEGER, ret_fuel INTEGER, inspected_by INTEGER REFERENCES users(id),
  total INTEGER);
CREATE TABLE IF NOT EXISTS uploads(
  id INTEGER PRIMARY KEY, filename TEXT NOT NULL, mime TEXT NOT NULL, uploaded_by INTEGER NOT NULL);
-- kind: 'pre' = 대여 시점에 이미 있던 흠집, 'return' = 반납 점검에서 기록한 흠집
CREATE TABLE IF NOT EXISTS damages(
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL REFERENCES rentals(id),
  kind TEXT NOT NULL CHECK(kind IN ('pre','return')), part TEXT NOT NULL, grade INTEGER NOT NULL,
  photo_id INTEGER REFERENCES uploads(id), note TEXT);
CREATE TABLE IF NOT EXISTS charges(
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL REFERENCES rentals(id),
  type TEXT NOT NULL, description TEXT NOT NULL, amount INTEGER NOT NULL, damage_id INTEGER REFERENCES damages(id));
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)  # 트랜잭션은 직접 관리
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


def hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + h.hex()


def verify_pw(pw: str, stored: str) -> bool:
    salt_hex, h_hex = stored.split("$")
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(h.hex(), h_hex)
