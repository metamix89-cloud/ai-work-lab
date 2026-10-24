import base64
import csv
import os
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "feed.db")
SEED = os.path.join(BASE, "seed")
PAGE = 20
MAX_PINNED = 3
HIDE_AT = 3

lock = threading.RLock()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def read_csv(name):
    with open(os.path.join(SEED, name), newline="", encoding="utf-8-sig") as f:
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
        CREATE TABLE fd_posts (
            post_id TEXT PRIMARY KEY, author_id TEXT, body TEXT, created_at TEXT,
            pinned INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0, seq INTEGER);
        CREATE TABLE fd_comments (
            comment_id TEXT PRIMARY KEY, post_id TEXT, author_id TEXT, body TEXT, created_at TEXT);
        CREATE TABLE fd_reports (post_id TEXT, reporter_id TEXT, UNIQUE(post_id, reporter_id));
        """
    )
    for u in read_csv("users.csv"):
        con.execute("INSERT INTO fd_users VALUES (?,?,?)", (u["user_id"], u["name"], u["role"]))
    for i, p in enumerate(read_csv("posts.csv")):
        con.execute(
            "INSERT INTO fd_posts (post_id,author_id,body,created_at,pinned,deleted,seq) VALUES (?,?,?,?,?,0,?)",
            (p["post_id"], p["author_id"], p["body"], p["created_at"], 1 if str(p["pinned"]).strip() == "1" else 0, i),
        )
    for c in read_csv("comments.csv"):
        con.execute(
            "INSERT INTO fd_comments VALUES (?,?,?,?,?)",
            (c["comment_id"], c["post_id"], c["author_id"], c["body"], c["created_at"]),
        )
    for r in read_csv("reports.csv"):
        con.execute("INSERT OR IGNORE INTO fd_reports VALUES (?,?)", (r["post_id"], r["reporter_id"]))
    con.commit()
    return con


db = init_db()
app = FastAPI()


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


# ---------- helpers ----------

async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def need_user_id(value):
    if not isinstance(value, str) or not value.strip():
        raise Reject(400, "사용자를 확인하세요")
    return value


def clean_text(value):
    if not isinstance(value, str):
        raise Reject(400, "내용을 확인하세요")
    text = value.strip()
    if not 1 <= len(text) <= 500:
        raise Reject(400, "내용을 확인하세요")
    return text


def get_user(user_id):
    row = db.execute("SELECT * FROM fd_users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise Reject(404, "사용자를 찾을 수 없습니다")
    return row


def get_post(post_id):
    row = db.execute("SELECT * FROM fd_posts WHERE post_id=? AND deleted=0", (post_id,)).fetchone()
    if not row:
        raise Reject(404, "글을 찾을 수 없습니다")
    return row


def report_count(post_id):
    return db.execute("SELECT COUNT(DISTINCT reporter_id) FROM fd_reports WHERE post_id=?", (post_id,)).fetchone()[0]


POST_SQL = """
SELECT p.post_id, p.author_id, u.name AS author_name, p.body, p.created_at, p.pinned,
  (SELECT COUNT(*) FROM fd_comments c WHERE c.post_id=p.post_id) AS comment_count,
  (SELECT COUNT(DISTINCT r.reporter_id) FROM fd_reports r WHERE r.post_id=p.post_id) AS reports
FROM fd_posts p LEFT JOIN fd_users u ON u.user_id=p.author_id
"""


def shape(row):
    return {
        "post_id": row["post_id"],
        "author_id": row["author_id"],
        "author_name": row["author_name"],
        "body": row["body"],
        "created_at": row["created_at"],
        "pinned": bool(row["pinned"]),
        "comment_count": row["comment_count"],
        "hidden": row["reports"] >= HIDE_AT,
    }


def one_post(post_id):
    return shape(db.execute(POST_SQL + " WHERE p.post_id=?", (post_id,)).fetchone())


def visible_filter(viewer):
    """SQL fragment + params: hidden posts are only for the author and admins."""
    if viewer["role"] == "admin":
        return "", []
    return (
        " AND (p.author_id=? OR (SELECT COUNT(DISTINCT r.reporter_id) FROM fd_reports r WHERE r.post_id=p.post_id) < ?)",
        [viewer["user_id"], HIDE_AT],
    )


# newest first; ties broken by larger post_id (number-aware so P1000 > P999)
ORDER = " ORDER BY p.created_at DESC, LENGTH(p.post_id) DESC, p.post_id DESC"


def encode_cursor(row):
    return base64.urlsafe_b64encode(f"{row['created_at']}\t{row['post_id']}".encode()).decode()


def decode_cursor(text):
    try:
        created_at, post_id = base64.urlsafe_b64decode(text.encode()).decode().split("\t")
        return created_at, post_id
    except Exception:
        raise Reject(400, "내용을 확인하세요")


def next_id(table, col, prefix):
    best = 0
    for (v,) in db.execute(f"SELECT {col} FROM {table}"):
        digits = "".join(ch for ch in v if ch.isdigit())
        if digits:
            best = max(best, int(digits))
    return f"{prefix}{best + 1:03d}"


def now_for_post():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    latest = db.execute("SELECT MAX(created_at) FROM fd_posts").fetchone()[0]
    return max(now, latest) if latest else now


# ---------- routes ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id,name,role FROM fd_users ORDER BY rowid")]


@app.get("/api/posts")
def list_posts(request: Request):
    viewer_id = need_user_id(request.query_params.get("viewer"))
    before = request.query_params.get("before")
    with lock:
        viewer = get_user(viewer_id)
        vis, vparams = visible_filter(viewer)
        pinned = []
        if before is None:
            rows = db.execute(POST_SQL + " WHERE p.deleted=0 AND p.pinned=1" + vis + ORDER, vparams).fetchall()
            pinned = [shape(r) for r in rows]
        sql = POST_SQL + " WHERE p.deleted=0 AND p.pinned=0" + vis
        params = list(vparams)
        if before is not None:
            created_at, post_id = decode_cursor(before)
            sql += (
                " AND (p.created_at < ? OR (p.created_at = ? AND (LENGTH(p.post_id) < ?"
                " OR (LENGTH(p.post_id) = ? AND p.post_id < ?))))"
            )
            params += [created_at, created_at, len(post_id), len(post_id), post_id]
        rows = db.execute(sql + ORDER + " LIMIT ?", params + [PAGE + 1]).fetchall()
        page = rows[:PAGE]
        cursor = encode_cursor(page[-1]) if len(rows) > PAGE else None
        return {"pinned": pinned, "posts": [shape(r) for r in page], "next_cursor": cursor}


@app.post("/api/posts", status_code=201)
async def create_post(request: Request):
    data = await body_of(request)
    user_id = need_user_id(data.get("user"))
    text = clean_text(data.get("body"))
    with lock:
        user = get_user(user_id)
        post_id = next_id("fd_posts", "post_id", "P")
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM fd_posts").fetchone()[0]
        db.execute(
            "INSERT INTO fd_posts (post_id,author_id,body,created_at,pinned,deleted,seq) VALUES (?,?,?,?,0,0,?)",
            (post_id, user["user_id"], text, now_for_post(), seq),
        )
        db.commit()
        return JSONResponse(one_post(post_id), status_code=201)


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: str, request: Request):
    data = await body_of(request)
    user_id = need_user_id(data.get("user"))
    with lock:
        post = get_post(post_id)
        user = get_user(user_id)
        if user["role"] != "admin" and post["author_id"] != user["user_id"]:
            raise Reject(403, "본인 글만 지울 수 있습니다")
        db.execute("UPDATE fd_posts SET deleted=1, pinned=0 WHERE post_id=?", (post_id,))
        db.commit()
        return {"deleted": post_id}


@app.post("/api/posts/{post_id}/pin")
async def pin_post(post_id: str, request: Request):
    data = await body_of(request)
    user_id = need_user_id(data.get("user"))
    pinned = data.get("pinned")
    if not isinstance(pinned, bool):
        raise Reject(400, "내용을 확인하세요")
    with lock:
        post = get_post(post_id)
        user = get_user(user_id)
        if user["role"] != "admin":
            raise Reject(403, "운영자만 할 수 있습니다")
        if pinned and not post["pinned"]:
            count = db.execute("SELECT COUNT(*) FROM fd_posts WHERE pinned=1 AND deleted=0").fetchone()[0]
            if count >= MAX_PINNED:
                raise Reject(409, "고정은 3개까지입니다")
        db.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (1 if pinned else 0, post_id))
        db.commit()
        return one_post(post_id)


@app.post("/api/posts/{post_id}/reports", status_code=201)
async def report_post(post_id: str, request: Request):
    data = await body_of(request)
    user_id = need_user_id(data.get("user"))
    with lock:
        post = get_post(post_id)
        user = get_user(user_id)
        if post["author_id"] == user["user_id"]:
            raise Reject(403, "자기 글은 신고할 수 없습니다")
        if db.execute(
            "SELECT 1 FROM fd_reports WHERE post_id=? AND reporter_id=?", (post_id, user["user_id"])
        ).fetchone():
            raise Reject(409, "이미 신고했습니다")
        db.execute("INSERT INTO fd_reports VALUES (?,?)", (post_id, user["user_id"]))
        db.commit()
        count = report_count(post_id)
        return JSONResponse({"reports": count, "hidden": count >= HIDE_AT}, status_code=201)


@app.post("/api/posts/{post_id}/comments", status_code=201)
async def add_comment(post_id: str, request: Request):
    data = await body_of(request)
    user_id = need_user_id(data.get("user"))
    text = clean_text(data.get("body"))
    with lock:
        get_post(post_id)
        user = get_user(user_id)
        comment_id = next_id("fd_comments", "comment_id", "C")
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.execute(
            "INSERT INTO fd_comments VALUES (?,?,?,?,?)",
            (comment_id, post_id, user["user_id"], text, created_at),
        )
        db.commit()
        return JSONResponse(
            {
                "comment_id": comment_id,
                "post_id": post_id,
                "author_id": user["user_id"],
                "author_name": user["name"],
                "body": text,
                "created_at": created_at,
            },
            status_code=201,
        )
