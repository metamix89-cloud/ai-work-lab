import csv
import html
import os
import re
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "policy.db"
CSV_PATH = BASE / "seed" / "clauses.csv"

app = FastAPI()


def build_db():
    """시작할 때마다 CSV 로 SQLite 를 새로 만든다."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE pl_clauses (clause_id TEXT PRIMARY KEY, doc TEXT, article TEXT, "
        "title TEXT, body TEXT, effective_from TEXT, effective_to TEXT)"
    )
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = [
            (r["clause_id"].strip(), r["doc"], r["article"], r["title"], r["body"],
             r["effective_from"], (r["effective_to"] or "").strip())
            for r in csv.DictReader(f)
        ]
    con.executemany("INSERT INTO pl_clauses VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


build_db()


def query(sql, args=()):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def has_history(row):
    if row["effective_to"]:
        return False
    return bool(query(
        "SELECT 1 FROM pl_clauses WHERE doc=? AND article=? AND effective_to<>'' LIMIT 1",
        (row["doc"], row["article"]),
    ))


def make_snippet(body, words):
    """첫 매칭 단어 앞뒤 40자를 잘라 매칭 단어를 <mark> 로 감싼다."""
    low = body.lower()
    pos, first = min((low.find(w), w) for w in words if w in low)
    start, end = max(0, pos - 40), pos + len(first) + 40
    text = html.escape(body[start:end])
    pattern = "|".join(
        re.escape(html.escape(w)) for w in sorted(set(words), key=len, reverse=True)
    )
    text = re.sub(f"({pattern})", r"<mark>\1</mark>", text, flags=re.IGNORECASE)
    return ("…" if start > 0 else "") + text + ("…" if end < len(body) else "")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/docs")
def docs():
    return query(
        "SELECT doc, COUNT(*) AS count FROM pl_clauses WHERE effective_to='' "
        "GROUP BY doc ORDER BY MIN(rowid)"
    )


@app.get("/api/search")
def search(q: str = Query("")):
    words = q.lower().split()
    if not words:
        return err(400, "검색어를 입력하세요")
    results = [
        r for r in query("SELECT * FROM pl_clauses WHERE effective_to=''")
        if all(w in r["title"].lower() or w in r["body"].lower() for w in words)
    ]
    # R5: 제목 매칭 먼저 → 시행일 최신 먼저 → clause_id 순 (안정 정렬을 거꾸로 적용)
    results.sort(key=lambda r: r["clause_id"])
    results.sort(key=lambda r: r["effective_from"], reverse=True)
    results.sort(key=lambda r: not any(w in r["title"].lower() for w in words))
    out = [{
        "clause_id": r["clause_id"], "doc": r["doc"], "article": r["article"],
        "title": r["title"], "effective_from": r["effective_from"],
        "snippet": make_snippet(r["body"], words), "has_history": has_history(r),
    } for r in results]
    return {"query": q.strip(), "count": len(out), "results": out}


@app.get("/api/clauses/{clause_id}")
def clause(clause_id: str):
    rows = query("SELECT * FROM pl_clauses WHERE clause_id=?", (clause_id,))
    if not rows:
        return err(404, "해당 조항이 없습니다")
    r = rows[0]
    r["has_history"] = has_history(r)
    return r


@app.get("/api/clauses/{clause_id}/history")
def history(clause_id: str):
    rows = query("SELECT * FROM pl_clauses WHERE clause_id=?", (clause_id,))
    if not rows:
        return err(404, "해당 조항이 없습니다")
    r = rows[0]
    if r["effective_to"]:
        return []
    return query(
        "SELECT clause_id, effective_from, effective_to, body FROM pl_clauses "
        "WHERE doc=? AND article=? AND effective_to<>'' ORDER BY effective_from DESC",
        (r["doc"], r["article"]),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
