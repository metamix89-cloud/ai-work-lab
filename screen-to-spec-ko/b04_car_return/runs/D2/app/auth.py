import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, Depends, HTTPException

from .billing import KST
from .db import connect

SESSION_HOURS = 12
COOKIE = "session"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _, _ = stored.partition("$")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)), stored)


_DUMMY = hash_password("dummy")  # 없는 아이디도 같은 시간이 걸리도록


def check_login(conn, username: str, password: str):
    u = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    ok = verify_password(password, u["pw_hash"] if u else _DUMMY)
    return u if (u and ok) else None


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)",
                 (token, user_id, datetime.now(KST).isoformat()))
    return token


def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(session: str | None = Cookie(default=None), conn=Depends(get_conn)):
    if not session:
        raise HTTPException(401, "로그인이 필요합니다.")
    row = conn.execute(
        "SELECT u.id,u.username,u.name,u.role,s.created_at FROM sessions s JOIN users u ON u.id=s.user_id"
        " WHERE s.token=?", (session,)).fetchone()
    if row is None or datetime.now(KST) - datetime.fromisoformat(row["created_at"]) > timedelta(hours=SESSION_HOURS):
        raise HTTPException(401, "로그인이 필요합니다.")
    return dict(row)


def staff_only(user=Depends(current_user)):
    if user["role"] != "staff":
        raise HTTPException(403, "직원만 사용할 수 있습니다.")
    return user
