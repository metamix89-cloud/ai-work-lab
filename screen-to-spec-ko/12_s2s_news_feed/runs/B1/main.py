import csv
import os
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "feed.db")
PAGE = 20
HIDE_AT = 3
PIN_MAX = 3

app = FastAPI()
lock = threading.RLock()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE fd_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE fd_posts (post_id TEXT PRIMARY KEY, author_id TEXT, body TEXT,
            created_at TEXT, pinned INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0);
        CREATE TABLE fd_comments (comment_id TEXT PRIMARY KEY, post_id TEXT, author_id TEXT,
            body TEXT, created_at TEXT);
        CREATE TABLE fd_reports (post_id TEXT, reporter_id TEXT, PRIMARY KEY (post_id, reporter_id));
        CREATE INDEX fd_posts_order ON fd_posts (created_at, post_id);
        """
    )
    con.executemany("INSERT INTO fd_users VALUES (?,?,?)",
                    [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    con.executemany("INSERT INTO fd_posts VALUES (?,?,?,?,?,0)",
                    [(r["post_id"], r["author_id"], r["body"], r["created_at"],
                      1 if str(r["pinned"]).strip() == "1" else 0) for r in read_csv("posts.csv")])
    con.executemany("INSERT INTO fd_comments VALUES (?,?,?,?,?)",
                    [(r["comment_id"], r["post_id"], r["author_id"], r["body"], r["created_at"])
                     for r in read_csv("comments.csv")])
    con.executemany("INSERT OR IGNORE INTO fd_reports VALUES (?,?)",
                    [(r["post_id"], r["reporter_id"]) for r in read_csv("reports.csv")])
    con.commit()
    return con


db = init_db()


# ---------- helpers ----------

async def read_body(request: Request):
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
    if not isinstance(value, str):
        raise Reject(400, "내용을 확인하세요")
    value = value.strip()
    if not 1 <= len(value) <= 500:
        raise Reject(400, "내용을 확인하세요")
    return value


def get_user(user_id):
    row = db.execute("SELECT * FROM fd_users WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return row


def get_post(post_id):
    row = db.execute("SELECT * FROM fd_posts WHERE post_id=? AND deleted=0", (post_id,)).fetchone()
    if row is None:
        raise Reject(404, "글을 찾을 수 없습니다")
    return row


def report_count(post_id):
    return db.execute("SELECT COUNT(*) FROM fd_reports WHERE post_id=?", (post_id,)).fetchone()[0]


def post_json(row):
    author = db.execute("SELECT name FROM fd_users WHERE user_id=?", (row["author_id"],)).fetchone()
    comments = db.execute("SELECT COUNT(*) FROM fd_comments WHERE post_id=?", (row["post_id"],)).fetchone()[0]
    return {
        "post_id": row["post_id"],
        "author_id": row["author_id"],
        "author_name": author["name"] if author else row["author_id"],
        "body": row["body"],
        "created_at": row["created_at"],
        "pinned": bool(row["pinned"]),
        "comment_count": comments,
        "hidden": report_count(row["post_id"]) >= HIDE_AT,
    }


def next_id(table, col, prefix):
    top = 0
    for (v,) in db.execute(f"SELECT {col} FROM {table}"):
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        if digits:
            top = max(top, int(digits))
    return f"{prefix}{top + 1:03d}"


def now_text(floor_sql):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    latest = db.execute(floor_sql).fetchone()[0]
    return max(now, latest) if latest else now


def visible_sql(viewer):
    """WHERE fragment: not deleted, and not hidden unless viewer is author or admin."""
    if viewer["role"] == "admin":
        return "deleted=0", []
    clause = ("deleted=0 AND (post_id NOT IN (SELECT post_id FROM fd_reports GROUP BY post_id "
              f"HAVING COUNT(*) >= {HIDE_AT}) OR author_id=?)")
    return clause, [viewer["user_id"]]


# ---------- API ----------

@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id, name, role FROM fd_users ORDER BY rowid")]


@app.get("/api/posts")
def list_posts(viewer: str = None, before: str = None):
    with lock:
        viewer_id = need_user_id(viewer)
        v = get_user(viewer_id)
        where, args = visible_sql(v)
        pinned = []
        if before is None:
            rows = db.execute(f"SELECT * FROM fd_posts WHERE {where} AND pinned=1 "
                              "ORDER BY created_at DESC, post_id DESC", args).fetchall()
            pinned = [post_json(r) for r in rows]
        cond, cargs = "", []
        if before is not None:
            ts, _, pid = before.partition("|")
            cond = " AND (created_at < ? OR (created_at = ? AND post_id < ?))"
            cargs = [ts, ts, pid]
        rows = db.execute(f"SELECT * FROM fd_posts WHERE {where} AND pinned=0{cond} "
                          "ORDER BY created_at DESC, post_id DESC LIMIT ?",
                          args + cargs + [PAGE + 1]).fetchall()
        more = len(rows) > PAGE
        rows = rows[:PAGE]
        cursor = f"{rows[-1]['created_at']}|{rows[-1]['post_id']}" if more else None
        return {"pinned": pinned, "posts": [post_json(r) for r in rows], "next_cursor": cursor}


@app.post("/api/posts", status_code=201)
async def create_post(request: Request):
    data = await read_body(request)
    with lock:
        user_id = need_user_id(data.get("user"))
        body = check_text(data.get("body"))
        get_user(user_id)
        pid = next_id("fd_posts", "post_id", "P")
        ts = now_text("SELECT MAX(created_at) FROM fd_posts")
        db.execute("INSERT INTO fd_posts VALUES (?,?,?,?,0,0)", (pid, user_id, body, ts))
        db.commit()
        return post_json(get_post(pid))


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: str, request: Request):
    data = await read_body(request)
    with lock:
        user_id = need_user_id(data.get("user"))
        post = get_post(post_id)
        user = get_user(user_id)
        if post["author_id"] != user_id and user["role"] != "admin":
            raise Reject(403, "본인 글만 지울 수 있습니다")
        db.execute("UPDATE fd_posts SET deleted=1, pinned=0 WHERE post_id=?", (post_id,))
        db.commit()
        return {"deleted": post_id}


@app.post("/api/posts/{post_id}/pin")
async def pin_post(post_id: str, request: Request):
    data = await read_body(request)
    with lock:
        user_id = need_user_id(data.get("user"))
        flag = data.get("pinned")
        if not isinstance(flag, bool):
            raise Reject(400, "내용을 확인하세요")
        post = get_post(post_id)
        user = get_user(user_id)
        if user["role"] != "admin":
            raise Reject(403, "운영자만 할 수 있습니다")
        if bool(post["pinned"]) != flag:
            if flag:
                n = db.execute("SELECT COUNT(*) FROM fd_posts WHERE pinned=1 AND deleted=0").fetchone()[0]
                if n >= PIN_MAX:
                    raise Reject(409, "고정은 3개까지입니다")
            db.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (1 if flag else 0, post_id))
            db.commit()
        return post_json(get_post(post_id))


@app.post("/api/posts/{post_id}/reports", status_code=201)
async def report_post(post_id: str, request: Request):
    data = await read_body(request)
    with lock:
        user_id = need_user_id(data.get("user"))
        post = get_post(post_id)
        get_user(user_id)
        if post["author_id"] == user_id:
            raise Reject(403, "자기 글은 신고할 수 없습니다")
        if db.execute("SELECT 1 FROM fd_reports WHERE post_id=? AND reporter_id=?",
                      (post_id, user_id)).fetchone():
            raise Reject(409, "이미 신고했습니다")
        db.execute("INSERT INTO fd_reports VALUES (?,?)", (post_id, user_id))
        db.commit()
        n = report_count(post_id)
        return {"reports": n, "hidden": n >= HIDE_AT}


@app.post("/api/posts/{post_id}/comments", status_code=201)
async def add_comment(post_id: str, request: Request):
    data = await read_body(request)
    with lock:
        user_id = need_user_id(data.get("user"))
        body = check_text(data.get("body"))
        get_post(post_id)
        user = get_user(user_id)
        cid = next_id("fd_comments", "comment_id", "C")
        ts = now_text("SELECT MAX(created_at) FROM fd_comments")
        db.execute("INSERT INTO fd_comments VALUES (?,?,?,?,?)", (cid, post_id, user_id, body, ts))
        db.commit()
        return {"comment_id": cid, "post_id": post_id, "author_id": user_id,
                "author_name": user["name"], "body": body, "created_at": ts}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")
