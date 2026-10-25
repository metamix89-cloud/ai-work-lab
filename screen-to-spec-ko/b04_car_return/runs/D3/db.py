import hashlib
import hmac
import os
import sqlite3
from pathlib import Path

BASE = Path(__file__).parent
DB_PATH = Path(os.environ.get("BRR_DB", BASE / "data" / "app.db"))
UPLOAD_DIR = Path(os.environ.get("BRR_UPLOADS", BASE / "data" / "uploads"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('staff','customer')));
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS cars(id INTEGER PRIMARY KEY, plate TEXT UNIQUE NOT NULL, model TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rentals(
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id),
  car_id INTEGER NOT NULL REFERENCES cars(id),
  start_at TEXT NOT NULL, due_at TEXT NOT NULL,
  start_fuel INTEGER NOT NULL CHECK(start_fuel BETWEEN 0 AND 8),
  start_odometer INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','returned')));
CREATE TABLE IF NOT EXISTS photos(
  id INTEGER PRIMARY KEY, filename TEXT NOT NULL, mime TEXT NOT NULL,
  uploaded_by INTEGER NOT NULL REFERENCES users(id), attached INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rental_damages(
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL REFERENCES rentals(id),
  phase TEXT NOT NULL CHECK(phase IN ('checkout','return')),
  part TEXT NOT NULL, grade TEXT NOT NULL CHECK(grade IN ('minor','major','severe')),
  photo_id INTEGER NOT NULL REFERENCES photos(id),
  pre_existing INTEGER NOT NULL DEFAULT 0, fee INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS returns(
  rental_id INTEGER PRIMARY KEY REFERENCES rentals(id),
  returned_at TEXT NOT NULL, fuel INTEGER NOT NULL, odometer INTEGER NOT NULL,
  late_minutes INTEGER NOT NULL, late_fee INTEGER NOT NULL,
  fuel_short INTEGER NOT NULL, fuel_fee INTEGER NOT NULL,
  damage_fee INTEGER NOT NULL, total INTEGER NOT NULL,
  staff_id INTEGER NOT NULL REFERENCES users(id));
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)  # 트랜잭션은 직접 관리
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init():
    con = connect()
    con.executescript(SCHEMA)
    con.close()


def hash_pw(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + "$" + h.hex()


def check_pw(password: str, stored: str) -> bool:
    salt, h = stored.split("$")
    return hmac.compare_digest(hash_pw(password, bytes.fromhex(salt)).split("$")[1], h)
