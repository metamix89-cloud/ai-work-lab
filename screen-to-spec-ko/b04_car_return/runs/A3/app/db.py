import os
import sqlite3

DATA_DIR = os.environ.get("RENTAL_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
DB_PATH = os.path.join(DATA_DIR, "rental.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('staff','customer')));
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vehicles(
  id INTEGER PRIMARY KEY, plate TEXT UNIQUE NOT NULL, model TEXT NOT NULL,
  daily_rate INTEGER NOT NULL, tank_liters REAL NOT NULL, odometer INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rentals(
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES users(id),
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  start_at TEXT NOT NULL, due_at TEXT NOT NULL,
  start_fuel INTEGER NOT NULL, start_odo INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'rented' CHECK(status IN ('rented','returned')),
  returned_at TEXT, return_fuel INTEGER, return_odo INTEGER, staff_id INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS photos(
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL REFERENCES rentals(id),
  filename TEXT NOT NULL, content_type TEXT NOT NULL, uploaded_by INTEGER NOT NULL);
-- phase: pickup = 대여 전부터 있던 흠집(비청구 기준), return = 반납 점검에서 기록
CREATE TABLE IF NOT EXISTS damages(
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL REFERENCES rentals(id),
  phase TEXT NOT NULL CHECK(phase IN ('pickup','return')),
  part TEXT NOT NULL, grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 3),
  note TEXT NOT NULL DEFAULT '', photo_id INTEGER REFERENCES photos(id),
  status TEXT, prior_grade INTEGER, fee INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY, rental_id INTEGER UNIQUE NOT NULL REFERENCES rentals(id),
  late_minutes INTEGER NOT NULL, late_fee INTEGER NOT NULL,
  fuel_short_units INTEGER NOT NULL, fuel_fee INTEGER NOT NULL,
  damage_fee INTEGER NOT NULL, total INTEGER NOT NULL, created_at TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)  # 요청당 1 연결, 순차 사용
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)


def get_con():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
