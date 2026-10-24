import calendar
import csv
import datetime as dt
import os
import random
import re
import sqlite3
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "duty.db")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    path = os.path.join(BASE, "seed", name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
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
    c.executemany("INSERT INTO dt_staff VALUES (?,?)", [(r["name"], r["grade"]) for r in read_csv("staff.csv")])
    c.executemany("INSERT INTO dt_unavailable VALUES (?,?,?)",
                  [(r["name"], r["date"], r["reason"]) for r in read_csv("unavailable.csv")])
    c.executemany("INSERT OR REPLACE INTO dt_roster VALUES (?,?,?)",
                  [(r["date"], r["name"], int(r["confirmed"] or 0)) for r in read_csv("roster.csv")])
    c.commit()
    c.close()


init_db()


def check_month(month):
    if not isinstance(month, str) or not MONTH_RE.match(month):
        raise Reject(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")


def month_dates(month):
    y, m = int(month[:4]), int(month[5:])
    return [dt.date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def staff_names(c):
    return [r["name"] for r in c.execute("SELECT name FROM dt_staff ORDER BY rowid")]


def roster_rows(c, month):
    return {r["date"]: r for r in c.execute("SELECT * FROM dt_roster WHERE date LIKE ?", (month + "-%",))}


def build_roster(c, month):
    rows = roster_rows(c, month)
    if not rows:
        status = "미생성"
    elif all(r["confirmed"] for r in rows.values()):
        status = "확정"
    else:
        status = "생성됨"
    days = [{"date": d.isoformat(), "name": rows[d.isoformat()]["name"] if d.isoformat() in rows else "",
             "weekend": d.weekday() >= 5} for d in month_dates(month)]
    return {"month": month, "status": status, "days": days}


# ── 생성 ──────────────────────────────────────────────────────────────────
def solve(dates, names, unav, prev_name, time_limit=2.5):
    """백트래킹. R1~R5 를 가지치기로 강제한다. 시드 고정."""
    n, k = len(dates), len(names)
    weekend = [d.weekday() >= 5 for d in dates]
    W = sum(weekend)
    tmax, tmin = -(-n // k), n // k
    wmax, wmin = -(-W // k), W // k
    tot = {x: 0 for x in names}
    wk = {x: 0 for x in names}
    plan = [None] * n
    rng = random.Random(20261101)
    deadline = time.time() + time_limit
    wrem = [sum(weekend[i:]) for i in range(n + 1)]

    def rec(i, prev):
        if time.time() > deadline:
            return False
        if i == n:
            return True
        rem, wr = n - i, wrem[i]
        for x in names:  # 남은 날로 최소 횟수를 못 채우는 사람이 있으면 가지치기
            if tmin - tot[x] > rem or wmin - wk[x] > wr:
                return False
        cands = [x for x in names if x != prev and (x, dates[i].isoformat()) not in unav
                 and tot[x] < tmax and (not weekend[i] or wk[x] < wmax)]
        rng.shuffle(cands)
        cands.sort(key=lambda x: (tot[x], wk[x] if weekend[i] else 0))
        for x in cands:
            plan[i] = x
            tot[x] += 1
            wk[x] += weekend[i]
            if rec(i + 1, x):
                return True
            tot[x] -= 1
            wk[x] -= weekend[i]
        plan[i] = None
        return False

    return list(plan) if rec(0, prev_name) else None


def verify(dates, plan, names, unav, prev_name):
    """생성 뒤 R1~R5 자체 검사."""
    if len(plan) != len(dates) or any(p not in names for p in plan):
        return False
    prev = prev_name
    for d, p in zip(dates, plan):
        if p == prev or (p, d.isoformat()) in unav:
            return False
        prev = p
    tot = {x: 0 for x in names}
    wk = {x: 0 for x in names}
    for d, p in zip(dates, plan):
        tot[p] += 1
        wk[p] += d.weekday() >= 5
    return max(tot.values()) - min(tot.values()) <= 1 and max(wk.values()) - min(wk.values()) <= 1


@app.get("/api/staff")
def api_staff():
    c = conn()
    out = [{"name": r["name"], "grade": r["grade"]} for r in c.execute("SELECT * FROM dt_staff ORDER BY rowid")]
    c.close()
    return out


@app.get("/api/unavailable")
def api_unavailable(month: str):
    check_month(month)
    c = conn()
    out = [{"name": r["name"], "date": r["date"], "reason": r["reason"]} for r in
           c.execute("SELECT * FROM dt_unavailable WHERE date LIKE ? ORDER BY date, rowid", (month + "-%",))]
    c.close()
    return out


@app.get("/api/roster")
def api_roster(month: str):
    check_month(month)
    c = conn()
    out = build_roster(c, month)
    c.close()
    return out


@app.post("/api/roster/generate")
def api_generate(body: dict):
    month = body.get("month")
    check_month(month)
    c = conn()
    try:
        if build_roster(c, month)["status"] == "확정":
            raise Reject(409, "확정된 달은 다시 생성할 수 없습니다")
        dates = month_dates(month)
        names = staff_names(c)
        unav = {(r["name"], r["date"]) for r in c.execute("SELECT name, date FROM dt_unavailable")}
        prev_day = (dates[0] - dt.timedelta(days=1)).isoformat()
        row = c.execute("SELECT name FROM dt_roster WHERE date=?", (prev_day,)).fetchone()
        prev_name = row["name"] if row else None
        plan = solve(dates, names, unav, prev_name) if names else None
        if not plan or not verify(dates, plan, names, unav, prev_name):
            raise Reject(422, "규칙을 만족하는 순번을 만들 수 없습니다")
        c.execute("DELETE FROM dt_roster WHERE date LIKE ?", (month + "-%",))
        c.executemany("INSERT INTO dt_roster VALUES (?,?,0)", [(d.isoformat(), p) for d, p in zip(dates, plan)])
        c.commit()
        return build_roster(c, month)
    finally:
        c.close()


@app.post("/api/roster/swap")
def api_swap(body: dict):
    a, b = body.get("date_a"), body.get("date_b")
    c = conn()
    try:
        def valid(s):
            try:
                return isinstance(s, str) and dt.date.fromisoformat(s).isoformat() == s
            except ValueError:
                return False
        if not valid(a) or not valid(b):
            raise Reject(400, "없는 날짜입니다")
        if a == b:
            raise Reject(400, "같은 날짜는 바꿀 수 없습니다")
        ra = c.execute("SELECT * FROM dt_roster WHERE date=?", (a,)).fetchone()
        rb = c.execute("SELECT * FROM dt_roster WHERE date=?", (b,)).fetchone()
        if not ra or not rb:
            raise Reject(400, "순번이 아직 생성되지 않은 날짜입니다")
        unav = {(r["name"], r["date"]) for r in c.execute("SELECT name, date FROM dt_unavailable")}
        new = {a: rb["name"], b: ra["name"]}

        def at(d):  # 이웃은 교환 전 순번 기준으로 본다(이웃한 두 날의 교환은 거부)
            r = c.execute("SELECT name FROM dt_roster WHERE date=?", (d,)).fetchone()
            return r["name"] if r else None

        for d in (a, b):  # R2 먼저, 그다음 R3
            if (new[d], d) in unav:
                raise Reject(409, "R2 위반: %s 님은 %s 에 근무할 수 없습니다(제외일)" % (new[d], d))
        for d in (a, b):
            day = dt.date.fromisoformat(d)
            for off in (-1, 1):
                nb = at((day + dt.timedelta(days=off)).isoformat())
                if nb is not None and nb == new[d]:
                    raise Reject(409, "R3 위반: %s 님이 이틀 연속 당직이 됩니다(%s)" % (new[d], d))
        c.execute("UPDATE dt_roster SET name=? WHERE date=?", (new[a], a))
        c.execute("UPDATE dt_roster SET name=? WHERE date=?", (new[b], b))
        c.commit()
        return build_roster(c, a[:7])
    finally:
        c.close()


@app.post("/api/roster/confirm")
def api_confirm(body: dict):
    month = body.get("month")
    check_month(month)
    c = conn()
    try:
        if build_roster(c, month)["status"] == "미생성":
            raise Reject(400, "순번이 아직 생성되지 않았습니다")
        c.execute("UPDATE dt_roster SET confirmed=1 WHERE date LIKE ?", (month + "-%",))
        c.commit()
        return build_roster(c, month)
    finally:
        c.close()


@app.get("/api/stats")
def api_stats(month: str):
    check_month(month)
    c = conn()
    rows = roster_rows(c, month)
    out = []
    for n in staff_names(c):
        ds = [d for d, r in rows.items() if r["name"] == n]
        out.append({"name": n, "total": len(ds),
                    "weekend": sum(dt.date.fromisoformat(d).weekday() >= 5 for d in ds)})
    c.close()
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
