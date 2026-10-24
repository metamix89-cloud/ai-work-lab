import csv
import html
import os
import re
import sqlite3
from datetime import date

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "policy.db")
COLS = ["clause_id", "doc", "article", "title", "body", "effective_from", "effective_to"]


def load_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE pl_clauses (clause_id TEXT PRIMARY KEY, doc TEXT, article TEXT, "
        "title TEXT, body TEXT, effective_from TEXT, effective_to TEXT)"
    )
    with open(os.path.join(BASE, "seed", "clauses.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            con.execute(
                "INSERT INTO pl_clauses VALUES (?,?,?,?,?,?,?)",
                [(r.get(c) or "").strip() for c in COLS],
            )
    con.commit()
    con.close()


load_db()
app = FastAPI()


def query(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def has_history(row):
    return bool(query(
        "SELECT 1 FROM pl_clauses WHERE doc=? AND article=? AND effective_to!='' AND clause_id!=? LIMIT 1",
        (row["doc"], row["article"], row["clause_id"]),
    ))


def snippet(text, words):
    low = text.lower()
    hits = [(low.find(w), w) for w in words if w in low]
    if not hits:
        return html.escape(text[:80])
    start, first = min(hits)
    a = max(0, start - 40)
    b = min(len(text), start + len(first) + 40)
    part = text[a:b]
    pat = re.compile("|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)), re.I)
    out, last = [], 0
    for m in pat.finditer(part):
        out.append(html.escape(part[last:m.start()]))
        out.append("<mark>" + html.escape(m.group(0)) + "</mark>")
        last = m.end()
    out.append(html.escape(part[last:]))
    return ("…" if a > 0 else "") + "".join(out) + ("…" if b < len(text) else "")


@app.get("/api/docs")
def docs():
    return query(
        "SELECT doc, COUNT(*) AS count FROM pl_clauses WHERE effective_to='' "
        "GROUP BY doc ORDER BY MIN(rowid)"
    )


@app.get("/api/search")
def search(q: str = ""):
    words = q.strip().lower().split()
    if not words:
        return err(400, "검색어를 입력하세요")
    found = []
    for r in query("SELECT * FROM pl_clauses WHERE effective_to=''"):
        t, b = r["title"].lower(), r["body"].lower()
        if all(w in t or w in b for w in words):
            r["in_title"] = any(w in t for w in words)
            found.append(r)
    # R5: 제목 매칭 먼저 → 시행일 최신 먼저 → clause_id 순 (안정 정렬 3회)
    found.sort(key=lambda r: r["clause_id"])
    found.sort(key=lambda r: r["effective_from"], reverse=True)
    found.sort(key=lambda r: not r["in_title"])
    results = [{
        "clause_id": r["clause_id"], "doc": r["doc"], "article": r["article"], "title": r["title"],
        "effective_from": r["effective_from"], "snippet": snippet(r["body"], words),
        "has_history": has_history(r),
    } for r in found]
    return {"query": q.strip(), "count": len(results), "results": results}


@app.get("/api/clauses/{cid}")
def clause(cid: str):
    rows = query("SELECT * FROM pl_clauses WHERE clause_id=?", (cid,))
    if not rows:
        return err(404, "조항을 찾을 수 없습니다")
    r = rows[0]
    r["has_history"] = has_history(r)
    return r


@app.get("/api/clauses/{cid}/history")
def history(cid: str):
    rows = query("SELECT * FROM pl_clauses WHERE clause_id=?", (cid,))
    if not rows:
        return err(404, "조항을 찾을 수 없습니다")
    r = rows[0]
    return query(
        "SELECT clause_id, effective_from, effective_to, body FROM pl_clauses "
        "WHERE doc=? AND article=? AND effective_to!='' AND clause_id!=? ORDER BY effective_from DESC",
        (r["doc"], r["article"], cid),
    )


@app.get("/api/today")
def today():
    return {"today": date.today().isoformat()}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
