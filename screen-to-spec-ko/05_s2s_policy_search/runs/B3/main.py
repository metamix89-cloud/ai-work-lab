import csv
import html
import os
import re
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed", "clauses.csv")
DB = os.path.join(BASE, "policy.db")
INDEX = os.path.join(BASE, "static", "index.html")

COLS = ["clause_id", "doc", "article", "title", "body", "effective_from", "effective_to"]


def build_db():
    """서버가 시작될 때마다 CSV 에서 SQLite 를 새로 만든다."""
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except FileNotFoundError:
            pass
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE pl_clauses ("
        "clause_id TEXT PRIMARY KEY, doc TEXT NOT NULL, article TEXT NOT NULL, "
        "title TEXT NOT NULL, body TEXT NOT NULL, "
        "effective_from TEXT NOT NULL, effective_to TEXT)"
    )
    with open(SEED, encoding="utf-8-sig", newline="") as f:
        rows = [
            tuple((r.get(c) or "").strip() if c != "effective_to" else ((r.get(c) or "").strip() or None)
                  for c in COLS)
            for r in csv.DictReader(f)
        ]
    con.executemany("INSERT INTO pl_clauses VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


build_db()

app = FastAPI()


def query(sql, params=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def error(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return error(400, "검색어를 입력하세요")


def has_history(row):
    n = query(
        "SELECT COUNT(*) AS n FROM pl_clauses WHERE doc=? AND article=? "
        "AND effective_to IS NOT NULL AND clause_id<>?",
        (row["doc"], row["article"], row["clause_id"]),
    )[0]["n"]
    return n > 0


def make_snippet(body, words):
    low = body.lower()
    pos = [low.find(w) for w in words if low.find(w) >= 0]
    if pos:
        start = min(pos)
        first_len = next(len(w) for w in words if low.find(w) == start)
        lo = max(0, start - 40)
        hi = min(len(body), start + first_len + 40)
    else:
        lo, hi = 0, min(len(body), 80)
    text = html.escape(body[lo:hi], quote=False)
    pattern = re.compile("|".join(re.escape(html.escape(w, quote=False)) for w in
                                  sorted(words, key=len, reverse=True)), re.IGNORECASE)
    text = pattern.sub(lambda m: "<mark>" + m.group(0) + "</mark>", text)
    return ("…" if lo > 0 else "") + text + ("…" if hi < len(body) else "")


@app.get("/api/docs")
def docs():
    return query(
        "SELECT doc, COUNT(*) AS count FROM pl_clauses WHERE effective_to IS NULL "
        "GROUP BY doc ORDER BY MIN(clause_id)"
    )


@app.get("/api/search")
def search(q: str = ""):
    words = q.lower().split()
    if not words:
        return error(400, "검색어를 입력하세요")
    rows = query("SELECT * FROM pl_clauses WHERE effective_to IS NULL")
    hits = []
    for r in rows:
        hay = (r["title"] + "\n" + r["body"]).lower()
        if all(w in hay for w in words):
            hits.append(r)

    def sort_key(r):
        in_title = any(w in r["title"].lower() for w in words)
        # 제목 매칭 먼저, 시행일 최신 먼저, clause_id 순
        return (not in_title, tuple(-ord(c) for c in r["effective_from"]), r["clause_id"])

    hits.sort(key=sort_key)
    results = [
        {
            "clause_id": r["clause_id"],
            "doc": r["doc"],
            "article": r["article"],
            "title": r["title"],
            "effective_from": r["effective_from"],
            "snippet": make_snippet(r["body"], words),
            "has_history": has_history(r),
        }
        for r in hits
    ]
    return {"query": q.strip(), "count": len(results), "results": results}


def get_clause(clause_id):
    rows = query("SELECT * FROM pl_clauses WHERE clause_id=?", (clause_id,))
    return rows[0] if rows else None


@app.get("/api/clauses/{clause_id}")
def clause(clause_id: str):
    r = get_clause(clause_id)
    if r is None:
        return error(404, "조항을 찾을 수 없습니다")
    r["has_history"] = has_history(r)
    return r


@app.get("/api/clauses/{clause_id}/history")
def history(clause_id: str):
    r = get_clause(clause_id)
    if r is None:
        return error(404, "조항을 찾을 수 없습니다")
    return query(
        "SELECT clause_id, effective_from, effective_to, body FROM pl_clauses "
        "WHERE doc=? AND article=? AND effective_to IS NOT NULL AND clause_id<>? "
        "ORDER BY effective_from DESC, clause_id",
        (r["doc"], r["article"], clause_id),
    )


@app.get("/")
def index():
    return FileResponse(INDEX, media_type="text/html; charset=utf-8")
