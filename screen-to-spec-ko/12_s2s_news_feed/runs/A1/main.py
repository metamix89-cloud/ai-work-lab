"""다온소프트 사내 소식 피드 — FastAPI + SQLite."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("FEED_DB", str(BASE / "feed.db"))
PAGE_SIZE = 20
DEMO_PASSWORD = "daon1234"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  dept TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
  salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL REFERENCES users(id),
  content TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES users(id), content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  reporter_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(post_id, reporter_id));
CREATE INDEX IF NOT EXISTS idx_posts_pinned_id ON posts(pinned, id);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


app = FastAPI(title="다온소프트 사내 소식 피드")


@app.on_event("startup")
def startup():
    con = connect()
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        import seed
        seed.run(con)
    con.commit()
    con.close()


# ---------- 인증 ----------
def current_user(authorization: str = Header(default=""), db: sqlite3.Connection = Depends(get_db)):
    token = authorization.removeprefix("Bearer ").strip()
    row = db.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires_at > ?",
        (token, now()),
    ).fetchone()
    if not row:
        raise HTTPException(401, "로그인이 필요합니다.")
    return row


def public_user(u) -> dict:
    return {"id": u["id"], "name": u["name"], "dept": u["dept"], "is_admin": bool(u["is_admin"])}


class LoginIn(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=100)


@app.post("/api/login")
def login(body: LoginIn, db: sqlite3.Connection = Depends(get_db)):
    u = db.execute("SELECT * FROM users WHERE username = ?", (body.username.strip(),)).fetchone()
    # 사용자 유무와 무관하게 비슷한 시간이 걸리도록 항상 해시를 계산
    salt = u["salt"] if u else "00" * 16
    ok = hmac.compare_digest(hash_pw(body.password, salt), u["pw_hash"] if u else "x")
    if not u or not ok:
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
    db.execute(
        "INSERT INTO sessions VALUES (?,?,?)",
        (token, u["id"], (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")),
    )
    return {"token": token, "user": public_user(u)}


@app.post("/api/logout", status_code=204)
def logout(authorization: str = Header(default=""), db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM sessions WHERE token = ?", (authorization.removeprefix("Bearer ").strip(),))


@app.get("/api/me")
def me(user=Depends(current_user)):
    return public_user(user)


# ---------- 글 ----------
POST_SELECT = """
SELECT p.id, p.content, p.pinned, p.created_at, p.author_id, u.name AS author_name, u.dept AS author_dept,
  (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS comment_count,
  (SELECT COUNT(*) FROM reports r WHERE r.post_id = p.id) AS report_count,
  EXISTS(SELECT 1 FROM reports r WHERE r.post_id = p.id AND r.reporter_id = :me) AS reported_by_me
FROM posts p JOIN users u ON u.id = p.author_id
"""


def post_dict(r, user) -> dict:
    return {
        "id": r["id"], "content": r["content"], "pinned": bool(r["pinned"]), "created_at": r["created_at"],
        "author": {"id": r["author_id"], "name": r["author_name"], "dept": r["author_dept"]},
        "comment_count": r["comment_count"], "mine": r["author_id"] == user["id"],
        "reported_by_me": bool(r["reported_by_me"]),
        # 신고 수는 운영자에게만 노출
        "report_count": r["report_count"] if user["is_admin"] else None,
    }


@app.get("/api/posts")
def list_posts(before: int | None = Query(default=None, ge=1), user=Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)):
    """고정 글은 첫 요청에서만 내려주고, 일반 글은 id 기준 커서(before)로 20개씩 이어서 준다."""
    pinned = []
    if before is None:
        rows = db.execute(POST_SELECT + " WHERE p.pinned = 1 ORDER BY p.id DESC", {"me": user["id"]}).fetchall()
        pinned = [post_dict(r, user) for r in rows]
    rows = db.execute(
        POST_SELECT + " WHERE p.pinned = 0 AND p.id < :before ORDER BY p.id DESC LIMIT :n",
        {"me": user["id"], "before": before or 2**62, "n": PAGE_SIZE + 1},
    ).fetchall()
    return {
        "pinned": pinned,
        "posts": [post_dict(r, user) for r in rows[:PAGE_SIZE]],
        "has_more": len(rows) > PAGE_SIZE,
    }


class PostIn(BaseModel):
    content: str = Field(max_length=500)


def clean(text: str, label: str) -> str:
    text = text.strip()
    if not text:
        raise HTTPException(422, f"{label} 내용을 입력해 주세요.")
    return text


@app.post("/api/posts", status_code=201)
def create_post(body: PostIn, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    cur = db.execute("INSERT INTO posts(author_id, content, created_at) VALUES (?,?,?)",
                     (user["id"], clean(body.content, "글"), now()))
    r = db.execute(POST_SELECT + " WHERE p.id = :id", {"me": user["id"], "id": cur.lastrowid}).fetchone()
    return post_dict(r, user)


def get_post(db, post_id: int):
    p = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not p:
        raise HTTPException(404, "글을 찾을 수 없습니다.")
    return p


@app.delete("/api/posts/{post_id}", status_code=204)
def delete_post(post_id: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    if get_post(db, post_id)["author_id"] != user["id"]:
        raise HTTPException(403, "내가 쓴 글만 삭제할 수 있습니다.")
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))


class PinIn(BaseModel):
    pinned: bool


@app.put("/api/posts/{post_id}/pin")
def pin_post(post_id: int, body: PinIn, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    if not user["is_admin"]:
        raise HTTPException(403, "운영자만 공지를 고정할 수 있습니다.")
    get_post(db, post_id)
    db.execute("UPDATE posts SET pinned = ? WHERE id = ?", (int(body.pinned), post_id))
    return {"id": post_id, "pinned": body.pinned}


class ReportIn(BaseModel):
    reason: str = Field(max_length=200)


@app.post("/api/posts/{post_id}/report", status_code=201)
def report_post(post_id: int, body: ReportIn, user=Depends(current_user),
                db: sqlite3.Connection = Depends(get_db)):
    if get_post(db, post_id)["author_id"] == user["id"]:
        raise HTTPException(400, "내가 쓴 글은 신고할 수 없습니다.")
    try:
        db.execute("INSERT INTO reports(post_id, reporter_id, reason, created_at) VALUES (?,?,?,?)",
                   (post_id, user["id"], clean(body.reason, "신고 사유"), now()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "이미 신고한 글입니다.")
    return {"ok": True}


@app.get("/api/reports")
def list_reports(user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    """운영자 전용: 신고된 글을 신고 많은 순으로."""
    if not user["is_admin"]:
        raise HTTPException(403, "운영자만 볼 수 있습니다.")
    rows = db.execute("""
        SELECT p.id, p.content, u.name AS author_name, COUNT(r.id) AS cnt,
               GROUP_CONCAT(r.reason, ' / ') AS reasons
        FROM reports r JOIN posts p ON p.id = r.post_id JOIN users u ON u.id = p.author_id
        GROUP BY p.id ORDER BY cnt DESC, p.id DESC""").fetchall()
    return [dict(r) for r in rows]


# ---------- 댓글 ----------
@app.get("/api/posts/{post_id}/comments")
def list_comments(post_id: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    get_post(db, post_id)
    rows = db.execute("""SELECT c.id, c.content, c.created_at, c.author_id, u.name, u.dept
        FROM comments c JOIN users u ON u.id = c.author_id WHERE c.post_id = ? ORDER BY c.id""",
                      (post_id,)).fetchall()
    return [{"id": r["id"], "content": r["content"], "created_at": r["created_at"],
             "author": {"id": r["author_id"], "name": r["name"], "dept": r["dept"]},
             "mine": r["author_id"] == user["id"]} for r in rows]


class CommentIn(BaseModel):
    content: str = Field(max_length=200)


@app.post("/api/posts/{post_id}/comments", status_code=201)
def add_comment(post_id: int, body: CommentIn, user=Depends(current_user),
                db: sqlite3.Connection = Depends(get_db)):
    get_post(db, post_id)
    ts = now()
    cur = db.execute("INSERT INTO comments(post_id, author_id, content, created_at) VALUES (?,?,?,?)",
                     (post_id, user["id"], clean(body.content, "댓글"), ts))
    return {"id": cur.lastrowid, "content": body.content.strip(), "created_at": ts,
            "author": {"id": user["id"], "name": user["name"], "dept": user["dept"]}, "mine": True}


@app.delete("/api/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    c = db.execute("SELECT author_id FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if not c:
        raise HTTPException(404, "댓글을 찾을 수 없습니다.")
    if c["author_id"] != user["id"]:
        raise HTTPException(403, "내가 쓴 댓글만 삭제할 수 있습니다.")
    db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))


# ---------- 정적 파일 ----------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
