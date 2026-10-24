# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수만 모았다. T1 · T2 만 통과해야 채점기가 맞다.
실수: 더 보기를 쪽 번호(offset)로 · 공백만 있는 글 허용(strip 안 함) · 누구나 삭제 · 고정 개수 무제한 ·
      같은 사람의 신고를 또 셈 · 글을 본문보다 먼저 찾음(거부 순서) · 화면 없음."""
import csv
import os
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "feed.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE fd_users(user_id TEXT, name TEXT, role TEXT);
    CREATE TABLE fd_posts(post_id TEXT, author_id TEXT, body TEXT, created_at TEXT, pinned INTEGER, deleted INTEGER DEFAULT 0);
    CREATE TABLE fd_comments(comment_id TEXT, post_id TEXT, author_id TEXT, body TEXT, created_at TEXT);
    CREATE TABLE fd_reports(post_id TEXT, reporter_id TEXT);""")
    for name, sql in (("users.csv", "INSERT INTO fd_users VALUES (?,?,?)"),
                      ("posts.csv", "INSERT INTO fd_posts(post_id, author_id, body, created_at, pinned) VALUES (?,?,?,?,?)"),
                      ("comments.csv", "INSERT INTO fd_comments VALUES (?,?,?,?,?)"),
                      ("reports.csv", "INSERT INTO fd_reports VALUES (?,?)")):
        with open(os.path.join(SEED, name), encoding="utf-8") as f:
            c.executemany(sql, list(csv.reader(f))[1:])
    c.commit()
    c.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def view(c, p):
    n = c.execute("SELECT COUNT(*) FROM fd_reports WHERE post_id=?", (p["post_id"],)).fetchone()[0]
    return {"post_id": p["post_id"], "author_id": p["author_id"], "author_name": p["author_id"], "body": p["body"], "created_at": p["created_at"],
            "pinned": bool(int(p["pinned"])), "comment_count": 0, "hidden": n >= 3}


def post_or_404(c, pid):
    p = c.execute("SELECT * FROM fd_posts WHERE post_id=? AND deleted=0", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "글이 없습니다")                      # 실수: 본문(400)보다 먼저
    return p


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>사내 소식</h1></body></html>"


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM fd_users")]


@app.get("/api/posts")
def posts(viewer: str = "", before: str | None = None):
    c = con()
    off = int(before) if before and before.isdigit() else 0          # 실수: 쪽 번호(건너뛸 개수)
    rows = [p for p in c.execute("SELECT * FROM fd_posts WHERE deleted=0 AND pinned=0 ORDER BY created_at DESC, post_id DESC")
            if c.execute("SELECT COUNT(*) FROM fd_reports WHERE post_id=?", (p["post_id"],)).fetchone()[0] < 3]
    chunk = rows[off:off + 20]
    pinned = [] if before else [view(c, p) for p in c.execute("SELECT * FROM fd_posts WHERE deleted=0 AND pinned=1 ORDER BY created_at DESC")]
    return {"pinned": pinned, "posts": [view(c, p) for p in chunk], "next_cursor": str(off + 20) if off + 20 < len(rows) else None}


@app.post("/api/posts", status_code=201)
def create(body: dict[str, Any] = Body(default={})):
    text = body.get("body") or ""
    if not text or len(text) > 500:                                  # 실수: 공백만 있는 글을 거르지 않음
        raise HTTPException(400, "내용을 확인하세요")
    c = con()
    pid = "P%03d" % (c.execute("SELECT COUNT(*) FROM fd_posts").fetchone()[0] + 1)
    c.execute("INSERT INTO fd_posts(post_id, author_id, body, created_at, pinned) VALUES (?,?,?,?,0)",
              (pid, body.get("user"), text, datetime.now().strftime("%Y-%m-%d %H:%M")))
    c.commit()
    return view(c, post_or_404(c, pid))


@app.delete("/api/posts/{pid}")
def delete(pid: str, body: dict[str, Any] = Body(default={})):
    c = con()
    post_or_404(c, pid)                                              # 실수: 누구나 지운다
    c.execute("UPDATE fd_posts SET deleted=1 WHERE post_id=?", (pid,))
    c.commit()
    return {"deleted": pid}


@app.post("/api/posts/{pid}/pin")
def pin(pid: str, body: dict[str, Any] = Body(default={})):
    c = con()
    post_or_404(c, pid)
    u = c.execute("SELECT * FROM fd_users WHERE user_id=?", (body.get("user"),)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    if u["role"] != "admin":
        raise HTTPException(403, "운영자만 할 수 있습니다")
    c.execute("UPDATE fd_posts SET pinned=? WHERE post_id=?", (1 if body.get("pinned") else 0, pid))   # 실수: 개수 제한 없음
    c.commit()
    return view(c, post_or_404(c, pid))


@app.post("/api/posts/{pid}/reports", status_code=201)
def report(pid: str, body: dict[str, Any] = Body(default={})):
    c = con()
    post_or_404(c, pid)
    c.execute("INSERT INTO fd_reports VALUES (?,?)", (pid, body.get("user")))   # 실수: 자기 글 · 같은 사람 신고를 막지 않음
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM fd_reports WHERE post_id=?", (pid,)).fetchone()[0]
    return {"reports": n, "hidden": n >= 3}


@app.post("/api/posts/{pid}/comments", status_code=201)
def comment(pid: str, body: dict[str, Any] = Body(default={})):
    c = con()
    post_or_404(c, pid)
    c.execute("INSERT INTO fd_comments VALUES (?,?,?,?,?)", ("C900", pid, body.get("user"), body.get("body"), ""))
    c.commit()
    return {"comment_id": "C900"}
