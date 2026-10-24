import calendar
import csv
import os
import random
import re
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

BASE = Path(__file__).parent
SEED = BASE / "seed"
DB_PATH = BASE / "duty.db"
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

app = FastAPI()


class ApiError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return JSONResponse({"detail": e.detail}, status_code=e.status)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, e: RequestValidationError):
    return JSONResponse({"detail": "입력이 올바르지 않습니다"}, status_code=400)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, e: StarletteHTTPException):
    return JSONResponse({"detail": str(e.detail)}, status_code=e.status_code)


# ---------- DB ----------

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    con = db()
    con.executescript(
        """
        DROP TABLE IF EXISTS dt_staff;
        DROP TABLE IF EXISTS dt_unavailable;
        DROP TABLE IF EXISTS dt_roster;
        CREATE TABLE dt_staff (name TEXT PRIMARY KEY, grade TEXT, ord INTEGER);
        CREATE TABLE dt_unavailable (name TEXT, date TEXT, reason TEXT);
        CREATE TABLE dt_roster (date TEXT PRIMARY KEY, name TEXT, confirmed INTEGER);
        """
    )
    for i, r in enumerate(read_csv("staff.csv")):
        con.execute("INSERT INTO dt_staff VALUES (?,?,?)", (r["name"].strip(), r["grade"].strip(), i))
    for r in read_csv("unavailable.csv"):
        con.execute(
            "INSERT INTO dt_unavailable VALUES (?,?,?)",
            (r["name"].strip(), r["date"].strip(), r["reason"].strip()),
        )
    for r in read_csv("roster.csv"):
        con.execute(
            "INSERT OR REPLACE INTO dt_roster VALUES (?,?,?)",
            (r["date"].strip(), r["name"].strip(), int(r["confirmed"])),
        )
    con.commit()
    con.close()


init_db()


# ---------- helpers ----------

def parse_month(month):
    if not isinstance(month, str) or not MONTH_RE.match(month):
        raise ApiError(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    y, m = int(month[:4]), int(month[5:])
    if not 1 <= m <= 12:
        raise ApiError(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    return y, m


def month_days(month):
    y, m = parse_month(month)
    return [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def parse_date(s):
    try:
        if not isinstance(s, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            raise ValueError
        return date.fromisoformat(s)
    except ValueError:
        raise ApiError(400, "존재하지 않는 날짜입니다")


def staff_list(con):
    return [dict(r) for r in con.execute("SELECT name, grade FROM dt_staff ORDER BY ord")]


def roster_of(con, month):
    days = month_days(month)
    rows = {
        r["date"]: r
        for r in con.execute(
            "SELECT date, name, confirmed FROM dt_roster WHERE date LIKE ?", (month + "-%",)
        )
    }
    out = [
        {
            "date": d.isoformat(),
            "name": rows[d.isoformat()]["name"] if d.isoformat() in rows else "",
            "weekend": d.weekday() >= 5,
        }
        for d in days
    ]
    if not rows:
        status = "미생성"
    elif len(rows) == len(days) and all(r["confirmed"] for r in rows.values()):
        status = "확정"
    else:
        status = "생성됨"
    return {"month": month, "status": status, "days": out}


def name_on(con, d):
    r = con.execute("SELECT name FROM dt_roster WHERE date=?", (d.isoformat(),)).fetchone()
    return r["name"] if r else None


# ---------- generation (R1~R5) ----------

def solve(days, names, blocked, prev_name, next_name, deadline):
    n, k = len(days), len(names)
    weekend = [d.weekday() >= 5 for d in days]
    wtotal = sum(weekend)
    t_lo, t_hi = n // k, -(-n // k)
    w_lo, w_hi = wtotal // k, -(-wtotal // k)
    rest_w = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        rest_w[i] = rest_w[i + 1] + (1 if weekend[i] else 0)

    for attempt in range(10000):
        rnd = random.Random(attempt)
        tot = dict.fromkeys(names, 0)
        wk = dict.fromkeys(names, 0)
        plan = [None] * n
        state = {"nodes": 0, "cut": False}
        budget = 30000

        def dfs(i):
            if i == n:
                return True
            state["nodes"] += 1
            if state["nodes"] > budget:
                state["cut"] = True
                return False
            if time.monotonic() > deadline:
                state["cut"] = True
                return False
            remaining = n - i
            if sum(max(0, t_lo - tot[p]) for p in names) > remaining:
                return False
            if sum(max(0, w_lo - wk[p]) for p in names) > rest_w[i]:
                return False
            prev = plan[i - 1] if i else prev_name
            w = weekend[i]
            cands = []
            for p in names:
                if p == prev or (d_iso(days[i]), p) in blocked:
                    continue
                if i == n - 1 and p == next_name:
                    continue
                if tot[p] >= t_hi or (w and wk[p] >= w_hi):
                    continue
                cands.append(p)
            rnd.shuffle(cands)
            cands.sort(key=lambda p: (tot[p], wk[p] if w else 0))
            for p in cands:
                plan[i] = p
                tot[p] += 1
                if w:
                    wk[p] += 1
                if dfs(i + 1):
                    return True
                tot[p] -= 1
                if w:
                    wk[p] -= 1
                plan[i] = None
            return False

        if dfs(0):
            return plan
        if not state["cut"]:
            return None  # 전체 탐색 완료: 불가능
        if time.monotonic() > deadline:
            return None
    return None


def d_iso(d):
    return d.isoformat()


# ---------- API ----------

@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/staff")
def api_staff():
    con = db()
    try:
        return staff_list(con)
    finally:
        con.close()


@app.get("/api/unavailable")
def api_unavailable(month: str):
    parse_month(month)
    con = db()
    try:
        return [
            dict(r)
            for r in con.execute(
                "SELECT name, date, reason FROM dt_unavailable WHERE date LIKE ? ORDER BY date, name",
                (month + "-%",),
            )
        ]
    finally:
        con.close()


@app.get("/api/roster")
def api_roster(month: str):
    parse_month(month)
    con = db()
    try:
        return roster_of(con, month)
    finally:
        con.close()


@app.post("/api/roster/generate")
def api_generate(body: dict):
    month = body.get("month")
    days = month_days(month)
    con = db()
    try:
        if roster_of(con, month)["status"] == "확정":
            raise ApiError(409, "확정된 달은 다시 생성할 수 없습니다")
        names = [s["name"] for s in staff_list(con)]
        blocked = {
            (r["date"], r["name"])
            for r in con.execute(
                "SELECT name, date FROM dt_unavailable WHERE date LIKE ?", (month + "-%",)
            )
        }
        prev_name = name_on(con, days[0] - timedelta(days=1))
        next_name = name_on(con, days[-1] + timedelta(days=1))
        plan = solve(days, names, blocked, prev_name, next_name, time.monotonic() + 2.5) if names else None
        if plan is None:
            raise ApiError(422, "규칙을 만족하는 순번을 만들 수 없습니다")
        con.execute("DELETE FROM dt_roster WHERE date LIKE ?", (month + "-%",))
        con.executemany(
            "INSERT INTO dt_roster VALUES (?,?,0)", [(d.isoformat(), p) for d, p in zip(days, plan)]
        )
        con.commit()
        return roster_of(con, month)
    finally:
        con.close()


@app.post("/api/roster/swap")
def api_swap(body: dict):
    a, b = parse_date(body.get("date_a")), parse_date(body.get("date_b"))
    if a == b:
        raise ApiError(400, "같은 날짜끼리는 바꿀 수 없습니다")
    con = db()
    try:
        na, nb = name_on(con, a), name_on(con, b)
        if na is None or nb is None:
            raise ApiError(400, "순번이 없는 날짜입니다 (미생성 달)")
        new = {a: nb, b: na}

        def at(d):
            return new[d] if d in new else name_on(con, d)

        for d, who in new.items():
            hit = con.execute(
                "SELECT 1 FROM dt_unavailable WHERE name=? AND date=?", (who, d.isoformat())
            ).fetchone()
            if hit:
                raise ApiError(409, f"R2 위반: {who} 님은 {d.isoformat()} 에 제외일입니다")
        for d, who in new.items():
            for nd in (d - timedelta(days=1), d + timedelta(days=1)):
                if at(nd) == who:
                    raise ApiError(409, f"R3 위반: {who} 님이 {min(d, nd).isoformat()} · {max(d, nd).isoformat()} 연속 당직이 됩니다")
        for d, who in new.items():
            con.execute("UPDATE dt_roster SET name=? WHERE date=?", (who, d.isoformat()))
        con.commit()
        return roster_of(con, d_iso(a)[:7])
    finally:
        con.close()


@app.post("/api/roster/confirm")
def api_confirm(body: dict):
    month = body.get("month")
    parse_month(month)
    con = db()
    try:
        if roster_of(con, month)["status"] == "미생성":
            raise ApiError(400, "순번이 없는 달은 확정할 수 없습니다")
        con.execute("UPDATE dt_roster SET confirmed=1 WHERE date LIKE ?", (month + "-%",))
        con.commit()
        return roster_of(con, month)
    finally:
        con.close()


@app.get("/api/stats")
def api_stats(month: str):
    parse_month(month)
    con = db()
    try:
        stats = {s["name"]: {"name": s["name"], "total": 0, "weekend": 0} for s in staff_list(con)}
        for r in con.execute("SELECT date, name FROM dt_roster WHERE date LIKE ?", (month + "-%",)):
            if r["name"] in stats:
                stats[r["name"]]["total"] += 1
                if date.fromisoformat(r["date"]).weekday() >= 5:
                    stats[r["name"]]["weekend"] += 1
        return list(stats.values())
    finally:
        con.close()
