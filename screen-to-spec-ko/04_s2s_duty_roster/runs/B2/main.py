import calendar
import csv
import os
import random
import re
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
SEED = BASE / "seed"
DB_PATH = BASE / "duty.db"
STATIC = BASE / "static"

app = FastAPI()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    """서버가 시작할 때마다 seed CSV 로 DB 를 새로 만든다."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = db()
    con.executescript(
        """
        CREATE TABLE dt_staff (name TEXT PRIMARY KEY, grade TEXT);
        CREATE TABLE dt_unavailable (name TEXT, date TEXT, reason TEXT);
        CREATE TABLE dt_roster (date TEXT PRIMARY KEY, name TEXT, confirmed INTEGER DEFAULT 0);
        """
    )
    con.executemany(
        "INSERT INTO dt_staff VALUES (?,?)",
        [(r["name"], r["grade"]) for r in read_csv("staff.csv")],
    )
    con.executemany(
        "INSERT INTO dt_unavailable VALUES (?,?,?)",
        [(r["name"], r["date"], r["reason"]) for r in read_csv("unavailable.csv")],
    )
    con.executemany(
        "INSERT INTO dt_roster VALUES (?,?,?)",
        [(r["date"], r["name"], int(r["confirmed"])) for r in read_csv("roster.csv")],
    )
    con.commit()
    con.close()


init_db()

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def check_month(month):
    if not isinstance(month, str) or not MONTH_RE.match(month):
        raise Reject(400, "월 형식이 올바르지 않습니다 (YYYY-MM)")
    return month


def month_days(month):
    y, m = int(month[:4]), int(month[5:])
    n = calendar.monthrange(y, m)[1]
    return [date(y, m, d) for d in range(1, n + 1)]


def staff_names(con):
    return [r["name"] for r in con.execute("SELECT name FROM dt_staff ORDER BY rowid")]


def roster_rows(con, month):
    return {
        r["date"]: r
        for r in con.execute(
            "SELECT date, name, confirmed FROM dt_roster WHERE date LIKE ?", (month + "-%",)
        )
    }


def build_roster(con, month):
    rows = roster_rows(con, month)
    days = month_days(month)
    if not rows:
        status = "미생성"
    elif len(rows) == len(days) and all(r["confirmed"] for r in rows.values()):
        status = "확정"
    else:
        status = "생성됨"
    return {
        "month": month,
        "status": status,
        "days": [
            {
                "date": d.isoformat(),
                "name": rows[d.isoformat()]["name"] if d.isoformat() in rows else "",
                "weekend": d.weekday() >= 5,
            }
            for d in days
        ],
    }


def unavailable_set(con):
    return {(r["name"], r["date"]) for r in con.execute("SELECT name, date FROM dt_unavailable")}


# ---------- 생성 알고리즘 (R1~R5) ----------
def solve(days, staff, blocked, prev_name):
    """백트래킹. 총 횟수 · 주말 횟수가 (최댓값-최솟값 ≤ 1) 이 되도록 상한/하한을 가지치기에 쓴다."""
    n, k = len(days), len(staff)
    wk = [d.weekday() >= 5 for d in days]
    w_total = sum(wk)
    cap_t, floor_t = -(-n // k), n // k
    cap_w, floor_w = -(-w_total // k), w_total // k
    deadline = time.monotonic() + 2.0
    rng = random.Random(len(days) * 7919)

    for attempt in range(200):
        cnt = {s: 0 for s in staff}
        wcnt = {s: 0 for s in staff}
        out = [None] * n
        steps = [0]
        # 남은 날(자기 포함) 수 계산용
        rem_w = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            rem_w[i] = rem_w[i + 1] + (1 if wk[i] else 0)

        def feasible(i):
            remaining = n - i
            need = sum(max(0, floor_t - cnt[s]) for s in staff)
            if need > remaining:
                return False
            needw = sum(max(0, floor_w - wcnt[s]) for s in staff)
            return needw <= rem_w[i]

        def rec(i):
            if time.monotonic() > deadline:
                return False
            steps[0] += 1
            if steps[0] > 20000 * (attempt + 1):
                return False
            if i == n:
                return (
                    max(cnt.values()) - min(cnt.values()) <= 1
                    and max(wcnt.values()) - min(wcnt.values()) <= 1
                )
            prev = out[i - 1] if i > 0 else prev_name
            iso = days[i].isoformat()
            cands = [
                s
                for s in staff
                if s != prev
                and (s, iso) not in blocked
                and cnt[s] < cap_t
                and (not wk[i] or wcnt[s] < cap_w)
            ]
            rng.shuffle(cands)
            cands.sort(key=lambda s: (cnt[s], wcnt[s] if wk[i] else 0))
            for s in cands:
                out[i] = s
                cnt[s] += 1
                if wk[i]:
                    wcnt[s] += 1
                if feasible(i + 1) and rec(i + 1):
                    return True
                cnt[s] -= 1
                if wk[i]:
                    wcnt[s] -= 1
                out[i] = None
            return False

        if rec(0):
            return out
        if time.monotonic() > deadline:
            break
    return None


class GenerateBody(BaseModel):
    month: str


class SwapBody(BaseModel):
    date_a: str
    date_b: str


class ConfirmBody(BaseModel):
    month: str


# ---------- API ----------
@app.get("/api/staff")
def api_staff():
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT name, grade FROM dt_staff ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/unavailable")
def api_unavailable(month: str):
    check_month(month)
    con = db()
    try:
        return [
            dict(r)
            for r in con.execute(
                "SELECT name, date, reason FROM dt_unavailable WHERE date LIKE ? ORDER BY date, rowid",
                (month + "-%",),
            )
        ]
    finally:
        con.close()


@app.get("/api/roster")
def api_roster(month: str):
    check_month(month)
    con = db()
    try:
        return build_roster(con, month)
    finally:
        con.close()


@app.post("/api/roster/generate")
def api_generate(body: GenerateBody):
    month = check_month(body.month)
    con = db()
    try:
        if build_roster(con, month)["status"] == "확정":
            raise Reject(409, "확정된 달은 다시 생성할 수 없습니다")
        days = month_days(month)
        prev_day = (days[0] - timedelta(days=1)).isoformat()
        prev = con.execute("SELECT name FROM dt_roster WHERE date=?", (prev_day,)).fetchone()
        result = solve(days, staff_names(con), unavailable_set(con), prev["name"] if prev else None)
        if result is None:
            raise Reject(422, "규칙을 만족하는 순번을 만들 수 없습니다")
        con.execute("DELETE FROM dt_roster WHERE date LIKE ?", (month + "-%",))
        con.executemany(
            "INSERT INTO dt_roster VALUES (?,?,0)",
            [(d.isoformat(), n) for d, n in zip(days, result)],
        )
        con.commit()
        return build_roster(con, month)
    finally:
        con.close()


def parse_date(s):
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@app.post("/api/roster/swap")
def api_swap(body: SwapBody):
    con = db()
    try:
        # R8: 400(입력 오류) 먼저
        da, db_ = parse_date(body.date_a), parse_date(body.date_b)
        if da is None or db_ is None:
            raise Reject(400, "날짜 형식이 올바르지 않습니다")
        if da == db_:
            raise Reject(400, "같은 날짜끼리는 바꿀 수 없습니다")
        a, b = da.isoformat(), db_.isoformat()
        rows = {
            r["date"]: r["name"]
            for r in con.execute("SELECT date, name FROM dt_roster WHERE date IN (?,?)", (a, b))
        }
        if a not in rows or b not in rows:
            raise Reject(400, "순번이 없는 날짜입니다 (미생성 달이거나 없는 날짜)")
        # R6: 교환 후 R2 → R3 검사
        new = {a: rows[b], b: rows[a]}
        blocked = unavailable_set(con)
        for d in (a, b):
            if (new[d], d) in blocked:
                raise Reject(409, f"R2 위반: {new[d]} 은(는) {d} 에 제외일입니다")
        for d in (a, b):
            cur = date.fromisoformat(d)
            for nb in (cur - timedelta(days=1), cur + timedelta(days=1)):
                nbi = nb.isoformat()
                if nbi in new:
                    nb_name = new[nbi]
                else:
                    r = con.execute("SELECT name FROM dt_roster WHERE date=?", (nbi,)).fetchone()
                    nb_name = r["name"] if r else None
                if nb_name == new[d]:
                    raise Reject(409, f"R3 위반: {new[d]} 이(가) {d} 와(과) {nbi} 에 연속 당직이 됩니다")
        con.execute("UPDATE dt_roster SET name=? WHERE date=?", (new[a], a))
        con.execute("UPDATE dt_roster SET name=? WHERE date=?", (new[b], b))
        con.commit()
        return build_roster(con, a[:7])
    finally:
        con.close()


@app.post("/api/roster/confirm")
def api_confirm(body: ConfirmBody):
    month = check_month(body.month)
    con = db()
    try:
        if build_roster(con, month)["status"] == "미생성":
            raise Reject(400, "순번이 없는 달은 확정할 수 없습니다")
        con.execute("UPDATE dt_roster SET confirmed=1 WHERE date LIKE ?", (month + "-%",))
        con.commit()
        return build_roster(con, month)
    finally:
        con.close()


@app.get("/api/stats")
def api_stats(month: str):
    check_month(month)
    con = db()
    try:
        stats = {n: {"name": n, "total": 0, "weekend": 0} for n in staff_names(con)}
        for d, r in roster_rows(con, month).items():
            if r["name"] in stats:
                stats[r["name"]]["total"] += 1
                if date.fromisoformat(d).weekday() >= 5:
                    stats[r["name"]]["weekend"] += 1
        return list(stats.values())
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
