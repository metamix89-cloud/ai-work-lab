# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R7 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import os
import re
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "policy.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""CREATE TABLE pl_clauses(clause_id TEXT PRIMARY KEY, doc TEXT, article TEXT, title TEXT, body TEXT,
                                                 effective_from TEXT, effective_to TEXT);""")
    p = os.path.join(SEED, "clauses.csv")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            rows = [r for r in csv.reader(f)][1:]
        con.executemany("INSERT INTO pl_clauses VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def has_history(c, row):
    return c.execute("SELECT 1 FROM pl_clauses WHERE doc=? AND article=? AND effective_to<>'' AND clause_id<>?",
                     (row["doc"], row["article"], row["clause_id"])).fetchone() is not None


def snippet(body, words):
    low = body.lower()
    pos = min([low.find(w) for w in words if low.find(w) >= 0] or [0])
    start = max(0, pos - 40)
    s = body[start:pos + 40]
    for w in words:
        s = re.sub(re.escape(w), lambda m: "<mark>%s</mark>" % m.group(0), s, flags=re.I)
    return ("…" if start else "") + s + ("…" if pos + 40 < len(body) else "")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/docs")
def docs():
    return [dict(r) for r in con().execute("SELECT doc, COUNT(*) AS count FROM pl_clauses WHERE effective_to='' GROUP BY doc")]


@app.get("/api/search")
def search(q: str = ""):
    words = [w.lower() for w in q.strip().split() if w.strip()]
    if not words:
        raise HTTPException(400, "검색어를 입력하세요")
    c = con()
    out = []
    for r in c.execute("SELECT * FROM pl_clauses WHERE effective_to=''"):
        text = (r["title"] + " " + r["body"]).lower()
        if all(w in text for w in words):
            title_hit = sum(1 for w in words if w in r["title"].lower())
            out.append((title_hit, r["effective_from"], r["clause_id"], r))
    # R5: 제목 매칭 많은 순 → 시행일 최신 순 → clause_id 순 (안정 정렬을 거꾸로 쌓는다)
    out.sort(key=lambda x: x[2])
    out.sort(key=lambda x: x[1], reverse=True)
    out.sort(key=lambda x: x[0], reverse=True)
    results = [{"clause_id": r["clause_id"], "doc": r["doc"], "article": r["article"], "title": r["title"],
                "effective_from": r["effective_from"], "snippet": snippet(r["body"], words), "has_history": has_history(c, r)}
               for _, _, _, r in out]
    return {"query": q.strip(), "count": len(results), "results": results}


@app.get("/api/clauses/{clause_id}")
def clause(clause_id: str):
    c = con()
    r = c.execute("SELECT * FROM pl_clauses WHERE clause_id=?", (clause_id,)).fetchone()
    if not r:
        raise HTTPException(404, "조항이 없습니다")
    d = dict(r)
    d["has_history"] = has_history(c, r)
    return d


@app.get("/api/clauses/{clause_id}/history")
def history(clause_id: str):
    c = con()
    r = c.execute("SELECT * FROM pl_clauses WHERE clause_id=?", (clause_id,)).fetchone()
    if not r:
        raise HTTPException(404, "조항이 없습니다")
    return [dict(x) for x in c.execute("""SELECT * FROM pl_clauses WHERE doc=? AND article=? AND effective_to<>'' AND clause_id<>?
                                           ORDER BY effective_from DESC""", (r["doc"], r["article"], clause_id))]
