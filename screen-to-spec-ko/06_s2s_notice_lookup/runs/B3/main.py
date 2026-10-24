import csv
import os
import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).parent
SEED = ROOT / "seed" / "notices.csv"
DB = ROOT / "notice.db"
CATEGORIES = ["주차", "위생", "건축", "복지"]
COLS = ["notice_id", "title", "category", "issuer", "published",
        "effective_from", "repealed", "source_url", "original", "summary"]


def build_db():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE nt_notices (%s)" % ", ".join(c + " TEXT" for c in COLS))
    with open(SEED, encoding="utf-8-sig", newline="") as f:
        rows = [[(r.get(c) or "").strip() for c in COLS] for r in csv.DictReader(f)]
    con.executemany("INSERT INTO nt_notices VALUES (%s)" % ",".join("?" * len(COLS)), rows)
    con.commit()
    con.close()


build_db()
app = FastAPI()


@app.exception_handler(HTTPException)
async def http_exc(_, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def today():
    return date.today()


def shape(row, as_of, with_original=False):
    d = dict(zip(COLS, row))
    eff = date.fromisoformat(d["effective_from"])
    if d["repealed"] and date.fromisoformat(d["repealed"]) <= as_of:
        status, days = "폐지", None
    elif eff > as_of:
        status, days = "시행 예정", (eff - as_of).days
    else:
        status, days = "시행 중", None
    out = {k: d[k] for k in ("notice_id", "title", "category", "issuer", "published",
                             "effective_from", "repealed")}
    out.update(status=status, days_until=days, source_url=d["source_url"],
               summary=d["summary"], has_summary=bool(d["summary"]))
    if with_original:
        out["original"] = d["original"]
    return out


def query(sql, args=()):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@app.get("/api/categories")
def categories():
    return CATEGORIES


@app.get("/api/notices")
def notices(category: str = "", q: str = "", include_repealed: str = "0"):
    if category and category not in CATEGORIES:
        raise HTTPException(400, "알 수 없는 분야입니다")
    if include_repealed not in ("0", "1"):
        raise HTTPException(400, "include_repealed 는 0 또는 1 이어야 합니다")
    as_of = today()
    sql = "SELECT %s FROM nt_notices WHERE source_url != ''" % ",".join(COLS)
    args = []
    if category:
        sql += " AND category = ?"
        args.append(category)
    for w in q.split():
        sql += " AND (title LIKE ? OR summary LIKE ? OR original LIKE ?)"
        args += ["%" + w + "%"] * 3
    items = [shape(r, as_of) for r in query(sql, args)]
    if include_repealed == "0":
        items = [i for i in items if i["status"] != "폐지"]
    items.sort(key=lambda i: i["notice_id"])
    items.sort(key=lambda i: i["published"], reverse=True)
    return {"as_of": as_of.isoformat(), "count": len(items), "items": items}


@app.get("/api/notices/{notice_id}")
def notice(notice_id: str):
    rows = query("SELECT %s FROM nt_notices WHERE notice_id = ? AND source_url != ''"
                 % ",".join(COLS), (notice_id,))
    if not rows:
        raise HTTPException(404, "없는 고시입니다")
    return shape(rows[0], today(), with_original=True)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
