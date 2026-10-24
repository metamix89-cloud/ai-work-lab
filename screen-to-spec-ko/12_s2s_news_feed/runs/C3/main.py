import csv
import os
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "feed.db")
PAGE = 20
PIN_MAX = 3
HIDE_AT = 3

app = FastAPI()
lock = threading.RLock()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


def read_csv(name):
    with open(os.path.join(ROOT, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        DROP TABLE IF EXISTS fd_users; DROP TABLE IF EXISTS fd_posts;
        DROP TABLE IF EXISTS fd_comments; DROP TABLE IF EXISTS fd_reports;
        CREATE TABLE fd_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE fd_posts (post_id TEXT PRIMARY KEY, author_id TEXT, body TEXT, created_at TEXT, pinned INTEGER);
        CREATE TABLE fd_comments (comment_id TEXT PRIMARY KEY, post_id TEXT, author_id TEXT, body TEXT, created_at TEXT);
        CREATE TABLE fd_reports (post_id TEXT, reporter_id TEXT, PRIMARY KEY (post_id, reporter_id));
        CREATE INDEX fd_posts_order ON fd_posts (created_at, post_id);
    """)
    conn.executemany("INSERT OR REPLACE INTO fd_users VALUES (?,?,?)",
                     [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    conn.executemany("INSERT OR REPLACE INTO fd_posts VALUES (?,?,?,?,?)",
                     [(r["post_id"], r["author_id"], r["body"], r["created_at"], 1 if r["pinned"].strip() == "1" else 0)
                      for r in read_csv("posts.csv")])
    conn.executemany("INSERT OR REPLACE INTO fd_comments VALUES (?,?,?,?,?)",
                     [(r["comment_id"], r["post_id"], r["author_id"], r["body"], r["created_at"])
                      for r in read_csv("comments.csv")])
    conn.executemany("INSERT OR IGNORE INTO fd_reports VALUES (?,?)",
                     [(r["post_id"], r["reporter_id"]) for r in read_csv("reports.csv")])
    conn.commit()
    return conn


db = init_db()


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def need_user_id(value):
    if not isinstance(value, str) or not value:
        raise Reject(400, "사용자를 확인하세요")
    return value


def check_text(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
        raise Reject(400, "내용을 확인하세요")
    return value.strip()


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


def next_id(table, col, prefix):
    mx = 0
    for (v,) in db.execute("SELECT %s FROM %s" % (col, table)):
        digits = v[len(prefix):] if v.startswith(prefix) else ""
        if digits.isdigit():
            mx = max(mx, int(digits))
    return "%s%03d" % (prefix, mx + 1)


def now_text(table="fd_posts"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    latest = db.execute("SELECT MAX(created_at) FROM %s" % table).fetchone()[0]
    return max(now, latest) if latest else now


POST_SQL = """
SELECT p.post_id, p.author_id, COALESCE(u.name, p.author_id) AS author_name, p.body, p.created_at, p.pinned,
       (SELECT COUNT(*) FROM fd_comments c WHERE c.post_id = p.post_id) AS comment_count,
       (SELECT COUNT(*) FROM fd_reports r WHERE r.post_id = p.post_id) AS rc
FROM fd_posts p LEFT JOIN fd_users u ON u.user_id = p.author_id
"""


def shape(row):
    return {"post_id": row["post_id"], "author_id": row["author_id"], "author_name": row["author_name"],
            "body": row["body"], "created_at": row["created_at"], "pinned": bool(row["pinned"]),
            "comment_count": row["comment_count"], "hidden": row["rc"] >= HIDE_AT}


def fetch_post(post_id):
    return shape(db.execute(POST_SQL + " WHERE p.post_id=?", (post_id,)).fetchone())


@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id, name, role FROM fd_users ORDER BY rowid")]


@app.get("/api/posts")
def posts(viewer=None, before=None):
    with lock:
        viewer = need_user_id(viewer)
        v = get_user(viewer)
        see_all = v["role"] == "admin"
        vis = "(rc < %d OR p.author_id = ? OR ? = 1)" % HIDE_AT
        vis_args = [viewer, 1 if see_all else 0]
        wrap = "SELECT * FROM (" + POST_SQL + ") p WHERE "
        pinned = []
        if before is None:
            rows = db.execute(wrap.replace("p.", "p.") + "p.pinned=1 AND " + vis + " ORDER BY created_at DESC, post_id DESC", vis_args)
            pinned = [shape(r) for r in rows]
        cond, args = "p.pinned=0 AND " + vis, list(vis_args)
        if before is not None:
            parts = before.split("|", 1) if isinstance(before, str) else []
            if len(parts) != 2:
                raise Reject(400, "내용을 확인하세요")
            cond += " AND (p.created_at < ? OR (p.created_at = ? AND p.post_id < ?))"
            args += [parts[0], parts[0], parts[1]]
        rows = db.execute(wrap + cond + " ORDER BY p.created_at DESC, p.post_id DESC LIMIT ?", args + [PAGE + 1]).fetchall()
        more = len(rows) > PAGE
        rows = rows[:PAGE]
        cursor = "%s|%s" % (rows[-1]["created_at"], rows[-1]["post_id"]) if more else None
        return {"pinned": pinned, "posts": [shape(r) for r in rows], "next_cursor": cursor}


@app.post("/api/posts", status_code=201)
async def create_post(request: Request):
    data = await body_of(request)
    user = need_user_id(data.get("user"))
    text = check_text(data.get("body"))
    with lock:
        get_user(user)
        pid = next_id("fd_posts", "post_id", "P")
        db.execute("INSERT INTO fd_posts VALUES (?,?,?,?,0)", (pid, user, text, now_text(), ))
        db.commit()
        return fetch_post(pid)


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: str, request: Request):
    data = await body_of(request)
    user = need_user_id(data.get("user"))
    with lock:
        post = get_post(post_id)
        u = get_user(user)
        if post["author_id"] != user and u["role"] != "admin":
            raise Reject(403, "본인 글만 지울 수 있습니다")
        db.execute("DELETE FROM fd_posts WHERE post_id=?", (post_id,))
        db.execute("DELETE FROM fd_comments WHERE post_id=?", (post_id,))
        db.execute("DELETE FROM fd_reports WHERE post_id=?", (post_id,))
        db.commit()
        return {"deleted": post_id}


@app.post("/api/posts/{post_id}/pin")
async def pin_post(post_id: str, request: Request):
    data = await body_of(request)
    user = need_user_id(data.get("user"))
    flag = data.get("pinned")
    if not isinstance(flag, bool):
        raise Reject(400, "내용을 확인하세요")
    with lock:
        post = get_post(post_id)
        u = get_user(user)
        if u["role"] != "admin":
            raise Reject(403, "운영자만 할 수 있습니다")
        if flag and not post["pinned"]:
            if db.execute("SELECT COUNT(*) FROM fd_posts WHERE pinned=1").fetchone()[0] >= PIN_MAX:
                raise Reject(409, "고정은 3개까지입니다")
        db.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (1 if flag else 0, post_id))
        db.commit()
        return fetch_post(post_id)


@app.post("/api/posts/{post_id}/reports", status_code=201)
async def report_post(post_id: str, request: Request):
    data = await body_of(request)
    user = need_user_id(data.get("user"))
    with lock:
        post = get_post(post_id)
        get_user(user)
        if post["author_id"] == user:
            raise Reject(403, "자기 글은 신고할 수 없습니다")
        if db.execute("SELECT 1 FROM fd_reports WHERE post_id=? AND reporter_id=?", (post_id, user)).fetchone():
            raise Reject(409, "이미 신고했습니다")
        db.execute("INSERT INTO fd_reports VALUES (?,?)", (post_id, user))
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM fd_reports WHERE post_id=?", (post_id,)).fetchone()[0]
        return {"reports": n, "hidden": n >= HIDE_AT}


@app.post("/api/posts/{post_id}/comments", status_code=201)
async def add_comment(post_id: str, request: Request):
    data = await body_of(request)
    user = need_user_id(data.get("user"))
    text = check_text(data.get("body"))
    with lock:
        get_post(post_id)
        get_user(user)
        cid = next_id("fd_comments", "comment_id", "C")
        created = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.execute("INSERT INTO fd_comments VALUES (?,?,?,?,?)", (cid, post_id, user, text, created))
        db.commit()
        return {"comment_id": cid, "post_id": post_id, "author_id": user, "body": text, "created_at": created}


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"), media_type="text/html; charset=utf-8")
