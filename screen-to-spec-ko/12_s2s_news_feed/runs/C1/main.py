import csv
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(ROOT, "seed")
DB_PATH = os.path.join(ROOT, "feed.db")
PAGE = 20
MAX_PINNED = 3
HIDE_AT = 3

db = None


def read_csv(name):
    path = os.path.join(SEED, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global db
    if db is not None:
        db.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE fd_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE fd_posts (post_id TEXT PRIMARY KEY, author_id TEXT, body TEXT, created_at TEXT, pinned INTEGER);
        CREATE TABLE fd_comments (comment_id TEXT PRIMARY KEY, post_id TEXT, author_id TEXT, body TEXT, created_at TEXT);
        CREATE TABLE fd_reports (post_id TEXT, reporter_id TEXT, UNIQUE(post_id, reporter_id));
    """)
    db.executemany("INSERT OR REPLACE INTO fd_users VALUES (?,?,?)",
                   [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    db.executemany("INSERT OR REPLACE INTO fd_posts VALUES (?,?,?,?,?)",
                   [(r["post_id"], r["author_id"], r["body"], r["created_at"], 1 if str(r["pinned"]).strip() == "1" else 0)
                    for r in read_csv("posts.csv")])
    db.executemany("INSERT OR REPLACE INTO fd_comments VALUES (?,?,?,?,?)",
                   [(r["comment_id"], r["post_id"], r["author_id"], r["body"], r["created_at"]) for r in read_csv("comments.csv")])
    db.executemany("INSERT OR IGNORE INTO fd_reports VALUES (?,?)",
                   [(r["post_id"], r["reporter_id"]) for r in read_csv("reports.csv")])
    db.commit()


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(_, e):
    return JSONResponse({"detail": e.detail}, status_code=e.status)


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def check_user_field(value):
    if not isinstance(value, str) or not value.strip():
        raise Reject(400, "사용자를 확인하세요")


def check_text(value):
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= 500):
        raise Reject(400, "내용을 확인하세요")


def get_user(user_id):
    row = db.execute("SELECT * FROM fd_users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return row


def get_post(post_id):
    row = db.execute("SELECT * FROM fd_posts WHERE post_id=?", (post_id,)).fetchone()
    if not row:
        raise Reject(404, "글을 찾을 수 없습니다")
    return row


def report_count(post_id):
    return db.execute("SELECT COUNT(DISTINCT reporter_id) FROM fd_reports WHERE post_id=?", (post_id,)).fetchone()[0]


def as_post(row):
    name = db.execute("SELECT name FROM fd_users WHERE user_id=?", (row["author_id"],)).fetchone()
    count = db.execute("SELECT COUNT(*) FROM fd_comments WHERE post_id=?", (row["post_id"],)).fetchone()[0]
    return {
        "post_id": row["post_id"],
        "author_id": row["author_id"],
        "author_name": name["name"] if name else row["author_id"],
        "body": row["body"],
        "created_at": row["created_at"],
        "pinned": bool(row["pinned"]),
        "comment_count": count,
        "hidden": report_count(row["post_id"]) >= HIDE_AT,
    }


def visible_to(post, viewer):
    return not post["hidden"] or viewer["role"] == "admin" or post["author_id"] == viewer["user_id"]


def next_id(table, col, prefix):
    nums = [int(r[0][len(prefix):]) for r in db.execute("SELECT %s FROM %s" % (col, table))
            if r[0].startswith(prefix) and r[0][len(prefix):].isdigit()]
    return "%s%03d" % (prefix, max(nums, default=0) + 1)


def now_text():
    # 서버의 지금. 시드 글이 더 새로우면 그 뒤로 둔다(새 글이 항상 맨 앞).
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    latest = db.execute("SELECT MAX(created_at) FROM fd_posts").fetchone()[0]
    return max(now, latest) if latest else now


@app.get("/api/users")
async def users():
    return [dict(r) for r in db.execute("SELECT user_id, name, role FROM fd_users ORDER BY rowid")]


@app.get("/api/posts")
async def posts(viewer=None, before=None):
    check_user_field(viewer)
    v = get_user(viewer)
    pinned, regular = [], []
    if before is None:
        rows = db.execute("SELECT * FROM fd_posts WHERE pinned=1 ORDER BY created_at DESC, post_id DESC").fetchall()
        pinned = [p for p in map(as_post, rows) if visible_to(p, v)]
    sql, args = "SELECT * FROM fd_posts WHERE pinned=0", []
    if before is not None:
        created, sep, pid = before.partition("|")
        if not sep or not pid:
            raise Reject(400, "내용을 확인하세요")
        sql += " AND (created_at < ? OR (created_at = ? AND post_id < ?))"
        args += [created, created, pid]
    sql += " ORDER BY created_at DESC, post_id DESC"
    more = False
    for row in db.execute(sql, args):
        p = as_post(row)
        if not visible_to(p, v):
            continue
        if len(regular) == PAGE:
            more = True
            break
        regular.append(p)
    cursor = "%s|%s" % (regular[-1]["created_at"], regular[-1]["post_id"]) if more else None
    return {"pinned": pinned, "posts": regular, "next_cursor": cursor}


@app.post("/api/posts", status_code=201)
async def create_post(request: Request):
    data = await body_of(request)
    check_user_field(data.get("user"))
    check_text(data.get("body"))
    get_user(data["user"])
    post_id = next_id("fd_posts", "post_id", "P")
    db.execute("INSERT INTO fd_posts VALUES (?,?,?,?,0)", (post_id, data["user"], data["body"].strip(), now_text()))
    db.commit()
    return as_post(get_post(post_id))


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: str, request: Request):
    data = await body_of(request)
    check_user_field(data.get("user"))
    post = get_post(post_id)
    user = get_user(data["user"])
    if user["role"] != "admin" and post["author_id"] != user["user_id"]:
        raise Reject(403, "본인 글만 지울 수 있습니다")
    for table in ("fd_posts", "fd_comments", "fd_reports"):
        db.execute("DELETE FROM %s WHERE post_id=?" % table, (post_id,))
    db.commit()
    return {"deleted": post_id}


@app.post("/api/posts/{post_id}/pin")
async def pin_post(post_id: str, request: Request):
    data = await body_of(request)
    check_user_field(data.get("user"))
    if not isinstance(data.get("pinned"), bool):
        raise Reject(400, "내용을 확인하세요")
    post = get_post(post_id)
    user = get_user(data["user"])
    if user["role"] != "admin":
        raise Reject(403, "운영자만 할 수 있습니다")
    want = 1 if data["pinned"] else 0
    if post["pinned"] != want:
        if want and db.execute("SELECT COUNT(*) FROM fd_posts WHERE pinned=1").fetchone()[0] >= MAX_PINNED:
            raise Reject(409, "고정은 3개까지입니다")
        db.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (want, post_id))
        db.commit()
    return as_post(get_post(post_id))


@app.post("/api/posts/{post_id}/reports", status_code=201)
async def report_post(post_id: str, request: Request):
    data = await body_of(request)
    check_user_field(data.get("user"))
    post = get_post(post_id)
    user = get_user(data["user"])
    if post["author_id"] == user["user_id"]:
        raise Reject(403, "자기 글은 신고할 수 없습니다")
    if db.execute("SELECT 1 FROM fd_reports WHERE post_id=? AND reporter_id=?", (post_id, user["user_id"])).fetchone():
        raise Reject(409, "이미 신고했습니다")
    db.execute("INSERT INTO fd_reports VALUES (?,?)", (post_id, user["user_id"]))
    db.commit()
    n = report_count(post_id)
    return {"reports": n, "hidden": n >= HIDE_AT}


@app.post("/api/posts/{post_id}/comments", status_code=201)
async def comment_post(post_id: str, request: Request):
    data = await body_of(request)
    check_user_field(data.get("user"))
    check_text(data.get("body"))
    get_post(post_id)
    get_user(data["user"])
    comment_id = next_id("fd_comments", "comment_id", "C")
    created = datetime.now().strftime("%Y-%m-%d %H:%M")
    db.execute("INSERT INTO fd_comments VALUES (?,?,?,?,?)", (comment_id, post_id, data["user"], data["body"].strip(), created))
    db.commit()
    return {"comment_id": comment_id, "post_id": post_id, "author_id": data["user"],
            "body": data["body"].strip(), "created_at": created}


@app.get("/")
async def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
