import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from seed import CATEGORIES, NOTICES

BASE = Path(__file__).parent
DB = BASE / "notices.db"

app = FastAPI(title="푸른구청 고시·공고")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with closing(conn()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, kind TEXT NOT NULL, number TEXT NOT NULL,
            title TEXT NOT NULL, posted TEXT NOT NULL, deadline TEXT,
            dept TEXT NOT NULL, phone TEXT NOT NULL,
            summary TEXT NOT NULL, body TEXT NOT NULL)""")
        if c.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0:
            c.executemany(
                "INSERT INTO notices (category,kind,number,title,posted,deadline,dept,phone,summary,body)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", NOTICES)
        c.commit()


init_db()


@app.get("/api/categories")
def categories():
    with closing(conn()) as c:
        counts = dict(c.execute("SELECT category, COUNT(*) FROM notices GROUP BY category").fetchall())
    return [{"name": n, "count": counts.get(n, 0)} for n in CATEGORIES]


@app.get("/api/notices")
def list_notices(category: str | None = None, kind: str | None = None,
                 q: str | None = None, open_only: bool = False,
                 today: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    sql, args = "SELECT id,category,kind,number,title,posted,deadline,dept,summary FROM notices WHERE 1=1", []
    if category:
        sql += " AND category=?"; args.append(category)
    if kind:
        sql += " AND kind=?"; args.append(kind)
    if q:
        sql += " AND (title LIKE ? OR summary LIKE ? OR body LIKE ?)"
        args += [f"%{q}%"] * 3
    if open_only and today:
        sql += " AND deadline IS NOT NULL AND deadline>=?"; args.append(today)
    sql += " ORDER BY posted DESC, id DESC"
    with closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args)]


@app.get("/api/notices/{nid}")
def get_notice(nid: int):
    with closing(conn()) as c:
        r = c.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone()
    if not r:
        raise HTTPException(404, "게시물을 찾을 수 없습니다.")
    return dict(r)


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
