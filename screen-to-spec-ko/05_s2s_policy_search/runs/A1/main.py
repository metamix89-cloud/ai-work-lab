import sqlite3
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from seed import REGULATIONS

BASE = Path(__file__).parent
DB_PATH = BASE / "regulations.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(connect()) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS regulation (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS article (
                id INTEGER PRIMARY KEY,
                regulation_id INTEGER NOT NULL REFERENCES regulation(id),
                no TEXT NOT NULL,
                heading TEXT NOT NULL,
                body TEXT NOT NULL,
                seq INTEGER NOT NULL
            );
            """
        )
        if conn.execute("SELECT COUNT(*) FROM regulation").fetchone()[0]:
            return
        for reg in REGULATIONS:
            cur = conn.execute(
                "INSERT INTO regulation (code, category, title) VALUES (?, ?, ?)",
                (reg["code"], reg["category"], reg["title"]),
            )
            conn.executemany(
                "INSERT INTO article (regulation_id, no, heading, body, seq) VALUES (?, ?, ?, ?, ?)",
                [(cur.lastrowid, no, h, b, i) for i, (no, h, b) in enumerate(reg["articles"])],
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="다온소프트 사내 규정 검색", lifespan=lifespan)

ARTICLE_SELECT = """
    SELECT a.id, a.no, a.heading, a.body, r.code, r.category, r.title AS regulation
    FROM article a JOIN regulation r ON r.id = a.regulation_id
"""


def like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get("/api/categories")
def categories():
    with closing(connect()) as conn:
        rows = conn.execute("SELECT code, category, title FROM regulation ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/search")
def search(q: str = Query("", max_length=100), category: str = ""):
    terms = q.split()
    where, params = [], []
    for t in terms:  # 모든 검색어가 조항번호·제목·본문 중 어딘가에 포함되어야 함
        like = f"%{like_escape(t)}%"
        where.append("(a.no LIKE ? ESCAPE '\\' OR a.heading LIKE ? ESCAPE '\\' OR a.body LIKE ? ESCAPE '\\')")
        params += [like, like, like]
    if category:
        where.append("r.category = ?")
        params.append(category)
    sql = ARTICLE_SELECT + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY r.id, a.seq"
    with closing(connect()) as conn:
        rows = [dict(r) for r in conn.execute(sql, params)]
    # 제목 일치 조항을 우선 정렬 (안정 정렬이라 나머지는 규정/조 순서 유지)
    rows.sort(key=lambda r: not any(t in r["heading"] for t in terms))
    return {"query": q, "count": len(rows), "results": rows}


@app.get("/api/regulations/{code}")
def regulation(code: str):
    with closing(connect()) as conn:
        reg = conn.execute("SELECT * FROM regulation WHERE code = ?", (code,)).fetchone()
        if not reg:
            raise HTTPException(404, "규정을 찾을 수 없습니다.")
        arts = conn.execute(
            "SELECT id, no, heading, body FROM article WHERE regulation_id = ? ORDER BY seq", (reg["id"],)
        ).fetchall()
    return {**dict(reg), "articles": [dict(a) for a in arts]}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
