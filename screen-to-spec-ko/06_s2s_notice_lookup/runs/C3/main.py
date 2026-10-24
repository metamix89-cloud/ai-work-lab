import csv
import datetime as dt
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "notice.db")
CATEGORIES = ["주차", "위생", "건축", "복지"]
COLS = ["notice_id", "title", "category", "issuer", "published", "effective_from",
        "repealed", "source_url", "original", "summary"]


def load_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE nt_notices (%s)" % ", ".join(c + " TEXT" for c in COLS))
    with open(os.path.join(BASE, "seed", "notices.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            con.execute("INSERT INTO nt_notices VALUES (%s)" % ",".join("?" * len(COLS)),
                        [(r.get(c) or "").strip() if c not in ("original", "summary") else (r.get(c) or "") for c in COLS])
    con.commit()
    con.close()


@asynccontextmanager
async def lifespan(_app):
    load_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def bad_input(_req, _exc):
    return JSONResponse({"detail": "잘못된 입력입니다"}, status_code=400)


def rows():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        # R3: 출처 없는 행은 어디에도 싣지 않는다
        return [dict(r) for r in con.execute("SELECT * FROM nt_notices WHERE TRIM(source_url) <> ''")]
    finally:
        con.close()


def shape(r, today, with_original=False):
    eff = dt.date.fromisoformat(r["effective_from"])
    if r["repealed"] and dt.date.fromisoformat(r["repealed"]) <= today:
        status, days = "폐지", None
    elif eff > today:
        status, days = "시행 예정", (eff - today).days
    else:
        status, days = "시행 중", None
    out = {
        "notice_id": r["notice_id"], "title": r["title"], "category": r["category"],
        "issuer": r["issuer"], "published": r["published"], "effective_from": r["effective_from"],
        "repealed": r["repealed"] or None, "status": status, "days_until": days,
        "source_url": r["source_url"], "summary": r["summary"],
        "has_summary": bool(r["summary"].strip()),
    }
    if with_original:
        out["original"] = r["original"]
    return out


@app.get("/api/categories")
def categories():
    return CATEGORIES


@app.get("/api/notices")
def list_notices(category: Optional[str] = None, q: Optional[str] = None,
                 include_repealed: str = "0"):
    if category and category not in CATEGORIES:
        raise HTTPException(400, "알 수 없는 분야입니다")
    if include_repealed not in ("0", "1"):
        raise HTTPException(400, "include_repealed 는 0 또는 1 이어야 합니다")
    today = dt.date.today()
    terms = (q or "").lower().split()
    items = []
    for r in rows():
        if category and r["category"] != category:
            continue
        hay = (r["title"] + " " + r["summary"] + " " + r["original"]).lower()
        if not all(t in hay for t in terms):
            continue
        s = shape(r, today)
        if s["status"] == "폐지" and include_repealed == "0":
            continue
        items.append(s)
    items.sort(key=lambda i: i["notice_id"])
    items.sort(key=lambda i: i["published"], reverse=True)
    return {"as_of": today.isoformat(), "count": len(items), "items": items}


@app.get("/api/notices/{notice_id}")
def get_notice(notice_id: str):
    for r in rows():
        if r["notice_id"] == notice_id:
            return shape(r, dt.date.today(), with_original=True)
    raise HTTPException(404, "없는 고시입니다")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
