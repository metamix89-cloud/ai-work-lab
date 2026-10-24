import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .seed import CATEGORIES, NOTICES

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "notices.db"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT NOT NULL,
                category TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                body TEXT NOT NULL,
                department TEXT NOT NULL,
                published TEXT NOT NULL,
                effective TEXT,
                views INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_cat ON notices(category, published)")
        if conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0:
            counters, rows = {}, []
            for cat, kind, title, summary, body, dept, pub, eff in sorted(NOTICES, key=lambda n: n[6]):
                key = (kind, pub[:4])
                counters[key] = counters.get(key, 0) + 1
                number = f"푸른구 {kind} 제{pub[:4]}-{counters[key]}호"
                rows.append((number, cat, kind, title, summary, body, dept, pub, eff))
            conn.executemany(
                "INSERT INTO notices(number,category,kind,title,summary,body,department,published,effective)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="푸른구청 고시·공고 열람", lifespan=lifespan)

LIST_COLS = "id,number,category,kind,title,summary,department,published,effective,views"


@app.get("/api/categories")
def categories():
    conn = db()
    counts = {r["category"]: r["n"] for r in conn.execute("SELECT category, COUNT(*) n FROM notices GROUP BY category")}
    conn.close()
    return [{"name": n, "count": counts.get(n, 0)} for n in CATEGORIES]


@app.get("/api/notices")
def list_notices(
    category: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    sort: str = Query("latest", pattern="^(latest|views)$"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
):
    where, args = [], []
    if category:
        where.append("category = ?")
        args.append(category)
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(
            "(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR number LIKE ? ESCAPE '\\')"
        )
        args += [like] * 4
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    order = "published DESC, id DESC" if sort == "latest" else "views DESC, id DESC"
    conn = db()
    total = conn.execute(f"SELECT COUNT(*) FROM notices {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT {LIST_COLS} FROM notices {clause} ORDER BY {order} LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    conn.close()
    return {"total": total, "page": page, "size": size, "items": [dict(r) for r in rows]}


@app.get("/api/notices/{notice_id}")
def get_notice(notice_id: int):
    conn = db()
    with conn:
        conn.execute("UPDATE notices SET views = views + 1 WHERE id = ?", (notice_id,))
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "고시·공고를 찾을 수 없습니다.")
    return dict(row)


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
