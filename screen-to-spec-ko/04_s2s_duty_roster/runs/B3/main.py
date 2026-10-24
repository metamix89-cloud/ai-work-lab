import calendar
import csv
import os
import re
import sqlite3
import time
from datetime import date, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "duty.db")
SEED = os.path.join(BASE, "seed")
GEN_TIMEOUT = 2.5

app = FastAPI()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = db()
    con.executescript(
        """
        CREATE TABLE dt_staff (name TEXT PRIMARY KEY, grade TEXT);
        CREATE TABLE dt_unavailable (name TEXT, date TEXT, reason TEXT);
        CREATE TABLE dt_roster (date TEXT PRIMARY KEY, name TEXT, confirmed INTEGER DEFAULT 0);
        """
    )
    con.executemany("INSERT INTO dt_staff VALUES (?,?)",
                    [(r["name"], r["grade"]) for r in read_csv("staff.csv")])
    con.executemany("INSERT INTO dt_unavailable VALUES (?,?,?)",
                    [(r["name"], r["date"], r["reason"]) for r in read_csv("unavailable.csv")])
    con.executemany("INSERT OR REPLACE INTO dt_roster VALUES (?,?,?)",
                    [(r["date"], r["name"], int(r["confirmed"])) for r in read_csv("roster.csv")])
    con.commit()
    con.close()


init_db()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


def parse_month(month):
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise Reject(400, "월 형식은 YYYY-MM 이어야 합니다")
    y, m = int(month[:4]), int(month[5:])
    if not 1 <= m <= 12 or y < 1:
        raise Reject(400, "월 형식은 YYYY-MM 이어야 합니다")
    return y, m


def month_dates(month):
    y, m = parse_month(month)
    return [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def parse_date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise Reject(400, "없는 날짜입니다")


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    if not isinstance(data, dict):
        raise Reject(400, "요청 본문이 올바르지 않습니다")
    return data


def build_roster(con, month):
    dates = month_dates(month)
    rows = {r["date"]: r for r in con.execute(
        "SELECT * FROM dt_roster WHERE date LIKE ?", (month + "-%",))}
    if not rows:
        status = "미생성"
    elif any(r["confirmed"] for r in rows.values()):
        status = "확정"
    else:
        status = "생성됨"
    days = [{"date": d.isoformat(),
             "name": rows[d.isoformat()]["name"] if d.isoformat() in rows else "",
             "weekend": d.weekday() >= 5} for d in dates]
    return {"month": month, "status": status, "days": days}


def generate(dates, staff, unavail, prev_name):
    """DFS 백트래킹: R1~R5 를 모두 만족하는 배정을 찾는다."""
    n, k = len(dates), len(staff)
    wk = [d.weekday() >= 5 for d in dates]
    n_wk = sum(wk)
    lo, hi = n // k, -(-n // k)
    wlo, whi = n_wk // k, -(-n_wk // k)
    total = {s: 0 for s in staff}
    weekend = {s: 0 for s in staff}
    result = [None] * n
    deadline = time.monotonic() + GEN_TIMEOUT
    # 하루 후보가 적은 날부터가 아니라 날짜 순으로 진행, 후보는 적게 선 사람 우선
    order_idx = {s: i for i, s in enumerate(staff)}

    def need_ok(i):
        rem = n - i
        rem_wk = sum(wk[i:])
        if sum(max(0, lo - total[s]) for s in staff) > rem:
            return False
        if sum(max(0, wlo - weekend[s]) for s in staff) > rem_wk:
            return False
        return True

    def dfs(i):
        if i == n:
            return True
        if time.monotonic() > deadline:
            raise TimeoutError
        prev = result[i - 1] if i else prev_name
        iso = dates[i].isoformat()
        cands = [s for s in staff
                 if s != prev and (s, iso) not in unavail
                 and total[s] < hi and (not wk[i] or weekend[s] < whi)]
        cands.sort(key=lambda s: (total[s], weekend[s] if wk[i] else 0, order_idx[s]))
        for s in cands:
            result[i] = s
            total[s] += 1
            if wk[i]:
                weekend[s] += 1
            if need_ok(i + 1) and dfs(i + 1):
                return True
            total[s] -= 1
            if wk[i]:
                weekend[s] -= 1
            result[i] = None
        return False

    try:
        ok = dfs(0)
    except TimeoutError:
        ok = False
    return result if ok else None


def unavailable_set(con):
    return {(r["name"], r["date"]) for r in con.execute("SELECT name, date FROM dt_unavailable")}


@app.get("/api/staff")
def api_staff():
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT name, grade FROM dt_staff ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/unavailable")
def api_unavailable(month: str = ""):
    con = db()
    try:
        if month:
            parse_month(month)
            rows = con.execute(
                "SELECT name, date, reason FROM dt_unavailable WHERE date LIKE ? ORDER BY date, name",
                (month + "-%",))
        else:
            rows = con.execute("SELECT name, date, reason FROM dt_unavailable ORDER BY date, name")
        return [dict(r) for r in rows]
    finally:
        con.close()


@app.get("/api/roster")
def api_roster(month: str):
    con = db()
    try:
        parse_month(month)
        return build_roster(con, month)
    finally:
        con.close()


@app.post("/api/roster/generate")
async def api_generate(request: Request):
    data = await body_of(request)
    month = data.get("month")
    dates = month_dates(month)
    con = db()
    try:
        if build_roster(con, month)["status"] == "확정":
            raise Reject(409, "확정된 달은 다시 생성할 수 없습니다")
        staff = [r["name"] for r in con.execute("SELECT name FROM dt_staff ORDER BY rowid")]
        prev = con.execute("SELECT name FROM dt_roster WHERE date=?",
                           ((dates[0] - timedelta(days=1)).isoformat(),)).fetchone()
        result = generate(dates, staff, unavailable_set(con), prev["name"] if prev else None)
        if result is None:
            raise Reject(422, "규칙을 만족하는 순번을 만들 수 없습니다")
        con.execute("DELETE FROM dt_roster WHERE date LIKE ?", (month + "-%",))
        con.executemany("INSERT INTO dt_roster VALUES (?,?,0)",
                        [(d.isoformat(), n) for d, n in zip(dates, result)])
        con.commit()
        return build_roster(con, month)
    finally:
        con.close()


@app.post("/api/roster/swap")
async def api_swap(request: Request):
    data = await body_of(request)
    da, db_ = data.get("date_a"), data.get("date_b")
    a, b = parse_date(da), parse_date(db_)
    con = db()
    try:
        if a == b:
            raise Reject(400, "같은 날짜끼리는 바꿀 수 없습니다")
        ra = con.execute("SELECT name FROM dt_roster WHERE date=?", (a.isoformat(),)).fetchone()
        rb = con.execute("SELECT name FROM dt_roster WHERE date=?", (b.isoformat(),)).fetchone()
        if not ra or not rb:
            raise Reject(400, "순번이 없는 날짜입니다 (없는 날짜이거나 생성되지 않은 달)")
        new = {a: rb["name"], b: ra["name"]}
        unavail = unavailable_set(con)
        for d, name in new.items():
            if (name, d.isoformat()) in unavail:
                raise Reject(409, f"R2 위반: {name} 님은 {d.isoformat()} 에 근무할 수 없습니다 (제외일)")
        for d, name in new.items():
            for nb in (d - timedelta(days=1), d + timedelta(days=1)):
                if nb in new:
                    other = new[nb]
                else:
                    r = con.execute("SELECT name FROM dt_roster WHERE date=?", (nb.isoformat(),)).fetchone()
                    other = r["name"] if r else None
                if other == name:
                    raise Reject(409, f"R3 위반: {name} 님이 {min(d, nb).isoformat()} 와 {max(d, nb).isoformat()} 에 연속 당직이 됩니다")
        for d, name in new.items():
            con.execute("UPDATE dt_roster SET name=? WHERE date=?", (name, d.isoformat()))
        con.commit()
        return build_roster(con, a.isoformat()[:7])
    finally:
        con.close()


@app.post("/api/roster/confirm")
async def api_confirm(request: Request):
    data = await body_of(request)
    month = data.get("month")
    parse_month(month)
    con = db()
    try:
        if build_roster(con, month)["status"] == "미생성":
            raise Reject(400, "아직 생성되지 않은 달은 확정할 수 없습니다")
        con.execute("UPDATE dt_roster SET confirmed=1 WHERE date LIKE ?", (month + "-%",))
        con.commit()
        return build_roster(con, month)
    finally:
        con.close()


@app.get("/api/stats")
def api_stats(month: str):
    con = db()
    try:
        parse_month(month)
        stats = {r["name"]: {"name": r["name"], "total": 0, "weekend": 0}
                 for r in con.execute("SELECT name FROM dt_staff ORDER BY rowid")}
        for d in build_roster(con, month)["days"]:
            if d["name"] in stats:
                stats[d["name"]]["total"] += 1
                if d["weekend"]:
                    stats[d["name"]]["weekend"] += 1
        return list(stats.values())
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
