import calendar
import csv
import datetime as dt
import os
import random
import re
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "duty.db")
SEED = os.path.join(BASE, "seed")

app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def _reject(_req, e):
    return JSONResponse({"detail": e.detail}, status_code=e.status)


@app.exception_handler(RequestValidationError)
async def _invalid(_req, _e):
    return JSONResponse({"detail": "입력이 올바르지 않습니다"}, status_code=400)


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    c = conn()
    c.executescript("""
        CREATE TABLE dt_staff (name TEXT PRIMARY KEY, grade TEXT);
        CREATE TABLE dt_unavailable (name TEXT, date TEXT, reason TEXT);
        CREATE TABLE dt_roster (date TEXT PRIMARY KEY, name TEXT, confirmed INTEGER DEFAULT 0);
    """)
    c.executemany("INSERT INTO dt_staff VALUES (?,?)", [(r["name"].strip(), r["grade"].strip()) for r in read_csv("staff.csv")])
    c.executemany("INSERT INTO dt_unavailable VALUES (?,?,?)",
                  [(r["name"].strip(), r["date"].strip(), r["reason"].strip()) for r in read_csv("unavailable.csv")])
    c.executemany("INSERT OR REPLACE INTO dt_roster VALUES (?,?,?)",
                  [(r["date"].strip(), r["name"].strip(), int(r["confirmed"] or 0)) for r in read_csv("roster.csv")])
    c.commit()
    c.close()


init_db()


# ── 공통 ──────────────────────────────────────────────
def month_days(month):
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise Reject(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    y, m = int(month[:4]), int(month[5:])
    if not 1 <= m <= 12 or y < 1:
        raise Reject(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    return [dt.date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def is_weekend(d):
    return d.weekday() >= 5


def month_rows(c, month):
    return c.execute("SELECT * FROM dt_roster WHERE date LIKE ? ORDER BY date", (month + "-%",)).fetchall()


def status_of(rows):
    if not rows:
        return "미생성"
    return "확정" if any(r["confirmed"] for r in rows) else "생성됨"


def roster_json(c, month):
    days = month_days(month)
    rows = month_rows(c, month)
    names = {r["date"]: r["name"] for r in rows}
    return {"month": month, "status": status_of(rows),
            "days": [{"date": d.isoformat(), "name": names.get(d.isoformat(), ""), "weekend": is_weekend(d)} for d in days]}


def staff_names(c):
    return [r["name"] for r in c.execute("SELECT name FROM dt_staff ORDER BY rowid")]


def name_on(c, date):
    r = c.execute("SELECT name FROM dt_roster WHERE date=?", (date,)).fetchone()
    return r["name"] if r else None


# ── 생성 ──────────────────────────────────────────────
def solve(days, staff, unav, prev_name, seed):
    n, k = len(days), len(staff)
    wk = [is_weekend(d) for d in days]
    tot_lo, tot_hi = n // k, -(-n // k)
    wn = sum(wk)
    wk_lo, wk_hi = wn // k, -(-wn // k)
    rng = random.Random(seed)
    total = {s: 0 for s in staff}
    wcnt = {s: 0 for s in staff}
    out = [None] * n
    steps = [0]
    # 남은 날 수 (뒤에서부터 센 값)
    rem_all = [n - i for i in range(n + 1)]
    rem_wk = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        rem_wk[i] = rem_wk[i + 1] + (1 if wk[i] else 0)

    def feasible(i):
        left = rem_all[i]
        if sum(max(0, tot_lo - total[s]) for s in staff) > left:
            return False
        lw = rem_wk[i]
        return sum(max(0, wk_lo - wcnt[s]) for s in staff) <= lw

    def dfs(i):
        if i == n:
            return True
        steps[0] += 1
        if steps[0] > 200000:
            return False
        prev = out[i - 1] if i else prev_name
        date = days[i].isoformat()
        cands = [s for s in staff if s != prev and (s, date) not in unav and total[s] < tot_hi
                 and (not wk[i] or wcnt[s] < wk_hi)]
        rng.shuffle(cands)
        cands.sort(key=lambda s: (wcnt[s] if wk[i] else 0, total[s]))
        for s in cands:
            out[i] = s
            total[s] += 1
            if wk[i]:
                wcnt[s] += 1
            if feasible(i + 1) and dfs(i + 1):
                return True
            total[s] -= 1
            if wk[i]:
                wcnt[s] -= 1
            out[i] = None
            if steps[0] > 200000:
                return False
        return False

    return out if dfs(0) else None


def check_rules(days, staff, unav, prev_name, out):
    """생성 뒤 R1~R5 스스로 검사."""
    if any(o not in staff for o in out):
        return False
    prev = prev_name
    for d, o in zip(days, out):
        if o == prev or (o, d.isoformat()) in unav:
            return False
        prev = o
    t = {s: 0 for s in staff}
    w = {s: 0 for s in staff}
    for d, o in zip(days, out):
        t[o] += 1
        if is_weekend(d):
            w[o] += 1
    return max(t.values()) - min(t.values()) <= 1 and max(w.values()) - min(w.values()) <= 1


@app.post("/api/roster/generate")
async def generate(request: Request):
    body = await _json(request)
    month = body.get("month")
    days = month_days(month)
    c = conn()
    try:
        if status_of(month_rows(c, month)) == "확정":
            raise Reject(409, "확정된 달은 다시 생성할 수 없습니다")
        staff = staff_names(c)
        if not staff:
            raise Reject(422, "규칙을 만족하는 순번을 만들 수 없습니다")
        unav = {(r["name"], r["date"]) for r in c.execute("SELECT name, date FROM dt_unavailable")}
        prev_day = (days[0] - dt.timedelta(days=1)).isoformat()
        prev_name = name_on(c, prev_day)
        out = None
        for seed in range(1, 40):
            out = solve(days, staff, unav, prev_name, seed)
            if out and check_rules(days, staff, unav, prev_name, out):
                break
            out = None
        if not out:
            raise Reject(422, "규칙을 만족하는 순번을 만들 수 없습니다")
        c.execute("DELETE FROM dt_roster WHERE date LIKE ?", (month + "-%",))
        c.executemany("INSERT INTO dt_roster VALUES (?,?,0)", [(d.isoformat(), o) for d, o in zip(days, out)])
        c.commit()
        return roster_json(c, month)
    finally:
        c.close()


async def _json(request):
    try:
        body = await request.json()
    except Exception:
        raise Reject(400, "입력이 올바르지 않습니다")
    if not isinstance(body, dict):
        raise Reject(400, "입력이 올바르지 않습니다")
    return body


# ── 바꾸기 · 확정 ─────────────────────────────────────
def parse_date(s):
    try:
        if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            raise ValueError
        return dt.date.fromisoformat(s)
    except ValueError:
        raise Reject(400, "없는 날짜입니다")


@app.post("/api/roster/swap")
async def swap(request: Request):
    body = await _json(request)
    da, db_ = parse_date(body.get("date_a")), parse_date(body.get("date_b"))
    a, b = da.isoformat(), db_.isoformat()
    if a == b:
        raise Reject(400, "같은 날짜끼리는 바꿀 수 없습니다")
    c = conn()
    try:
        na, nb = name_on(c, a), name_on(c, b)
        if na is None or nb is None:
            raise Reject(400, "순번이 없는 날짜입니다 (없는 날짜이거나 생성되지 않은 달)")
        unav = {(r["name"], r["date"]) for r in c.execute("SELECT name, date FROM dt_unavailable")}
        new = {a: nb, b: na}
        for d, who in new.items():
            if (who, d) in unav:
                raise Reject(409, "제외일 규칙(R2) 위반: %s 님은 %s 에 근무할 수 없습니다" % (who, d))
        for d, who in new.items():
            day = dt.date.fromisoformat(d)
            for off in (-1, 1):
                nd = (day + dt.timedelta(days=off)).isoformat()
                other = new.get(nd, name_on(c, nd))
                if other == who:
                    raise Reject(409, "연속 금지 규칙(R3) 위반: %s 님이 %s 와 %s 에 연속 당직이 됩니다" % (who, d, nd))
        c.execute("UPDATE dt_roster SET name=? WHERE date=?", (nb, a))
        c.execute("UPDATE dt_roster SET name=? WHERE date=?", (na, b))
        c.commit()
        return roster_json(c, a[:7])
    finally:
        c.close()


@app.post("/api/roster/confirm")
async def confirm(request: Request):
    body = await _json(request)
    month = body.get("month")
    month_days(month)
    c = conn()
    try:
        if not month_rows(c, month):
            raise Reject(400, "아직 생성되지 않은 달은 확정할 수 없습니다")
        c.execute("UPDATE dt_roster SET confirmed=1 WHERE date LIKE ?", (month + "-%",))
        c.commit()
        return roster_json(c, month)
    finally:
        c.close()


# ── 조회 ──────────────────────────────────────────────
@app.get("/api/staff")
def staff():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT name, grade FROM dt_staff ORDER BY rowid")]
    finally:
        c.close()


@app.get("/api/unavailable")
def unavailable(month: str):
    month_days(month)
    c = conn()
    try:
        return [dict(r) for r in c.execute(
            "SELECT name, date, reason FROM dt_unavailable WHERE date LIKE ? ORDER BY date, rowid", (month + "-%",))]
    finally:
        c.close()


@app.get("/api/roster")
def roster(month: str):
    c = conn()
    try:
        return roster_json(c, month)
    finally:
        c.close()


@app.get("/api/stats")
def stats(month: str):
    month_days(month)
    c = conn()
    try:
        t = {s: 0 for s in staff_names(c)}
        w = dict(t)
        for r in month_rows(c, month):
            if r["name"] in t:
                t[r["name"]] += 1
                if is_weekend(dt.date.fromisoformat(r["date"])):
                    w[r["name"]] += 1
        return [{"name": s, "total": t[s], "weekend": w[s]} for s in t]
    finally:
        c.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")
