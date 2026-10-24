import csv
import html
import os
import re
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "policy.db")
SEED = os.path.join(ROOT, "seed", "clauses.csv")

app = FastAPI()


def build_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE pl_clauses (clause_id TEXT PRIMARY KEY, doc TEXT, article TEXT, title TEXT,"
        " body TEXT, effective_from TEXT, effective_to TEXT)"
    )
    with open(SEED, encoding="utf-8-sig", newline="") as f:
        rows = [
            (r["clause_id"], r["doc"], r["article"], r["title"], r["body"],
             r["effective_from"], (r.get("effective_to") or "").strip())
            for r in csv.DictReader(f)
        ]
    con.executemany("INSERT INTO pl_clauses VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


build_db()


def query(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def old_versions(row):
    return query(
        "SELECT * FROM pl_clauses WHERE doc=? AND article=? AND effective_to<>'' AND clause_id<>?"
        " ORDER BY effective_from DESC, clause_id DESC",
        (row["doc"], row["article"], row["clause_id"]),
    )


def snippet(body, words):
    low = body.lower()
    found = [(low.find(w), w) for w in words if low.find(w) >= 0]
    if found:
        first, w = min(found)
        start, end = max(0, first - 40), min(len(body), first + len(w) + 40)
    else:
        start, end = 0, min(len(body), 80)
    text = html.escape(body[start:end], quote=False)
    pat = re.compile(
        "|".join(re.escape(html.escape(w, quote=False)) for w in sorted(words, key=len, reverse=True)),
        re.I,
    )
    text = pat.sub(lambda m: "<mark>" + m.group(0) + "</mark>", text)
    return ("…" if start > 0 else "") + text + ("…" if end < len(body) else "")


@app.get("/api/docs")
def docs():
    return query(
        "SELECT doc, COUNT(*) AS count FROM pl_clauses WHERE effective_to='' GROUP BY doc ORDER BY MIN(rowid)"
    )


@app.get("/api/search")
def search(q: str = Query("")):
    words = q.lower().split()
    if not words:
        raise HTTPException(400, "검색어를 입력하세요")
    hits = []
    for r in query("SELECT * FROM pl_clauses WHERE effective_to=''"):
        t, b = r["title"].lower(), r["body"].lower()
        if all(w in t or w in b for w in words):
            hits.append((r, any(w in t for w in words)))
    hits.sort(key=lambda h: h[0]["clause_id"])
    hits.sort(key=lambda h: h[0]["effective_from"], reverse=True)
    hits.sort(key=lambda h: not h[1])
    results = [
        {
            "clause_id": r["clause_id"], "doc": r["doc"], "article": r["article"], "title": r["title"],
            "effective_from": r["effective_from"], "snippet": snippet(r["body"], words),
            "has_history": bool(old_versions(r)),
        }
        for r, _ in hits
    ]
    return {"query": q.strip(), "count": len(results), "results": results}


def get_clause(clause_id):
    rows = query("SELECT * FROM pl_clauses WHERE clause_id=?", (clause_id,))
    if not rows:
        raise HTTPException(404, "해당 조항이 없습니다")
    return rows[0]


@app.get("/api/clauses/{clause_id}/history")
def history(clause_id: str):
    r = get_clause(clause_id)
    return [
        {"clause_id": h["clause_id"], "effective_from": h["effective_from"],
         "effective_to": h["effective_to"], "body": h["body"]}
        for h in old_versions(r)
    ]


@app.get("/api/clauses/{clause_id}")
def clause(clause_id: str):
    r = get_clause(clause_id)
    r["effective_to"] = r["effective_to"] or None
    r["has_history"] = bool(old_versions(r))
    return r


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))
