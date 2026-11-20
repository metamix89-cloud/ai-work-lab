# -*- coding: utf-8 -*-
"""ep097 채점기 자가 시험용 앱 3벌을 base/ 에서 만든다 (화면 · seed 는 base 그대로, main.py 의 예약 만들기 · 취소만 바꾼다).
  ref_a   정답 — mr_reservations 에 series_id 칸을 더한 구조
  ref_b   정답 — 예약 표는 그대로 두고 mr_series_items(res_id, series_id) 표를 따로 둔 구조
  trap    흔한 실수 — 겹치는 주만 빼고 만든다 · 횟수 범위 검사 없음 · '남은 전부' 가 묶음 전체를 본인 확인 없이 지운다
사용: python _scratch/s2s/20_feature_regression/selftest/make_refs.py"""
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..", "base")

HEAD = '''# -*- coding: utf-8 -*-
import csv
import datetime
import os
import re
import sqlite3
import threading

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "rooms.db")
SEED = os.path.join(BASE, "seed")
LOCK = threading.Lock()
TIME_RE = re.compile(r"^([01]\\d|2[0-3]):[0-5]\\d$")
COLS = "r.res_id, r.room_id, r.date, r.start, r.end, r.user"


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE mr_rooms (room_id TEXT PRIMARY KEY, name TEXT, capacity INTEGER)")
    con.execute("CREATE TABLE mr_users (user TEXT PRIMARY KEY)")
    con.execute("CREATE TABLE mr_reservations (res_id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, "
                "date TEXT, start TEXT, end TEXT, user TEXT%(extra_col)s)")
    %(extra_table)s
    for r in read_csv("rooms.csv"):
        con.execute("INSERT INTO mr_rooms VALUES (?,?,?)", (r["room_id"], r["name"], int(r["capacity"])))
    for r in read_csv("users.csv"):
        con.execute("INSERT INTO mr_users VALUES (?)", (r["user"],))
    for r in read_csv("reservations.csv"):
        con.execute("INSERT INTO mr_reservations (res_id, room_id, date, start, end, user) VALUES (?,?,?,?,?,?)",
                    (int(r["res_id"]), r["room_id"], r["date"], r["start"], r["end"], r["user"]))
    con.commit()
    con.close()


init_db()
app = FastAPI()


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


def minutes(t):
    return int(t[:2]) * 60 + int(t[3:])


def week_dates(date, n):
    d = datetime.date.fromisoformat(date)
    return [(d + datetime.timedelta(days=7 * k)).isoformat() for k in range(n)]


@app.get("/api/rooms")
def rooms():
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT room_id, name, capacity FROM mr_rooms ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/users")
def users():
    con = db()
    try:
        return [r["user"] for r in con.execute("SELECT user FROM mr_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/reservations")
def list_reservations(date: str = Query(...)):
    con = db()
    try:
        return [dict(r) for r in con.execute(%(list_sql)s, (date,))]
    finally:
        con.close()


@app.post("/api/reservations")
def create(body: dict):
    vals = {k: body.get(k) for k in ("room_id", "date", "start", "end", "user")}
    if any(not isinstance(v, str) or not v.strip() for v in vals.values()):
        return err(400, "모든 값을 입력해 주세요")
    s, e = vals["start"], vals["end"]
    if not (TIME_RE.match(s) and TIME_RE.match(e)) or s[3:] not in ("00", "30") or e[3:] not in ("00", "30"):
        return err(400, "30분 단위로만 예약할 수 있습니다")
    if s < "09:00" or e > "18:00" or e <= s:
        return err(400, "예약 가능 시간은 09:00~18:00 입니다")
    if minutes(e) - minutes(s) > 120:
        return err(400, "한 번에 최대 2시간까지 예약할 수 있습니다")
    weeks = body.get("repeat_weeks")
    repeat = weeks is not None
%(range_check)s
    try:
        dates = week_dates(vals["date"], weeks if repeat else 1)
    except (ValueError, TypeError):
        return err(400, "모든 값을 입력해 주세요")
    con = db()
    try:
        with LOCK:
            if not con.execute("SELECT 1 FROM mr_rooms WHERE room_id=?", (vals["room_id"],)).fetchone():
                return err(404, "회의실을 찾을 수 없습니다")
            clash = [d for d in dates if con.execute(
                "SELECT 1 FROM mr_reservations WHERE room_id=? AND date=? AND ? < end AND ? > start",
                (vals["room_id"], d, s, e)).fetchone()]
%(clash_rule)s
            made = []
            series_id = None
            for d in dates:
                cur = con.execute("INSERT INTO mr_reservations (room_id, date, start, end, user) VALUES (?,?,?,?,?)",
                                  (vals["room_id"], d, s, e, vals["user"]))
                res_id = cur.lastrowid
                if repeat:
                    series_id = series_id or res_id
%(link)s
                made.append({"res_id": res_id, **vals, "date": d, "series_id": series_id})
            con.commit()
    finally:
        con.close()
    if not repeat:
        one = dict(made[0])
        one.pop("series_id")
        return JSONResponse(one, status_code=201)
    return JSONResponse({"series_id": series_id, "reservations": made}, status_code=201)


@app.delete("/api/reservations/{res_id}")
def cancel(res_id: int, user: str = "", scope: str = "one"):
    con = db()
    try:
        with LOCK:
            row = con.execute(%(one_sql)s, (res_id,)).fetchone()
            if not row:
                return err(404, "예약을 찾을 수 없습니다")
%(cancel_body)s
            con.commit()
    finally:
        con.close()
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
'''

RANGE_OK = '''    if repeat and (isinstance(weeks, bool) or not isinstance(weeks, int) or not 2 <= weeks <= 8):
        return err(400, "반복은 2주에서 8주까지 가능합니다")'''
RANGE_TRAP = '''    if repeat and not isinstance(weeks, int):
        return err(400, "반복 횟수는 숫자여야 합니다")
    if repeat and weeks < 1:
        weeks = 1'''
CLASH_OK = '''            if clash:
                return err(409, "반복 예약 중 겹치는 날짜가 있습니다" if repeat else "이미 예약된 시간입니다")'''
CLASH_TRAP = '''            if clash and not repeat:
                return err(409, "이미 예약된 시간입니다")
            dates = [d for d in dates if d not in clash]   # 함정: 겹치는 주만 빼고 만든다
            if not dates:
                return err(409, "이미 예약된 시간입니다")'''
OWNER = '''            if row["user"] != user:
                return err(403, "본인 예약만 취소할 수 있습니다")
'''

A = dict(
    extra_col=", series_id INTEGER", extra_table="pass",
    list_sql='"SELECT %s, r.series_id FROM mr_reservations r WHERE r.date=? ORDER BY r.start, r.res_id" % COLS',
    link='                    con.execute("UPDATE mr_reservations SET series_id=? WHERE res_id=?", (series_id, res_id))',
    one_sql='"SELECT user, date, series_id FROM mr_reservations WHERE res_id=?"',
    range_check=RANGE_OK, clash_rule=CLASH_OK,
    cancel_body=OWNER + '''            if scope == "following" and row["series_id"] is not None:
                con.execute("DELETE FROM mr_reservations WHERE series_id=? AND date>=?", (row["series_id"], row["date"]))
            else:
                con.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))''')

B = dict(
    extra_col="", extra_table='con.execute("CREATE TABLE mr_series_items (res_id INTEGER PRIMARY KEY, series_id INTEGER)")',
    list_sql='"SELECT %s, i.series_id FROM mr_reservations r LEFT JOIN mr_series_items i ON i.res_id=r.res_id "\n'
             '                                              "WHERE r.date=? ORDER BY r.start, r.res_id" % COLS',
    link='                    con.execute("INSERT INTO mr_series_items VALUES (?,?)", (res_id, series_id))',
    one_sql='"SELECT r.user, r.date, i.series_id FROM mr_reservations r LEFT JOIN mr_series_items i ON i.res_id=r.res_id WHERE r.res_id=?"',
    range_check=RANGE_OK, clash_rule=CLASH_OK,
    cancel_body=OWNER + '''            if scope == "following" and row["series_id"] is not None:
                ids = [r[0] for r in con.execute("SELECT r.res_id FROM mr_reservations r JOIN mr_series_items i ON i.res_id=r.res_id "
                                                 "WHERE i.series_id=? AND r.date>=?", (row["series_id"], row["date"]))]
            else:
                ids = [res_id]
            for i in ids:
                con.execute("DELETE FROM mr_reservations WHERE res_id=?", (i,))
                con.execute("DELETE FROM mr_series_items WHERE res_id=?", (i,))''')

TRAP = dict(A, range_check=RANGE_TRAP, clash_rule=CLASH_TRAP,
            cancel_body='''            if scope == "following" and row["series_id"] is not None:
                con.execute("DELETE FROM mr_reservations WHERE series_id=?", (row["series_id"],))   # 함정: 본인 확인 없이 묶음 전체
            else:
                if row["user"] != user:
                    return err(403, "본인 예약만 취소할 수 있습니다")
                con.execute("DELETE FROM mr_reservations WHERE res_id=?", (res_id,))''')

for name, spec in (("ref_a", A), ("ref_b", B), ("trap", TRAP)):
    dst = os.path.join(HERE, name)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    shutil.copytree(os.path.join(BASE, "seed"), os.path.join(dst, "seed"))
    shutil.copytree(os.path.join(BASE, "static"), os.path.join(dst, "static"))
    with open(os.path.join(dst, "main.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(HEAD % spec)
    print("썼음:", name)
