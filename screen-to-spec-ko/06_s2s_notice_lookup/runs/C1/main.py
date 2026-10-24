import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "notice.db")
CATEGORIES = ["주차", "위생", "건축", "복지"]
COLS = ["notice_id", "title", "category", "issuer", "published", "effective_from",
        "repealed", "source_url", "original", "summary"]

app = FastAPI()


def load_seed():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE nt_notices (%s)" % ", ".join(
        c + (" TEXT PRIMARY KEY" if c == "notice_id" else " TEXT") for c in COLS))
    with open(os.path.join(BASE, "seed", "notices.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            vals = [(r.get(c) or "") if c in ("original", "summary") else (r.get(c) or "").strip()
                    for c in COLS]
            con.execute("INSERT OR REPLACE INTO nt_notices VALUES (%s)" % ",".join("?" * len(COLS)), vals)
    con.commit()
    con.close()


load_seed()


def rows():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM nt_notices WHERE source_url != ''")]
    finally:
        con.close()


def shape(r, today, with_original=False):
    if r["repealed"] and r["repealed"] <= today.isoformat():
        status, days = "폐지", None
    elif r["effective_from"] > today.isoformat():
        status = "시행 예정"
        days = (dt.date.fromisoformat(r["effective_from"]) - today).days
    else:
        status, days = "시행 중", None
    out = {
        "notice_id": r["notice_id"], "title": r["title"], "category": r["category"],
        "issuer": r["issuer"], "published": r["published"],
        "effective_from": r["effective_from"], "repealed": r["repealed"],
        "status": status, "days_until": days, "source_url": r["source_url"],
        "summary": r["summary"], "has_summary": bool(r["summary"].strip()),
    }
    if with_original:
        out["original"] = r["original"]
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/categories")
def categories():
    return CATEGORIES


@app.get("/api/notices")
def notices(category: str = "", q: str = "", include_repealed: str = "0"):
    if category and category not in CATEGORIES:
        raise HTTPException(400, "알 수 없는 분야입니다")
    if include_repealed not in ("0", "1"):
        raise HTTPException(400, "include_repealed 는 0 또는 1 이어야 합니다")
    today = dt.date.today()
    terms = q.lower().split()
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
    items.sort(key=lambda s: s["notice_id"])
    items.sort(key=lambda s: s["published"], reverse=True)
    return {"as_of": today.isoformat(), "count": len(items), "items": items}


@app.get("/api/notices/{notice_id}")
def notice(notice_id: str):
    for r in rows():
        if r["notice_id"] == notice_id:
            return shape(r, dt.date.today(), True)
    raise HTTPException(404, "고시를 찾을 수 없습니다")
