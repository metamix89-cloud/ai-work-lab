import csv
import datetime
import os
import re
import sqlite3
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "policy.db")
CSV = os.path.join(BASE, "seed", "clauses.csv")
COLS = ["clause_id", "doc", "article", "title", "body", "effective_from", "effective_to"]

app = FastAPI()
_lock = threading.Lock()


def build_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE pl_clauses (clause_id TEXT PRIMARY KEY, doc TEXT, article TEXT, title TEXT, "
        "body TEXT, effective_from TEXT, effective_to TEXT)"
    )
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            con.execute(
                "INSERT INTO pl_clauses VALUES (?,?,?,?,?,?,?)",
                [(r.get(c) or "").strip() for c in COLS],
            )
    con.commit()
    con.close()


build_db()


def query(sql, args=()):
    with _lock:
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, args).fetchall()]
        finally:
            con.close()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def has_history(row):
    n = query(
        "SELECT COUNT(*) AS n FROM pl_clauses WHERE doc=? AND article=? AND effective_to<>'' AND clause_id<>?",
        (row["doc"], row["article"], row["clause_id"]),
    )
    return n[0]["n"] > 0


def snippet(body, words):
    low = body.lower()
    pos = [(low.find(w), w) for w in words if low.find(w) >= 0]
    if pos:
        first, w = min(pos)
        start, end = max(0, first - 40), min(len(body), first + len(w) + 40)
    else:
        start, end = 0, min(len(body), 80)
    part = body[start:end]
    pat = re.compile("|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)), re.I)
    out, last = "", 0
    for m in pat.finditer(part):
        out += esc(part[last:m.start()]) + "<mark>" + esc(m.group()) + "</mark>"
        last = m.end()
    out += esc(part[last:])
    return ("…" if start > 0 else "") + out + ("…" if end < len(body) else "")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/docs")
def docs():
    return query(
        "SELECT doc, COUNT(*) AS count FROM pl_clauses WHERE effective_to='' GROUP BY doc ORDER BY MIN(rowid)"
    )


@app.get("/api/search")
def search(q: str = ""):
    words = q.lower().split()
    if not words:
        return err(400, "검색어를 입력하세요")
    rows = query("SELECT * FROM pl_clauses WHERE effective_to=''")
    hits = []
    for r in rows:
        t, b = r["title"].lower(), r["body"].lower()
        if all(w in t or w in b for w in words):
            hits.append((any(w in t for w in words), r))
    hits.sort(key=lambda h: h[1]["clause_id"])
    hits.sort(key=lambda h: h[1]["effective_from"], reverse=True)
    hits.sort(key=lambda h: not h[0])
    results = [
        {
            "clause_id": r["clause_id"],
            "doc": r["doc"],
            "article": r["article"],
            "title": r["title"],
            "effective_from": r["effective_from"],
            "snippet": snippet(r["body"], words),
            "has_history": has_history(r),
        }
        for _, r in hits
    ]
    return {"query": q.strip(), "count": len(results), "results": results}


def get_clause(cid):
    rows = query("SELECT * FROM pl_clauses WHERE clause_id=?", (cid,))
    return rows[0] if rows else None


@app.get("/api/clauses/{cid}")
def clause(cid: str):
    r = get_clause(cid)
    if not r:
        return err(404, "조항을 찾을 수 없습니다")
    r["has_history"] = has_history(r)
    return r


@app.get("/api/clauses/{cid}/history")
def history(cid: str):
    r = get_clause(cid)
    if not r:
        return err(404, "조항을 찾을 수 없습니다")
    return query(
        "SELECT clause_id, effective_from, effective_to, body FROM pl_clauses "
        "WHERE doc=? AND article=? AND effective_to<>'' AND clause_id<>? ORDER BY effective_from DESC",
        (r["doc"], r["article"], cid),
    )


@app.get("/api/meta")
def meta():
    return {"today": datetime.date.today().isoformat()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
