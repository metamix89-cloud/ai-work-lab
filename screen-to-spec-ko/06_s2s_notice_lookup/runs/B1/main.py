import csv
import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
SEED = BASE / "seed" / "notices.csv"
DB = BASE / "notice.db"
CATEGORIES = ["주차", "위생", "건축", "복지"]
COLS = ["notice_id", "title", "category", "issuer", "published", "effective_from",
        "repealed", "source_url", "original", "summary"]


def build_db():
    """서버 시작 때마다 CSV 로 SQLite 를 새로 만든다."""
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.execute(f"CREATE TABLE nt_notices ({', '.join(c + ' TEXT' for c in COLS)})")
    with open(SEED, newline="", encoding="utf-8-sig") as f:
        rows = [[(r.get(c) or "").strip() for c in COLS] for r in csv.DictReader(f)]
    con.executemany(f"INSERT INTO nt_notices VALUES ({','.join('?' * len(COLS))})", rows)
    con.commit()
    con.close()


build_db()
app = FastAPI()


def query_all():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        # R3: 출처 없는 행은 어디에도 싣지 않는다. R6: 공고일 최신 먼저, 같으면 notice_id 순
        return [dict(r) for r in con.execute(
            "SELECT * FROM nt_notices WHERE source_url <> '' "
            "ORDER BY published DESC, notice_id ASC")]
    finally:
        con.close()


def shape(row, today, with_original=False):
    # R1: 상태는 기준일로 셈
    days = None
    if row["repealed"] and date.fromisoformat(row["repealed"]) <= today:
        status = "폐지"
    elif date.fromisoformat(row["effective_from"]) > today:
        status = "시행 예정"
        days = (date.fromisoformat(row["effective_from"]) - today).days
    else:
        status = "시행 중"
    out = {k: row[k] for k in ["notice_id", "title", "category", "issuer", "published",
                               "effective_from", "repealed", "source_url", "summary"]}
    out.update(status=status, days_until=days, has_summary=bool(row["summary"]))
    if with_original:
        out["original"] = row["original"]
    return out


@app.get("/api/categories")
def categories():
    return CATEGORIES


@app.get("/api/notices")
def notices(category: str = "", q: str = "", include_repealed: str = "0"):
    if category and category not in CATEGORIES:
        raise HTTPException(400, "알 수 없는 분야입니다")
    if include_repealed not in ("0", "1"):
        raise HTTPException(400, "include_repealed 는 0 또는 1 이어야 합니다")
    today = date.today()
    words = q.lower().split()
    items = []
    for r in query_all():
        if category and r["category"] != category:
            continue
        hay = (r["title"] + " " + r["summary"] + " " + r["original"]).lower()
        if not all(w in hay for w in words):  # R5: 단어 모두 포함
            continue
        it = shape(r, today)
        if it["status"] == "폐지" and include_repealed == "0":
            continue
        items.append(it)
    return {"as_of": today.isoformat(), "count": len(items), "items": items}


@app.get("/api/notices/{notice_id}")
def notice(notice_id: str):
    for r in query_all():
        if r["notice_id"] == notice_id:
            return shape(r, date.today(), with_original=True)
    raise HTTPException(404, "없는 고시입니다")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
