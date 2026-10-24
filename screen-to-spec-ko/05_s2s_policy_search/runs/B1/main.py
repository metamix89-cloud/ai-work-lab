import csv
import html
import os
import re
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "policy.db"
CSV_PATH = BASE / "seed" / "clauses.csv"

app = FastAPI()


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    c = sqlite3.connect(DB_PATH)
    c.execute(
        """CREATE TABLE pl_clauses (
        clause_id TEXT PRIMARY KEY, doc TEXT, article TEXT, title TEXT, body TEXT,
        effective_from TEXT, effective_to TEXT)"""
    )
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = [
            (r["clause_id"], r["doc"], r["article"], r["title"], r["body"],
             r["effective_from"], (r["effective_to"] or "").strip() or None)
            for r in csv.DictReader(f)
        ]
    c.executemany("INSERT INTO pl_clauses VALUES (?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()


init_db()


def has_history(db, row):
    if row["effective_to"] is not None:
        return False
    n = db.execute(
        "SELECT COUNT(*) FROM pl_clauses WHERE doc=? AND article=? AND effective_to IS NOT NULL",
        (row["doc"], row["article"]),
    ).fetchone()[0]
    return n > 0


def snippet(row, words):
    text = row["body"]
    low = text.lower()
    found = [(low.find(w), w) for w in words if w in low]
    if not found:  # 제목에만 있는 경우
        text = row["title"]
        low = text.lower()
        found = [(low.find(w), w) for w in words if w in low]
    pos, hit = min(found)
    start = max(0, pos - 40)
    end = min(len(text), pos + len(hit) + 40)
    out = html.escape(text[start:end])
    pattern = "|".join(re.escape(html.escape(w)) for w in words)
    out = re.sub(f"({pattern})", r"<mark>\1</mark>", out, flags=re.I)
    return ("…" if start > 0 else "") + out + ("…" if end < len(text) else "")


@app.get("/api/docs")
def docs():
    db = conn()
    rows = db.execute(
        "SELECT doc, COUNT(*) AS count FROM pl_clauses WHERE effective_to IS NULL "
        "GROUP BY doc ORDER BY MIN(clause_id)"
    ).fetchall()
    db.close()
    return [{"doc": r["doc"], "count": r["count"]} for r in rows]


@app.get("/api/asof")
def asof():
    db = conn()
    v = db.execute(
        "SELECT MAX(effective_from) FROM pl_clauses WHERE effective_to IS NULL"
    ).fetchone()[0]
    db.close()
    return {"asof": v}


@app.get("/api/search")
def search(q: str = ""):
    words = q.strip().lower().split()
    if not words:
        raise HTTPException(400, "검색어를 입력하세요")
    db = conn()
    rows = db.execute("SELECT * FROM pl_clauses WHERE effective_to IS NULL").fetchall()
    hits = [
        r for r in rows
        if all(w in r["title"].lower() or w in r["body"].lower() for w in words)
    ]
    hits.sort(key=lambda r: r["clause_id"])
    hits.sort(key=lambda r: r["effective_from"], reverse=True)
    hits.sort(key=lambda r: not any(w in r["title"].lower() for w in words))
    results = [
        {
            "clause_id": r["clause_id"], "doc": r["doc"], "article": r["article"],
            "title": r["title"], "effective_from": r["effective_from"],
            "snippet": snippet(r, words), "has_history": has_history(db, r),
        }
        for r in hits
    ]
    db.close()
    return {"query": q.strip(), "count": len(results), "results": results}


def get_row(db, clause_id):
    r = db.execute("SELECT * FROM pl_clauses WHERE clause_id=?", (clause_id,)).fetchone()
    if r is None:
        db.close()
        raise HTTPException(404, "해당 조항이 없습니다")
    return r


@app.get("/api/clauses/{clause_id}")
def clause(clause_id: str):
    db = conn()
    r = get_row(db, clause_id)
    out = dict(r)
    out["has_history"] = has_history(db, r)
    db.close()
    return out


@app.get("/api/clauses/{clause_id}/history")
def history(clause_id: str):
    db = conn()
    r = get_row(db, clause_id)
    rows = db.execute(
        "SELECT clause_id, effective_from, effective_to, body FROM pl_clauses "
        "WHERE doc=? AND article=? AND effective_to IS NOT NULL AND clause_id<>? "
        "ORDER BY effective_from DESC",
        (r["doc"], r["article"], clause_id),
    ).fetchall()
    db.close()
    return [dict(x) for x in rows]


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
