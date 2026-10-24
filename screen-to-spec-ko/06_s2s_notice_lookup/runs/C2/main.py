import csv
import datetime as dt
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "notice.db")
CATEGORIES = ["주차", "위생", "건축", "복지"]
COLS = ["notice_id", "title", "category", "issuer", "published", "effective_from",
        "repealed", "source_url", "original", "summary"]


def load_seed():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE nt_notices (%s)" % ", ".join(c + " TEXT" for c in COLS))
    with open(os.path.join(BASE, "seed", "notices.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            con.execute("INSERT INTO nt_notices VALUES (%s)" % ",".join("?" * len(COLS)),
                        [r.get(c) or "" for c in COLS])
    con.commit()
    con.close()


@asynccontextmanager
async def lifespan(_app):
    load_seed()
    yield


app = FastAPI(lifespan=lifespan)


def rows():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM nt_notices WHERE TRIM(source_url) <> '' ORDER BY published DESC, notice_id")]
    finally:
        con.close()


def shape(r, today, with_original=False):
    eff = dt.date.fromisoformat(r["effective_from"].strip())
    rep = r["repealed"].strip()
    days = None
    if rep and dt.date.fromisoformat(rep) <= today:
        status = "폐지"
    elif eff > today:
        status, days = "시행 예정", (eff - today).days
    else:
        status = "시행 중"
    out = {"notice_id": r["notice_id"], "title": r["title"], "category": r["category"],
           "issuer": r["issuer"], "published": r["published"], "effective_from": r["effective_from"],
           "repealed": rep or None, "status": status, "days_until": days,
           "source_url": r["source_url"], "summary": r["summary"],
           "has_summary": bool(r["summary"].strip())}
    if with_original:
        out["original"] = r["original"]
    return out


def err(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/api/categories")
def categories():
    return CATEGORIES


@app.get("/api/notices")
def list_notices(category: str = "", q: str = "", include_repealed: str = "0"):
    if category and category not in CATEGORIES:
        return err(400, "알 수 없는 분야입니다")
    if include_repealed not in ("0", "1"):
        return err(400, "include_repealed 는 0 또는 1 이어야 합니다")
    today = dt.date.today()
    words = q.split()
    items = []
    for r in rows():
        if category and r["category"] != category:
            continue
        hay = r["title"] + "\n" + r["summary"] + "\n" + r["original"]
        if not all(w in hay for w in words):
            continue
        it = shape(r, today)
        if it["status"] == "폐지" and include_repealed == "0":
            continue
        items.append(it)
    return {"as_of": today.isoformat(), "count": len(items), "items": items}


@app.get("/api/notices/{notice_id}")
def get_notice(notice_id: str):
    for r in rows():
        if r["notice_id"] == notice_id:
            return shape(r, dt.date.today(), True)
    return err(404, "없는 고시입니다")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
