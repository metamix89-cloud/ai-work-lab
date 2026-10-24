# -*- coding: utf-8 -*-
import csv
import os
import re
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(ROOT, "seed")
DB_PATH = os.path.join(ROOT, "feed.db")
PAGE = 20
PIN_MAX = 3
HIDE_AT = 3

db = None
lock = threading.RLock()
counters = {"post": 0, "comment": 0}


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def read_csv(name):
    path = os.path.join(SEED, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(s):
    m = re.search(r"(\d+)\s*$", s or "")
    return int(m.group(1)) if m else 0


def init_db():
    global db
    if db is not None:
        db.close()
        db = None
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE fd_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE fd_posts (post_id TEXT PRIMARY KEY, author_id TEXT NOT NULL, body TEXT NOT NULL,
            created_at TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE fd_comments (comment_id TEXT PRIMARY KEY, post_id TEXT NOT NULL, author_id TEXT NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE fd_reports (post_id TEXT NOT NULL, reporter_id TEXT NOT NULL, PRIMARY KEY (post_id, reporter_id));
        CREATE INDEX fd_posts_order ON fd_posts (created_at, post_id);
    """)
    for r in read_csv("users.csv"):
        db.execute("INSERT OR REPLACE INTO fd_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("posts.csv"):
        db.execute("INSERT OR REPLACE INTO fd_posts VALUES (?,?,?,?,?,0)",
                   (r["post_id"], r["author_id"], r["body"], r["created_at"], 1 if str(r["pinned"]).strip() == "1" else 0))
    for r in read_csv("comments.csv"):
        db.execute("INSERT OR REPLACE INTO fd_comments VALUES (?,?,?,?,?)",
                   (r["comment_id"], r["post_id"], r["author_id"], r["body"], r["created_at"]))
    for r in read_csv("reports.csv"):
        db.execute("INSERT OR IGNORE INTO fd_reports VALUES (?,?)", (r["post_id"], r["reporter_id"]))
    db.commit()
    counters["post"] = max([num(r[0]) for r in db.execute("SELECT post_id FROM fd_posts")] or [0])
    counters["comment"] = max([num(r[0]) for r in db.execute("SELECT comment_id FROM fd_comments")] or [0])


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Reject)
async def on_reject(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


# ── 도우미 ──
async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def need_user(value):
    if not isinstance(value, str) or not value.strip():
        raise Reject(400, "사용자를 확인하세요")
    return value


def need_text(value):
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= 500):
        raise Reject(400, "내용을 확인하세요")
    return value.strip()


def get_user(user_id):
    u = db.execute("SELECT * FROM fd_users WHERE user_id=?", (user_id,)).fetchone()
    if not u:
        raise Reject(404, "없는 사용자입니다")
    return u


def get_post(post_id):
    p = db.execute("SELECT * FROM fd_posts WHERE post_id=? AND deleted=0", (post_id,)).fetchone()
    if not p:
        raise Reject(404, "없는 글입니다")
    return p


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def report_count(post_id):
    return db.execute("SELECT COUNT(DISTINCT reporter_id) FROM fd_reports WHERE post_id=?", (post_id,)).fetchone()[0]


def as_post(row):
    return {
        "post_id": row["post_id"],
        "author_id": row["author_id"],
        "author_name": row["author_name"] if "author_name" in row.keys() else (
            (db.execute("SELECT name FROM fd_users WHERE user_id=?", (row["author_id"],)).fetchone() or [""])[0]),
        "body": row["body"],
        "created_at": row["created_at"],
        "pinned": bool(row["pinned"]),
        "comment_count": db.execute("SELECT COUNT(*) FROM fd_comments WHERE post_id=?", (row["post_id"],)).fetchone()[0],
        "hidden": report_count(row["post_id"]) >= HIDE_AT,
    }


def visible(p, viewer):
    return not p["hidden"] or viewer["role"] == "admin" or p["author_id"] == viewer["user_id"]


# ── API ──
@app.get("/api/users")
def users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id, name, role FROM fd_users ORDER BY rowid")]


@app.get("/api/posts")
def list_posts(viewer: str = None, before: str = None):
    with lock:
        viewer = need_user(viewer)
        v = get_user(viewer)
        rows = db.execute(
            "SELECT p.*, u.name AS author_name FROM fd_posts p LEFT JOIN fd_users u ON u.user_id=p.author_id "
            "WHERE p.deleted=0 AND p.pinned=? ORDER BY p.created_at DESC, p.post_id DESC", (0,)).fetchall()
        pinned = []
        if before is None:
            prow = db.execute(
                "SELECT p.*, u.name AS author_name FROM fd_posts p LEFT JOIN fd_users u ON u.user_id=p.author_id "
                "WHERE p.deleted=0 AND p.pinned=1 ORDER BY p.created_at DESC, p.post_id DESC").fetchall()
            pinned = [p for p in map(as_post, prow) if visible(p, v)]
        else:
            if "|" not in before:
                raise Reject(400, "내용을 확인하세요")
            c_at, c_id = before.split("|", 1)
            rows = [r for r in rows if (r["created_at"], r["post_id"]) < (c_at, c_id)]
        items = []
        for r in rows:
            p = as_post(r)
            if visible(p, v):
                items.append(p)
                if len(items) > PAGE:
                    break
        nxt = None
        if len(items) > PAGE:
            items = items[:PAGE]
            nxt = items[-1]["created_at"] + "|" + items[-1]["post_id"]
        return {"pinned": pinned, "posts": items, "next_cursor": nxt}


@app.post("/api/posts", status_code=201)
async def create_post(request: Request):
    data = await body_of(request)
    with lock:
        user = need_user(data.get("user"))
        text = need_text(data.get("body"))
        get_user(user)
        counters["post"] += 1
        pid = "P%03d" % counters["post"]
        db.execute("INSERT INTO fd_posts VALUES (?,?,?,?,0,0)", (pid, user, text, now()))
        db.commit()
        return as_post(db.execute("SELECT * FROM fd_posts WHERE post_id=?", (pid,)).fetchone())


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        user = need_user(data.get("user"))
        post = get_post(post_id)
        u = get_user(user)
        if u["role"] != "admin" and post["author_id"] != user:
            raise Reject(403, "본인 글만 지울 수 있습니다")
        db.execute("UPDATE fd_posts SET deleted=1, pinned=0 WHERE post_id=?", (post_id,))
        db.commit()
        return {"deleted": post_id}


@app.post("/api/posts/{post_id}/pin")
async def pin_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        user = need_user(data.get("user"))
        want = data.get("pinned")
        if not isinstance(want, bool):
            raise Reject(400, "내용을 확인하세요")
        post = get_post(post_id)
        u = get_user(user)
        if u["role"] != "admin":
            raise Reject(403, "운영자만 할 수 있습니다")
        if want and not post["pinned"]:
            n = db.execute("SELECT COUNT(*) FROM fd_posts WHERE pinned=1 AND deleted=0").fetchone()[0]
            if n >= PIN_MAX:
                raise Reject(409, "고정은 3개까지입니다")
        db.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (1 if want else 0, post_id))
        db.commit()
        return as_post(db.execute("SELECT * FROM fd_posts WHERE post_id=?", (post_id,)).fetchone())


@app.post("/api/posts/{post_id}/reports", status_code=201)
async def report_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        user = need_user(data.get("user"))
        post = get_post(post_id)
        get_user(user)
        if post["author_id"] == user:
            raise Reject(403, "자기 글은 신고할 수 없습니다")
        if db.execute("SELECT 1 FROM fd_reports WHERE post_id=? AND reporter_id=?", (post_id, user)).fetchone():
            raise Reject(409, "이미 신고했습니다")
        db.execute("INSERT INTO fd_reports VALUES (?,?)", (post_id, user))
        db.commit()
        n = report_count(post_id)
        return {"reports": n, "hidden": n >= HIDE_AT}


@app.post("/api/posts/{post_id}/comments", status_code=201)
async def comment_post(post_id: str, request: Request):
    data = await body_of(request)
    with lock:
        user = need_user(data.get("user"))
        text = need_text(data.get("body"))
        get_post(post_id)
        get_user(user)
        counters["comment"] += 1
        cid = "C%03d" % counters["comment"]
        at = now()
        db.execute("INSERT INTO fd_comments VALUES (?,?,?,?,?)", (cid, post_id, user, text, at))
        db.commit()
        return {"comment_id": cid, "post_id": post_id, "author_id": user, "body": text, "created_at": at}


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))
