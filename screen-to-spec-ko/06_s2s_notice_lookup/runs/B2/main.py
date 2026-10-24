import csv
import os
import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).parent
SEED = ROOT / "seed" / "notices.csv"
DB_PATH = ROOT / "notice.db"
CATEGORIES = ["주차", "위생", "건축", "복지"]
COLUMNS = ["notice_id", "title", "category", "issuer", "published", "effective_from",
           "repealed", "source_url", "original", "summary"]

app = FastAPI()


def build_db():
    """시작할 때마다 CSV 로 SQLite 를 새로 만든다."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE nt_notices (%s)" % ", ".join(f"{c} TEXT" for c in COLUMNS))
    with open(SEED, encoding="utf-8-sig", newline="") as f:
        rows = [[(r.get(c) or "").strip() for c in COLUMNS] for r in csv.DictReader(f)]
    con.executemany(
        "INSERT INTO nt_notices VALUES (%s)" % ", ".join("?" * len(COLUMNS)), rows)
    con.commit()
    con.close()


build_db()


def fetch_all():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # R3: 출처 없는 행은 어디에도 싣지 않는다.
    rows = con.execute("SELECT * FROM nt_notices WHERE source_url <> ''").fetchall()
    con.close()
    return [dict(r) for r in rows]


def to_item(row, today, with_original=False):
    published = row["published"]
    status, days_until = "시행 중", None
    if row["repealed"] and date.fromisoformat(row["repealed"]) <= today:
        status = "폐지"
    elif date.fromisoformat(row["effective_from"]) > today:
        status = "시행 예정"
        days_until = (date.fromisoformat(row["effective_from"]) - today).days
    item = {
        "notice_id": row["notice_id"], "title": row["title"], "category": row["category"],
        "issuer": row["issuer"], "published": published,
        "effective_from": row["effective_from"], "repealed": row["repealed"] or None,
        "status": status, "days_until": days_until, "source_url": row["source_url"],
        "summary": row["summary"], "has_summary": bool(row["summary"]),
    }
    if with_original:
        item["original"] = row["original"]
    return item


def bad_request(detail):
    return JSONResponse({"detail": detail}, status_code=400)


@app.get("/api/categories")
def categories():
    return CATEGORIES


@app.get("/api/notices")
def notices(category: str = Query(""), q: str = Query(""), include_repealed: str = Query("0")):
    if category and category not in CATEGORIES:
        return bad_request("알 수 없는 분야입니다")
    if include_repealed not in ("0", "1"):
        return bad_request("include_repealed 는 0 또는 1 이어야 합니다")
    today = date.today()
    terms = q.lower().split()
    items = []
    for row in fetch_all():
        if category and row["category"] != category:
            continue
        haystack = " ".join((row["title"], row["summary"], row["original"])).lower()
        if not all(t in haystack for t in terms):
            continue
        item = to_item(row, today)
        if item["status"] == "폐지" and include_repealed == "0":
            continue
        items.append(item)
    # R6: 공고일 최신 먼저, 같으면 notice_id 순
    items.sort(key=lambda i: i["notice_id"])
    items.sort(key=lambda i: i["published"], reverse=True)
    return {"as_of": today.isoformat(), "count": len(items), "items": items}


@app.get("/api/notices/{notice_id}")
def notice_detail(notice_id: str):
    for row in fetch_all():
        if row["notice_id"] == notice_id:
            return to_item(row, date.today(), with_original=True)
    return JSONResponse({"detail": "고시를 찾을 수 없습니다"}, status_code=404)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
