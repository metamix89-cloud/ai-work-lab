# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R7 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "notice.db")
CATS = ["주차", "위생", "건축", "복지"]
COLS = ["notice_id", "title", "category", "issuer", "published", "effective_from", "repealed", "source_url", "original", "summary"]
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE nt_notices(%s)" % ", ".join(c + " TEXT" for c in COLS))
    p = os.path.join(SEED, "notices.csv")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            rows = [r for r in csv.reader(f)][1:]
        con.executemany("INSERT INTO nt_notices VALUES (%s)" % ",".join("?" * len(COLS)), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def view(r, today, full=False):
    d = dict(r)
    if d["repealed"] and d["repealed"] <= today.isoformat():
        status, days = "폐지", None
    elif d["effective_from"] > today.isoformat():
        status, days = "시행 예정", (dt.date.fromisoformat(d["effective_from"]) - today).days
    else:
        status, days = "시행 중", None
    d.update(status=status, days_until=days, has_summary=bool(d["summary"]))
    if not full:
        d.pop("original")
    return d


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/categories")
def categories():
    return CATS


@app.get("/api/notices")
def notices(category: str = "", q: str = "", include_repealed: str = "0"):
    if category and category not in CATS:
        raise HTTPException(400, "알 수 없는 분야입니다")
    if include_repealed not in ("0", "1"):
        raise HTTPException(400, "include_repealed 는 0 또는 1 입니다")
    today = dt.date.today()
    words = [w.lower() for w in q.split() if w.strip()]
    items = []
    for r in con().execute("SELECT * FROM nt_notices WHERE source_url<>''"):
        v = view(r, today)
        if v["status"] == "폐지" and include_repealed == "0":
            continue
        if category and v["category"] != category:
            continue
        text = (r["title"] + " " + r["summary"] + " " + r["original"]).lower()
        if words and not all(w in text for w in words):
            continue
        items.append(v)
    items.sort(key=lambda x: x["notice_id"])
    items.sort(key=lambda x: x["published"], reverse=True)
    return {"as_of": today.isoformat(), "count": len(items), "items": items}


@app.get("/api/notices/{notice_id}")
def notice(notice_id: str):
    r = con().execute("SELECT * FROM nt_notices WHERE notice_id=? AND source_url<>''", (notice_id,)).fetchone()
    if not r:
        raise HTTPException(404, "고시가 없습니다")
    return view(r, dt.date.today(), full=True)
