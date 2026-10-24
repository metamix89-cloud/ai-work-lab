# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R8 그대로. 생성은 되추적(backtracking)으로 R1~R5 를 모두 만족시킨다."""
import calendar
import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "duty.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE dt_staff(name TEXT PRIMARY KEY, grade TEXT);
    CREATE TABLE dt_unavailable(name TEXT, date TEXT, reason TEXT);
    CREATE TABLE dt_roster(date TEXT PRIMARY KEY, name TEXT, confirmed INTEGER);""")
    for name, table, n in (("staff.csv", "dt_staff", 2), ("unavailable.csv", "dt_unavailable", 3), ("roster.csv", "dt_roster", 3)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            con.executemany("INSERT OR REPLACE INTO %s VALUES (%s)" % (table, ",".join("?" * n)), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def month_days(month):
    try:
        y, m = int(month[:4]), int(month[5:7])
        n = calendar.monthrange(y, m)[1]
    except Exception:
        raise HTTPException(400, "월 형식은 YYYY-MM 입니다")
    return ["%04d-%02d-%02d" % (y, m, d) for d in range(1, n + 1)]


def is_weekend(d):
    return dt.date.fromisoformat(d).weekday() >= 5


class MonthIn(BaseModel):
    month: str


class SwapIn(BaseModel):
    date_a: str
    date_b: str


def roster_of(c, month):
    days = month_days(month)
    rows = {r["date"]: r for r in c.execute("SELECT * FROM dt_roster WHERE date LIKE ?", (month + "-%",))}
    if not rows:
        status = "미생성"
    elif all(r["confirmed"] for r in rows.values()):
        status = "확정"
    else:
        status = "생성됨"
    return {"month": month, "status": status,
            "days": [{"date": d, "name": rows[d]["name"] if d in rows else "", "weekend": is_weekend(d)} for d in days]}


def unavailable_set(c, month):
    return {(r["name"], r["date"]) for r in c.execute("SELECT * FROM dt_unavailable WHERE date LIKE ?", (month + "-%",))}


def prev_day_name(c, first_day):
    prev = (dt.date.fromisoformat(first_day) - dt.timedelta(days=1)).isoformat()
    r = c.execute("SELECT name FROM dt_roster WHERE date=?", (prev,)).fetchone()
    return r["name"] if r else None


def generate(names, days, unav, prev_name):
    """되추적. 날마다 후보를 (총 횟수, 주말 횟수, 이름순) 으로 정렬해 시도하고, 공평 상한을 가지치기한다."""
    n_days, n = len(days), len(names)
    wk_days = [d for d in days if is_weekend(d)]
    cap_total = -(-n_days // n)          # 올림: 총 횟수 상한
    cap_wk = -(-len(wk_days) // n)       # 주말 상한
    total = {x: 0 for x in names}
    wk = {x: 0 for x in names}
    result = []

    def fair(d):
        return max(d.values()) - min(d.values()) <= 1

    def rec(i, prev):
        if i == n_days:
            return fair(total) and fair(wk)
        d = days[i]
        cands = [x for x in names if (x, d) not in unav and x != prev]
        cands.sort(key=lambda x: (total[x], wk[x] if is_weekend(d) else 0, names.index(x)))
        for x in cands:
            if total[x] + 1 > cap_total or (is_weekend(d) and wk[x] + 1 > cap_wk):
                continue
            total[x] += 1
            if is_weekend(d):
                wk[x] += 1
            result.append(x)
            if rec(i + 1, x):
                return True
            result.pop()
            total[x] -= 1
            if is_weekend(d):
                wk[x] -= 1
        return False

    return dict(zip(days, result)) if rec(0, prev_name) else None


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/staff")
def staff():
    return [dict(r) for r in con().execute("SELECT * FROM dt_staff")]


@app.get("/api/unavailable")
def unavailable(month: str):
    return [dict(r) for r in con().execute("SELECT * FROM dt_unavailable WHERE date LIKE ? ORDER BY date", (month + "-%",))]


@app.get("/api/roster")
def roster(month: str):
    return roster_of(con(), month)


@app.get("/api/stats")
def stats(month: str):
    c = con()
    names = [r["name"] for r in c.execute("SELECT name FROM dt_staff")]
    out = {x: {"name": x, "total": 0, "weekend": 0} for x in names}
    for r in c.execute("SELECT * FROM dt_roster WHERE date LIKE ?", (month + "-%",)):
        if r["name"] in out:
            out[r["name"]]["total"] += 1
            if is_weekend(r["date"]):
                out[r["name"]]["weekend"] += 1
    return list(out.values())


@app.post("/api/roster/generate")
def gen(m: MonthIn):
    c = con()
    days = month_days(m.month)
    cur = roster_of(c, m.month)
    if cur["status"] == "확정":
        raise HTTPException(409, "확정된 달은 다시 생성할 수 없습니다")
    names = [r["name"] for r in c.execute("SELECT name FROM dt_staff")]
    plan = generate(names, days, unavailable_set(c, m.month), prev_day_name(c, days[0]))
    if not plan:
        raise HTTPException(422, "규칙을 만족하는 순번을 만들 수 없습니다")
    c.execute("DELETE FROM dt_roster WHERE date LIKE ?", (m.month + "-%",))
    c.executemany("INSERT INTO dt_roster VALUES (?,?,0)", list(plan.items()))
    c.commit()
    return roster_of(c, m.month)


@app.post("/api/roster/swap")
def swap(s: SwapIn):
    c = con()
    if s.date_a == s.date_b:
        raise HTTPException(400, "같은 날짜입니다")
    a = c.execute("SELECT * FROM dt_roster WHERE date=?", (s.date_a,)).fetchone()
    b = c.execute("SELECT * FROM dt_roster WHERE date=?", (s.date_b,)).fetchone()
    if not a or not b:
        raise HTTPException(400, "순번이 없는 날짜입니다")
    new = {s.date_a: b["name"], s.date_b: a["name"]}
    unav = {(r["name"], r["date"]) for r in c.execute("SELECT * FROM dt_unavailable")}
    for d, name in new.items():
        if (name, d) in unav:
            raise HTTPException(409, "%s 은(는) %s 제외일입니다 (R2)" % (name, d))
        for delta in (-1, 1):
            nd = (dt.date.fromisoformat(d) + dt.timedelta(days=delta)).isoformat()
            neighbor = new.get(nd)
            if neighbor is None:
                r = c.execute("SELECT name FROM dt_roster WHERE date=?", (nd,)).fetchone()
                neighbor = r["name"] if r else None
            if neighbor == name:
                raise HTTPException(409, "%s 이(가) %s 과 연속 당직이 됩니다 (R3)" % (name, nd))
    for d, name in new.items():
        c.execute("UPDATE dt_roster SET name=? WHERE date=?", (name, d))
    c.commit()
    return roster_of(c, s.date_a[:7])


@app.post("/api/roster/confirm")
def confirm(m: MonthIn):
    c = con()
    if roster_of(c, m.month)["status"] == "미생성":
        raise HTTPException(400, "생성되지 않은 달입니다")
    c.execute("UPDATE dt_roster SET confirmed=1 WHERE date LIKE ?", (m.month + "-%",))
    c.commit()
    return roster_of(c, m.month)
