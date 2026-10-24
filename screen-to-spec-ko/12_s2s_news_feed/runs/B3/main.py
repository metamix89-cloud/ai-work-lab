import csv
import os
import re
import sqlite3
import threading
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "feed.db")
PAGE = 20
PIN_MAX = 3
HIDE_AT = 3

app = FastAPI()
lock = threading.RLock()
db = None


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
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
    db.executescript(
        """
        CREATE TABLE fd_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE fd_posts (post_id TEXT PRIMARY KEY, author_id TEXT, body TEXT,
            created_at TEXT, pinned INTEGER, deleted INTEGER DEFAULT 0);
        CREATE TABLE fd_comments (comment_id TEXT PRIMARY KEY, post_id TEXT, author_id TEXT,
            body TEXT, created_at TEXT);
        CREATE TABLE fd_reports (post_id TEXT, reporter_id TEXT, PRIMARY KEY (post_id, reporter_id));
        """
    )
    for r in read_csv("users.csv"):
        db.execute("INSERT INTO fd_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("posts.csv"):
        db.execute(
            "INSERT INTO fd_posts VALUES (?,?,?,?,?,0)",
            (r["post_id"], r["author_id"], r["body"], r["created_at"], 1 if str(r["pinned"]).strip() == "1" else 0),
        )
    for r in read_csv("comments.csv"):
        db.execute(
            "INSERT INTO fd_comments VALUES (?,?,?,?,?)",
            (r["comment_id"], r["post_id"], r["author_id"], r["body"], r["created_at"]),
        )
    for r in read_csv("reports.csv"):
        db.execute("INSERT OR IGNORE INTO fd_reports VALUES (?,?)", (r["post_id"], r["reporter_id"]))
    db.commit()


init_db()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def need_user(value):
    if not isinstance(value, str) or not value:
        raise Reject(400, "사용자를 확인하세요")
    return value


def check_text(value):
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= 500):
        raise Reject(400, "내용을 확인하세요")
    return value.strip()


def get_user(uid):
    row = db.execute("SELECT * FROM fd_users WHERE user_id=?", (uid,)).fetchone()
    if row is None:
        raise Reject(404, "없는 사용자입니다")
    return row


def get_post(pid):
    row = db.execute("SELECT * FROM fd_posts WHERE post_id=? AND deleted=0", (pid,)).fetchone()
    if row is None:
        raise Reject(404, "없는 글입니다")
    return row


def id_num(value):
    m = re.search(r"(\d+)$", value or "")
    return int(m.group(1)) if m else 0


def next_id(table, col, prefix):
    nums = [id_num(r[0]) for r in db.execute(f"SELECT {col} FROM {table}")]
    return f"{prefix}{max(nums + [0]) + 1:03d}"


def now_text():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest = db.execute("SELECT MAX(created_at) FROM fd_posts").fetchone()[0]
    return max(now, latest) if latest else now


def sort_key(p):
    return (p["created_at"], id_num(p["post_id"]))


def report_count(pid):
    return db.execute("SELECT COUNT(*) FROM fd_reports WHERE post_id=?", (pid,)).fetchone()[0]


def render(row):
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


def visible_to(post, viewer):
    if not post["hidden"]:
        return True
    return viewer["role"] == "admin" or post["author_id"] == viewer["user_id"]


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id, name, role FROM fd_users ORDER BY rowid")]


@app.get("/api/posts")
def posts(viewer=None, before=None):
    with lock:
        need_user(viewer)
        v = get_user(viewer)
        rows = [render(r) for r in db.execute("SELECT * FROM fd_posts WHERE deleted=0")]
        rows = [p for p in rows if visible_to(p, v)]
        pinned = []
        if before is None:
            pinned = sorted((p for p in rows if p["pinned"]), key=sort_key, reverse=True)
        normal = sorted((p for p in rows if not p["pinned"]), key=sort_key, reverse=True)
        if before is not None:
            created, _, pid = before.rpartition("|")
            cur = (created, id_num(pid))
            normal = [p for p in normal if sort_key(p) < cur]
        page = normal[:PAGE]
        nxt = None
        if len(normal) > PAGE and page:
            last = page[-1]
            nxt = f"{last['created_at']}|{last['post_id']}"
        return {"pinned": pinned, "posts": page, "next_cursor": nxt}


@app.post("/api/posts", status_code=201)
async def create_post(request: Request):
    data = await body_of(request)
    with lock:
        uid = need_user(data.get("user"))
        text = check_text(data.get("body"))
        get_user(uid)
        pid = next_id("fd_posts", "post_id", "P")
        db.execute(
            "INSERT INTO fd_posts VALUES (?,?,?,?,0,0)", (pid, uid, text, now_text())
        )
        db.commit()
        return render(get_post(pid))


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        uid = need_user(data.get("user"))
        post = get_post(post_id)
        user = get_user(uid)
        if user["role"] != "admin" and post["author_id"] != uid:
            raise Reject(403, "본인 글만 지울 수 있습니다")
        db.execute("UPDATE fd_posts SET deleted=1 WHERE post_id=?", (post_id,))
        db.commit()
        return {"deleted": post_id}


@app.post("/api/posts/{post_id}/pin")
async def pin_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        uid = need_user(data.get("user"))
        want = data.get("pinned")
        if not isinstance(want, bool):
            raise Reject(400, "내용을 확인하세요")
        post = get_post(post_id)
        user = get_user(uid)
        if user["role"] != "admin":
            raise Reject(403, "운영자만 할 수 있습니다")
        if want != bool(post["pinned"]):
            if want:
                count = db.execute("SELECT COUNT(*) FROM fd_posts WHERE pinned=1 AND deleted=0").fetchone()[0]
                if count >= PIN_MAX:
                    raise Reject(409, "고정은 3개까지입니다")
            db.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (1 if want else 0, post_id))
            db.commit()
        return render(get_post(post_id))


@app.post("/api/posts/{post_id}/reports", status_code=201)
async def report_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        uid = need_user(data.get("user"))
        post = get_post(post_id)
        get_user(uid)
        if post["author_id"] == uid:
            raise Reject(403, "자기 글은 신고할 수 없습니다")
        dup = db.execute(
            "SELECT 1 FROM fd_reports WHERE post_id=? AND reporter_id=?", (post_id, uid)
        ).fetchone()
        if dup:
            raise Reject(409, "이미 신고했습니다")
        db.execute("INSERT INTO fd_reports VALUES (?,?)", (post_id, uid))
        db.commit()
        n = report_count(post_id)
        return {"reports": n, "hidden": n >= HIDE_AT}


@app.post("/api/posts/{post_id}/comments", status_code=201)
async def comment_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        uid = need_user(data.get("user"))
        text = check_text(data.get("body"))
        get_post(post_id)
        get_user(uid)
        cid = next_id("fd_comments", "comment_id", "C")
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO fd_comments VALUES (?,?,?,?,?)", (cid, post_id, uid, text, created))
        db.commit()
        return {"comment_id": cid, "post_id": post_id, "author_id": uid, "body": text, "created_at": created}
