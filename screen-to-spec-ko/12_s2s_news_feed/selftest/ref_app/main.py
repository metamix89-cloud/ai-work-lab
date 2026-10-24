# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R8 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
더 보기(R2): 커서 = 이 쪽 마지막 글의 'created_at|post_id'. 다음 쪽은 (created_at, post_id) 가 그보다 작은 글부터 —
그 글이 나중에 지워져도 이어 갈 수 있다."""
import csv
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "feed.db")
LOCK = threading.Lock()
PAGE = 20
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE fd_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE fd_posts(post_id TEXT PRIMARY KEY, author_id TEXT, body TEXT, created_at TEXT, pinned INTEGER, deleted INTEGER DEFAULT 0);
    CREATE TABLE fd_comments(comment_id TEXT PRIMARY KEY, post_id TEXT, author_id TEXT, body TEXT, created_at TEXT);
    CREATE TABLE fd_reports(post_id TEXT, reporter_id TEXT, PRIMARY KEY(post_id, reporter_id));""")
    for name, sql, n in (("users.csv", "INSERT INTO fd_users VALUES (?,?,?)", 3),
                         ("posts.csv", "INSERT INTO fd_posts(post_id, author_id, body, created_at, pinned) VALUES (?,?,?,?,?)", 5),
                         ("comments.csv", "INSERT INTO fd_comments VALUES (?,?,?,?,?)", 5),
                         ("reports.csv", "INSERT OR IGNORE INTO fd_reports VALUES (?,?)", 2)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                con.executemany(sql, [r[:n] for r in list(csv.reader(f))[1:] if r])
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def reports(c, pid):
    return c.execute("SELECT COUNT(*) FROM fd_reports WHERE post_id=?", (pid,)).fetchone()[0]


def view(c, p):
    return {"post_id": p["post_id"], "author_id": p["author_id"],
            "author_name": (c.execute("SELECT name FROM fd_users WHERE user_id=?", (p["author_id"],)).fetchone() or [""])[0],
            "body": p["body"], "created_at": p["created_at"], "pinned": bool(int(p["pinned"])),
            "comment_count": c.execute("SELECT COUNT(*) FROM fd_comments WHERE post_id=?", (p["post_id"],)).fetchone()[0],
            "hidden": reports(c, p["post_id"]) >= 3}


def visible(c, p, viewer):
    return reports(c, p["post_id"]) < 3 or viewer["role"] == "admin" or p["author_id"] == viewer["user_id"]


def need_user(uid):
    if not isinstance(uid, str) or not uid:
        raise HTTPException(400, "사용자를 확인하세요")


def find_user(c, uid):
    u = c.execute("SELECT * FROM fd_users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    return u


def find_post(c, pid):
    p = c.execute("SELECT * FROM fd_posts WHERE post_id=? AND deleted=0", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "글이 없습니다")
    return p


def body_ok(text):
    return isinstance(text, str) and 1 <= len(text.strip()) <= 500


def next_id(c, table, col, prefix):
    nums = [int(r[0][1:]) for r in c.execute("SELECT %s FROM %s" % (col, table)) if r[0][1:].isdigit()]
    return "%s%03d" % (prefix, max(nums + [0]) + 1)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM fd_users ORDER BY rowid")]


@app.get("/api/posts")
def posts(viewer: str = Query(default=""), before: str | None = None):
    need_user(viewer)
    c = con()
    v = find_user(c, viewer)
    rows = c.execute("SELECT * FROM fd_posts WHERE deleted=0 AND pinned=0 ORDER BY created_at DESC, post_id DESC").fetchall()
    if before:
        ca, _, pid = before.partition("|")
        rows = [p for p in rows if (p["created_at"], p["post_id"]) < (ca, pid)]
    rows = [p for p in rows if visible(c, p, v)]
    chunk = rows[:PAGE]
    cursor = "%s|%s" % (chunk[-1]["created_at"], chunk[-1]["post_id"]) if len(rows) > PAGE else None
    pinned = [] if before else [view(c, p) for p in c.execute(
        "SELECT * FROM fd_posts WHERE deleted=0 AND pinned=1 ORDER BY created_at DESC, post_id DESC") if visible(c, p, v)]
    return {"pinned": pinned, "posts": [view(c, p) for p in chunk], "next_cursor": cursor}


@app.post("/api/posts", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    if not body_ok(body.get("body")):
        raise HTTPException(400, "내용을 확인하세요")
    with LOCK:
        c = con()
        u = find_user(c, body["user"])
        pid = next_id(c, "fd_posts", "post_id", "P")
        c.execute("INSERT INTO fd_posts(post_id, author_id, body, created_at, pinned) VALUES (?,?,?,?,0)",
                  (pid, u["user_id"], body["body"].strip(), datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()
        return view(c, find_post(c, pid))


@app.delete("/api/posts/{pid}")
def delete(pid: str, body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    with LOCK:
        c = con()
        p = find_post(c, pid)
        u = find_user(c, body["user"])
        if u["role"] != "admin" and p["author_id"] != u["user_id"]:
            raise HTTPException(403, "본인 글만 지울 수 있습니다")
        c.execute("UPDATE fd_posts SET deleted=1, pinned=0 WHERE post_id=?", (pid,))
        c.commit()
        return {"deleted": pid}


@app.post("/api/posts/{pid}/pin")
def pin(pid: str, body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    want = body.get("pinned")
    if not isinstance(want, bool):
        raise HTTPException(400, "pinned 를 확인하세요")
    with LOCK:
        c = con()
        p = find_post(c, pid)
        u = find_user(c, body["user"])
        if u["role"] != "admin":
            raise HTTPException(403, "운영자만 할 수 있습니다")
        if want and not p["pinned"] and c.execute("SELECT COUNT(*) FROM fd_posts WHERE deleted=0 AND pinned=1").fetchone()[0] >= 3:
            raise HTTPException(409, "고정은 3개까지입니다")
        c.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (1 if want else 0, pid))
        c.commit()
        return view(c, find_post(c, pid))


@app.post("/api/posts/{pid}/reports", status_code=201)
def report(pid: str, body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    with LOCK:
        c = con()
        p = find_post(c, pid)
        u = find_user(c, body["user"])
        if p["author_id"] == u["user_id"]:
            raise HTTPException(403, "자기 글은 신고할 수 없습니다")
        if c.execute("SELECT 1 FROM fd_reports WHERE post_id=? AND reporter_id=?", (pid, u["user_id"])).fetchone():
            raise HTTPException(409, "이미 신고했습니다")
        c.execute("INSERT INTO fd_reports VALUES (?,?)", (pid, u["user_id"]))
        c.commit()
        n = reports(c, pid)
        return {"reports": n, "hidden": n >= 3}


@app.post("/api/posts/{pid}/comments", status_code=201)
def comment(pid: str, body: dict[str, Any] = Body(default={})):
    need_user(body.get("user"))
    if not body_ok(body.get("body")):
        raise HTTPException(400, "내용을 확인하세요")
    with LOCK:
        c = con()
        find_post(c, pid)
        u = find_user(c, body["user"])
        cid = next_id(c, "fd_comments", "comment_id", "C")
        c.execute("INSERT INTO fd_comments VALUES (?,?,?,?,?)", (cid, pid, u["user_id"], body["body"].strip(), datetime.now().strftime("%Y-%m-%d %H:%M")))
        c.commit()
        return {"comment_id": cid, "post_id": pid, "author_id": u["user_id"], "body": body["body"].strip()}
