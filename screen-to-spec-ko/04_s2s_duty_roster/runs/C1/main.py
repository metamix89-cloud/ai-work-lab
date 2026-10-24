# -*- coding: utf-8 -*-
"""한빛요양병원 3병동 당직 순번표 — FastAPI + SQLite."""
import csv
import datetime as dt
import os
import random
import re
import sqlite3
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "duty.db")


# ── DB ──────────────────────────────────────────────────────────────────────
def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for ext in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + ext)
        except OSError:
            pass
    c = conn()
    c.executescript("""
        CREATE TABLE dt_staff (name TEXT PRIMARY KEY, grade TEXT);
        CREATE TABLE dt_unavailable (name TEXT, date TEXT, reason TEXT);
        CREATE TABLE dt_roster (date TEXT PRIMARY KEY, name TEXT, confirmed INTEGER DEFAULT 0);
    """)
    c.executemany("INSERT INTO dt_staff VALUES (?,?)",
                  [(r["name"].strip(), r["grade"].strip()) for r in read_csv("staff.csv")])
    c.executemany("INSERT INTO dt_unavailable VALUES (?,?,?)",
                  [(r["name"].strip(), r["date"].strip(), r["reason"].strip()) for r in read_csv("unavailable.csv")])
    c.executemany("INSERT OR REPLACE INTO dt_roster VALUES (?,?,?)",
                  [(r["date"].strip(), r["name"].strip(), int(r["confirmed"] or 0)) for r in read_csv("roster.csv")])
    c.commit()
    c.close()


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_handler(_req: Request, _exc: RequestValidationError):
    return JSONResponse({"detail": "입력이 올바르지 않습니다"}, status_code=400)


# ── 도우미 ──────────────────────────────────────────────────────────────────
def month_days(month):
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    y, m = int(month[:4]), int(month[5:])
    if not 1 <= m <= 12:
        raise HTTPException(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    d = dt.date(y, m, 1)
    out = []
    while d.month == m:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def parse_date(s):
    try:
        if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            raise ValueError
        return dt.date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, "날짜 형식이 올바르지 않습니다")


def month_rows(c, month):
    return c.execute("SELECT date, name, confirmed FROM dt_roster WHERE date LIKE ? ORDER BY date",
                     (month + "-%",)).fetchall()


def build_roster(c, month):
    days = month_days(month)
    rows = {r["date"]: r for r in month_rows(c, month)}
    if not rows:
        status = "미생성"
    elif any(r["confirmed"] for r in rows.values()):
        status = "확정"
    else:
        status = "생성됨"
    return {"month": month, "status": status,
            "days": [{"date": d.isoformat(),
                      "name": rows[d.isoformat()]["name"] if d.isoformat() in rows else "",
                      "weekend": d.weekday() >= 5} for d in days]}


def unavailable_set(c):
    return {(r["name"], r["date"]) for r in c.execute("SELECT name, date FROM dt_unavailable")}


# ── 생성 알고리즘 (백트래킹 + 시드 고정, 생성 뒤 R1~R5 재검사) ─────────────
def check_rules(days, assign, staff, unav, prev_name):
    """R1~R5 검사. 위반 사유 문자열 목록."""
    errs = []
    if len(assign) != len(days) or any(not n for n in assign):
        errs.append("R1")
    prev = prev_name
    for d, n in zip(days, assign):
        if (n, d.isoformat()) in unav:
            errs.append("R2")
        if n == prev:
            errs.append("R3")
        prev = n
    tot = {s: 0 for s in staff}
    wk = {s: 0 for s in staff}
    for d, n in zip(days, assign):
        if n in tot:
            tot[n] += 1
            if d.weekday() >= 5:
                wk[n] += 1
    if max(tot.values()) - min(tot.values()) > 1:
        errs.append("R4")
    if max(wk.values()) - min(wk.values()) > 1:
        errs.append("R5")
    return errs


def solve(days, staff, unav, prev_name, seed, budget):
    k, n = len(staff), len(days)
    weekend = [d.weekday() >= 5 for d in days]
    w = sum(weekend)
    t_lo, t_hi = n // k, -(-n // k)
    w_lo, w_hi = w // k, -(-w // k)
    rng = random.Random(seed)
    cnt = {s: 0 for s in staff}
    wcnt = {s: 0 for s in staff}
    assign = []
    nodes = [0]
    # 남은 날 중 각자 가능한 날 수(뒤쪽 가지치기용)
    ds = [d.isoformat() for d in days]
    future = [{s: 0 for s in staff} for _ in range(n + 1)]
    futurew = [{s: 0 for s in staff} for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for s in staff:
            ok = (s, ds[i]) not in unav
            future[i][s] = future[i + 1][s] + (1 if ok else 0)
            futurew[i][s] = futurew[i + 1][s] + (1 if ok and weekend[i] else 0)

    def dfs(i, prev):
        if i == n:
            return True
        nodes[0] += 1
        if nodes[0] > budget:
            return None
        cands = [s for s in staff if s != prev and (s, ds[i]) not in unav
                 and cnt[s] < t_hi and (not weekend[i] or wcnt[s] < w_hi)]
        rng.shuffle(cands)
        cands.sort(key=lambda s: (wcnt[s] if weekend[i] else 0, cnt[s]))
        for s in cands:
            cnt[s] += 1
            if weekend[i]:
                wcnt[s] += 1
            # 각자 최소치에 도달할 수 있는지(남은 날 기준)
            ok = all(cnt[x] + future[i + 1][x] >= t_lo and wcnt[x] + futurew[i + 1][x] >= w_lo for x in staff)
            if ok:
                assign.append(s)
                r = dfs(i + 1, s)
                if r:
                    return True
                assign.pop()
                if r is None:
                    cnt[s] -= 1
                    if weekend[i]:
                        wcnt[s] -= 1
                    return None
            cnt[s] -= 1
            if weekend[i]:
                wcnt[s] -= 1
        return False

    r = dfs(0, prev_name)
    return list(assign) if r else (None if r is None else False)


def generate_assignment(days, staff, unav, prev_name):
    if not staff:
        return None
    start = time.time()
    for seed in range(1, 200):
        if time.time() - start > 2.2:
            break
        res = solve(days, staff, unav, prev_name, seed, 20000)
        if res is False:
            return None  # 완전 탐색으로 불가능 확인
        if res and not check_rules(days, res, staff, unav, prev_name):
            return res
    return None


# ── 화면 ────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")


# ── API ─────────────────────────────────────────────────────────────────────
@app.get("/api/staff")
def api_staff():
    c = conn()
    out = [{"name": r["name"], "grade": r["grade"]} for r in c.execute("SELECT name, grade FROM dt_staff ORDER BY rowid")]
    c.close()
    return out


@app.get("/api/unavailable")
def api_unavailable(month: str):
    month_days(month)
    c = conn()
    out = [{"name": r["name"], "date": r["date"], "reason": r["reason"]}
           for r in c.execute("SELECT name, date, reason FROM dt_unavailable WHERE date LIKE ? ORDER BY date, rowid",
                              (month + "-%",))]
    c.close()
    return out


@app.get("/api/default-month")
def api_default_month():
    """화면 첫 월: 이미 짜인 마지막 달의 다음 달(없으면 이번 달)."""
    c = conn()
    r = c.execute("SELECT MAX(date) AS d FROM dt_roster").fetchone()
    c.close()
    if r and r["d"]:
        d = dt.date.fromisoformat(r["d"])
    else:
        d = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    nxt = d.replace(day=1) + dt.timedelta(days=32)
    return {"month": "%04d-%02d" % (nxt.year, nxt.month)}


@app.get("/api/roster")
def api_roster(month: str):
    c = conn()
    try:
        return build_roster(c, month)
    finally:
        c.close()


@app.post("/api/roster/generate")
async def api_generate(req: Request):
    body = await _json(req)
    month = body.get("month")
    days = month_days(month)
    c = conn()
    try:
        if any(r["confirmed"] for r in month_rows(c, month)):
            raise HTTPException(409, "확정된 달은 다시 생성할 수 없습니다")
        staff = [r["name"] for r in c.execute("SELECT name FROM dt_staff ORDER BY rowid")]
        unav = unavailable_set(c)
        p = c.execute("SELECT name FROM dt_roster WHERE date=?",
                      ((days[0] - dt.timedelta(days=1)).isoformat(),)).fetchone()
        prev_name = p["name"] if p else None
        res = generate_assignment(days, staff, unav, prev_name)
        if res is None:
            raise HTTPException(422, "규칙을 만족하는 순번을 만들 수 없습니다")
        c.execute("DELETE FROM dt_roster WHERE date LIKE ?", (month + "-%",))
        c.executemany("INSERT INTO dt_roster VALUES (?,?,0)", [(d.isoformat(), n) for d, n in zip(days, res)])
        c.commit()
        return build_roster(c, month)
    finally:
        c.close()


async def _json(req):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "입력이 올바르지 않습니다")
    if not isinstance(body, dict):
        raise HTTPException(400, "입력이 올바르지 않습니다")
    return body


@app.post("/api/roster/swap")
async def api_swap(req: Request):
    body = await _json(req)
    da, db_ = parse_date(body.get("date_a")), parse_date(body.get("date_b"))
    if da == db_:
        raise HTTPException(400, "같은 날짜는 바꿀 수 없습니다")
    c = conn()
    try:
        ra = c.execute("SELECT name FROM dt_roster WHERE date=?", (da.isoformat(),)).fetchone()
        rb = c.execute("SELECT name FROM dt_roster WHERE date=?", (db_.isoformat(),)).fetchone()
        if not ra or not rb:
            raise HTTPException(400, "순번이 없는 날짜입니다 (없는 날짜 또는 미생성 달)")
        if da.strftime("%Y-%m") != db_.strftime("%Y-%m"):
            raise HTTPException(400, "같은 달 안에서만 바꿀 수 있습니다")
        na, nb = ra["name"], rb["name"]
        unav = unavailable_set(c)
        new = {da: nb, db_: na}
        # R2 제외일
        for d, n in new.items():
            if (n, d.isoformat()) in unav:
                raise HTTPException(409, "R2 제외일 위반: %s 님은 %s 에 당직할 수 없습니다" % (n, d.isoformat()))

        def at(d):
            if d in new:
                return new[d]
            r = c.execute("SELECT name FROM dt_roster WHERE date=?", (d.isoformat(),)).fetchone()
            return r["name"] if r else None

        # R3 연속
        for d in (da, db_):
            for o in (d - dt.timedelta(days=1), d + dt.timedelta(days=1)):
                if at(o) is not None and at(o) == new[d]:
                    raise HTTPException(409, "R3 연속 당직 위반: %s 님이 %s 와 %s 에 이틀 연속입니다"
                                        % (new[d], min(d, o).isoformat(), max(d, o).isoformat()))
        c.execute("UPDATE dt_roster SET name=? WHERE date=?", (nb, da.isoformat()))
        c.execute("UPDATE dt_roster SET name=? WHERE date=?", (na, db_.isoformat()))
        c.commit()
        return build_roster(c, da.strftime("%Y-%m"))
    finally:
        c.close()


@app.post("/api/roster/confirm")
async def api_confirm(req: Request):
    body = await _json(req)
    month = body.get("month")
    month_days(month)
    c = conn()
    try:
        if not month_rows(c, month):
            raise HTTPException(400, "아직 순번이 없는 달은 확정할 수 없습니다")
        c.execute("UPDATE dt_roster SET confirmed=1 WHERE date LIKE ?", (month + "-%",))
        c.commit()
        return build_roster(c, month)
    finally:
        c.close()


@app.get("/api/stats")
def api_stats(month: str):
    month_days(month)
    c = conn()
    try:
        out = []
        for s in c.execute("SELECT name FROM dt_staff ORDER BY rowid").fetchall():
            tot = wk = 0
            for r in c.execute("SELECT date FROM dt_roster WHERE name=? AND date LIKE ?", (s["name"], month + "-%")):
                tot += 1
                if dt.date.fromisoformat(r["date"]).weekday() >= 5:
                    wk += 1
            out.append({"name": s["name"], "total": tot, "weekend": wk})
        return out
    finally:
        c.close()
