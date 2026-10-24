import sqlite3
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from seed_data import ARTICLES

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
                article_no TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                keywords TEXT NOT NULL DEFAULT ''
            )"""
        )
        if conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO articles (category, article_no, title, body, keywords) VALUES (?,?,?,?,?)",
                ARTICLES,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="다온소프트 사내 규정 검색", lifespan=lifespan)


def like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get("/api/categories")
def categories():
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM articles GROUP BY category ORDER BY MIN(id)"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/search")
def search(q: str = Query("", max_length=100), category: str = ""):
    """공백으로 나눈 모든 검색어가 포함된 조항을 반환. 제목 > 키워드 > 본문 순으로 가중치."""
    terms = q.split()[:8]
    where, params, score = [], [], []
    for t in terms:
        p = f"%{like_escape(t)}%"
        where.append(
            "(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' "
            "OR keywords LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')"
        )
        params += [p, p, p, p]
        score.append(
            "(CASE WHEN title LIKE ? ESCAPE '\\' THEN 3 ELSE 0 END "
            "+ CASE WHEN keywords LIKE ? ESCAPE '\\' THEN 2 ELSE 0 END "
            "+ CASE WHEN body LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END)"
        )
    score_params = [f"%{like_escape(t)}%" for t in terms for _ in range(3)]
    if category:
        where.append("category = ?")
        params.append(category)

    sql = f"SELECT id, category, article_no, title, body FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = " + ".join(score) if score else "0"
    sql = sql.replace("SELECT id,", f"SELECT ({order}) AS score, id,", 1)
    sql += " ORDER BY score DESC, id"
    with closing(connect()) as conn:
        rows = conn.execute(sql, score_params + params).fetchall()
    return {"query": q, "count": len(rows), "results": [dict(r) for r in rows]}


@app.get("/api/articles/{article_id}")
def article(article_id: int):
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT id, category, article_no, title, body FROM articles WHERE id = ?",
            (article_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "조항을 찾을 수 없습니다.")
        siblings = conn.execute(
            "SELECT id, article_no, title FROM articles WHERE category = ? ORDER BY id",
            (row["category"],),
        ).fetchall()
    return {**dict(row), "siblings": [dict(s) for s in siblings]}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
