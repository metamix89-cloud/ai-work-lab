import re
import sqlite3
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from seed import ARTICLES

BASE = Path(__file__).parent
DB_PATH = BASE / "regulations.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(connect()) as conn, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                regulation TEXT NOT NULL,
                article_no TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                keywords TEXT NOT NULL DEFAULT ''
            )"""
        )
        if conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO articles (category, regulation, article_no, title, body, keywords) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ARTICLES,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="다온소프트 사내 규정 검색", lifespan=lifespan)


def snippet(body: str, terms: list[str], width: int = 80) -> str:
    flat = " ".join(body.split())
    low = flat.lower()
    pos = min((p for p in (low.find(t.lower()) for t in terms) if p >= 0), default=0)
    start = max(0, pos - width // 3)
    text = flat[start : start + width * 2]
    return ("…" if start else "") + text + ("…" if start + width * 2 < len(flat) else "")


@app.get("/api/categories")
def categories():
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM articles GROUP BY category ORDER BY MIN(id)"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/search")
def search(q: str = "", category: str = "", limit: int = Query(50, ge=1, le=200)):
    terms = q.split()
    where, params = [], []
    if category:
        where.append("category = ?")
        params.append(category)
    # 모든 검색어가 조항 어딘가(제목/본문/키워드/규정명)에 있어야 함 (AND)
    for t in terms:
        esc = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append(
            "(title LIKE :p ESCAPE '\\' OR body LIKE :p ESCAPE '\\' "
            "OR keywords LIKE :p ESCAPE '\\' OR regulation LIKE :p ESCAPE '\\')".replace(
                ":p", "?"
            )
        )
        params.extend([f"%{esc}%"] * 4)
    sql = "SELECT * FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with closing(connect()) as conn:
        rows = conn.execute(sql + " ORDER BY id", params).fetchall()

    def score(r):
        s = 0
        for t in terms:
            tl = t.lower()
            s += 5 * (tl in r["title"].lower()) + 3 * (tl in r["keywords"].lower())
            s += min(r["body"].lower().count(tl), 3)
        return s

    rows = sorted(rows, key=lambda r: -score(r)) if terms else rows
    return {
        "query": q,
        "count": len(rows),
        "results": [
            {
                "id": r["id"],
                "category": r["category"],
                "regulation": r["regulation"],
                "article_no": r["article_no"],
                "title": r["title"],
                "snippet": snippet(r["body"], terms),
            }
            for r in rows[:limit]
        ],
    }


@app.get("/api/articles/{article_id}")
def article(article_id: int):
    with closing(connect()) as conn:
        r = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not r:
            raise HTTPException(404, "조항을 찾을 수 없습니다.")
        # 같은 규정의 전체 조항 목차 (앞뒤 이동용)
        toc = conn.execute(
            "SELECT id, article_no, title FROM articles WHERE regulation = ? ORDER BY id",
            (r["regulation"],),
        ).fetchall()
    return {**dict(r), "toc": [dict(t) for t in toc]}


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
