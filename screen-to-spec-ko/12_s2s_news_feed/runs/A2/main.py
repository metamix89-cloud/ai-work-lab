"""다온소프트 사내 소식 피드 — FastAPI + SQLite.

실행: python -m uvicorn main:app --reload   (http://127.0.0.1:8000)
"""
import hashlib
import hmac
import os
import random
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "feed.db"
PAGE_SIZE = 20
MAX_POST = 500
MAX_COMMENT = 200

app = FastAPI(title="다온소프트 사내 소식 피드")


# ---------------------------------------------------------------- DB
def connect():
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


def hash_pw(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + "$" + digest.hex()


def check_pw(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    again = hash_pw(password, bytes.fromhex(salt_hex)).split("$")[1]
    return hmac.compare_digest(again, digest_hex)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  dept TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  content TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, pinned_at TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(post_id, user_id));
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(id DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
"""

USERS = [  # username, 이름, 부서, 관리자
    ("admin", "운영팀 관리자", "경영지원", 1),
    ("minjun", "김민준", "개발1팀", 0),
    ("seoyeon", "이서연", "디자인", 0),
    ("jihoon", "박지훈", "개발2팀", 0),
    ("haeun", "최하은", "인사", 0),
    ("doyun", "정도윤", "영업", 0),
    ("yuna", "한유나", "마케팅", 0),
    ("sungmin", "오성민", "QA", 0),
    ("jiwoo", "윤지우", "개발1팀", 0),
]

NOTICES = [
    "📢 [공지] 10월 31일(금) 오후 2시 전사 타운홀이 3층 대회의실에서 열립니다. 온라인 참석 링크는 사내 메일을 확인해 주세요.",
    "🔒 [공지] 보안 점검 기간(11/3~11/7) 동안 VPN 재인증이 필요합니다. 업무 중단을 막으려면 미리 갱신해 주세요.",
]
POSTS = [
    "오늘 점심 구내식당 제육볶음 대박이네요. 줄 서는 거 이해됨 🍚",
    "새로 배포한 v2.4 결제 모듈 무사히 나갔습니다. 야근하신 개발1팀 감사합니다!",
    "3층 휴게실 커피머신 원두 새로 들어왔어요. 산미 있는 걸로 바꿨습니다 ☕",
    "디자인 시스템 토큰 정리 문서 공유합니다. 피드백은 댓글로 주세요.",
    "금요일 팀 회식 장소 투표합니다. 고기 vs 회 vs 파스타",
    "QA 자동화 파이프라인 실행 시간이 40분에서 12분으로 줄었어요 🎉",
    "주차장 B구역 조명 나간 것 같아요. 총무팀 확인 부탁드립니다.",
    "신규 입사자 환영합니다! 이번 주 목요일 온보딩 점심 같이 해요.",
    "회의실 예약 시스템에서 반복 예약이 안 풀리는 버그 발견했습니다.",
    "스탠딩 데스크 써 보신 분 계신가요? 허리가 너무 아파서 고민 중이에요.",
    "사내 스터디 'Rust 입문' 같이 하실 분 구해요. 매주 수요일 저녁 7시.",
    "오늘 비 온다는데 우산 공용 바구니 1층에 채워 뒀습니다 ☔",
    "고객사 데모 무사히 끝났습니다. 반응 좋았어요. 다들 고생하셨습니다!",
    "복지포인트 소진 기한이 12월 15일입니다. 잊지 마세요.",
    "점심시간 탁구대 리그전 참가자 모집해요. 초보 환영 🏓",
    "코드 리뷰 때 '왜'를 적어 주면 정말 도움이 돼요. 작은 팁 공유합니다.",
    "프린터 3호기 토너 교체 완료했습니다.",
    "마케팅 캠페인 클릭률이 지난달 대비 18% 올랐어요. 크리에이티브 팀 덕분!",
    "이번 분기 OKR 회고 템플릿 공유드립니다.",
    "퇴근길 지하철 2호선 지연 중이래요. 참고하세요.",
    "사내 도서관에 신간 들어왔어요. 'Designing Data-Intensive Applications' 개정판 있습니다.",
    "재택 근무 시 VPN 끊김 현상 있으시면 IT 헬프데스크에 알려 주세요.",
    "오늘 하늘 너무 예뻐서 옥상 올라가 봤어요. 10분 힐링 ✨",
    "팀 간 지식 공유 세션 '성능 튜닝 사례' 발표자 모집합니다.",
    "연말 송년회 일정 설문 올렸습니다. 이번 주까지 응답 부탁드려요.",
    "신규 서비스 로고 시안 3종 공유합니다. 의견 환영!",
    "스테이징 서버 점검으로 오늘 18시부터 1시간 접속이 어렵습니다.",
    "점심 샐러드 정기 배달 같이 시키실 분? 5명 이상이면 할인돼요.",
    "회사 근처 새로 생긴 칼국수집 추천합니다. 김치가 맛있어요.",
    "배포 체크리스트 v3 업데이트했습니다. 롤백 절차가 추가됐어요.",
    "야근 식대 정산 방법이 바뀌었습니다. 공지 메일 확인해 주세요.",
    "오늘 생일인 동료분들 축하합니다 🎂",
    "고객 문의 응대 가이드 개정본 공유합니다.",
    "버그 바운티 이벤트 시작합니다! 내부 서비스에서 이슈를 찾아 주세요.",
    "에어컨 온도 너무 낮다는 의견이 있어서 26도로 조정했습니다.",
    "사내 마라톤 동호회 첫 모임 이번 토요일 아침 7시 한강공원입니다 🏃",
    "문서 번역 자동화 툴 베타 테스트 참여자 모십니다.",
    "이번 주 금요일은 가정의 날입니다. 오후 5시 정시 퇴근 권장해요.",
    "슬랙 채널 정리했습니다. 안 쓰는 채널은 아카이브 처리됐어요.",
    "접근성 점검 도구로 대시보드를 확인해 봤더니 대비 문제가 꽤 있네요. 개선 티켓 올렸습니다.",
    "CI 캐시 설정 바꿔서 빌드 시간이 절반으로 줄었습니다.",
    "휴가 사용 촉진 안내: 잔여 연차 확인해 주세요.",
    "점심 후 산책 모임 만들어요. 12:40 로비 집합 🚶",
    "고객사 피드백 요약본 올렸습니다. 공통 요청은 '다크 모드'네요.",
    "개발자 컨퍼런스 참가 지원 신청 받습니다. 인당 50만 원 한도입니다.",
    "책상 정리의 날! 이번 주 금요일 오전에 같이 정리해요.",
    "신입 멘토링 프로그램 멘토 지원 받아요. 경력 2년 이상 누구나!",
    "엘리베이터 점검으로 내일 오전 10시~11시 이용이 어렵습니다.",
    "신규 복지: 사내 헬스장 이용권 지원이 시작됩니다 💪",
    "데이터 분석 대시보드 개편안 공유합니다.",
    "오늘 회의록 템플릿 새로 만들어서 공유 드라이브에 올렸어요.",
    "분실물: 3층 화장실 앞에서 검은색 우산을 발견했습니다. 총무팀에 맡겨 둘게요.",
    "사내 해커톤 아이디어 모집합니다. 팀 구성은 자유!",
    "퇴사하시는 분께 마지막 인사. 그동안 감사했습니다 🙏",
    "새 모니터 암 신청하신 분들 수령해 가세요.",
    "점심시간 보드게임 모임 다음 주에도 이어집니다 🎲",
    "API 응답 지연 이슈 원인을 찾았습니다. 인덱스 누락이었어요.",
    "오늘의 한 줄 팁: 커밋 메시지는 미래의 나를 위한 편지입니다.",
    "회의 없는 수요일 시범 운영, 다음 달에도 계속합니다!",
    "사내 메신저 알림 설정 가이드 올렸어요. 방해 금지 시간을 꼭 설정해 보세요.",
    "건강검진 예약 마감이 다가옵니다. 인사팀 공지 확인해 주세요.",
    "이번 스프린트 데모 영상 공유합니다. 3분 분량이에요.",
    "주말에 본 영화 추천해 주세요. 가볍게 볼 만한 걸로 🎬",
]
COMMENTS = [
    "좋은 소식이네요!", "공유 감사합니다 👍", "저도 참여할게요!", "확인했습니다.",
    "오 대박", "고생 많으셨어요", "저도 궁금했는데 잘 됐네요", "다음에도 부탁드려요 🙌",
    "ㅋㅋㅋ 공감합니다", "자세한 내용 DM 드릴게요.", "수고하셨습니다!", "저 한 표 던집니다.",
]


def now_iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    first = not DB_PATH.exists()
    con = connect()
    con.executescript(SCHEMA)
    if first:
        seed(con)
    con.commit()
    con.close()


def seed(con: sqlite3.Connection):
    rnd = random.Random(7)
    for username, name, dept, admin in USERS:
        pw = "admin1234" if admin else "1234"
        con.execute("INSERT INTO users(username,name,dept,is_admin,pw_hash) VALUES(?,?,?,?,?)",
                    (username, name, dept, admin, hash_pw(pw)))
    admin_id = 1
    employees = list(range(2, len(USERS) + 1))
    start = datetime.now() - timedelta(days=30)
    total = len(POSTS)
    step = (timedelta(days=30) - timedelta(hours=1)) / total
    for i, text in enumerate(POSTS):
        ts = now_iso(start + step * i + timedelta(minutes=rnd.randint(0, 40)))
        cur = con.execute("INSERT INTO posts(user_id,content,created_at) VALUES(?,?,?)",
                          (rnd.choice(employees), text, ts))
        for _ in range(rnd.choice([0, 0, 1, 2, 3, 5])):
            con.execute("INSERT INTO comments(post_id,user_id,content,created_at) VALUES(?,?,?,?)",
                        (cur.lastrowid, rnd.choice(employees), rnd.choice(COMMENTS), ts))
    for n, text in enumerate(NOTICES):
        ts = now_iso(datetime.now() - timedelta(days=2 - n))
        con.execute("INSERT INTO posts(user_id,content,pinned,pinned_at,created_at) VALUES(?,?,1,?,?)",
                    (admin_id, text, ts, ts))
    # 신고 샘플: 운영자가 확인해 볼 만한 글
    con.execute("INSERT INTO reports(post_id,user_id,reason,created_at) VALUES(?,?,?,?)",
                (5, 3, "투표 글이 아니라 스팸 같아요", now_iso()))


# ---------------------------------------------------------------- 인증
class Login(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=100)


def current_user(session: str | None = Cookie(default=None), db: sqlite3.Connection = Depends(get_db)):
    if session:
        row = db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
                         (session,)).fetchone()
        if row:
            return row
    raise HTTPException(401, "로그인이 필요합니다.")


def admin_only(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "운영자만 할 수 있습니다.")
    return user


def user_json(u):
    return {"id": u["id"], "username": u["username"], "name": u["name"], "dept": u["dept"],
            "is_admin": bool(u["is_admin"])}


@app.post("/api/login")
def login(body: Login, response: Response, db: sqlite3.Connection = Depends(get_db)):
    u = db.execute("SELECT * FROM users WHERE username=?", (body.username.strip(),)).fetchone()
    if not u or not check_pw(body.password, u["pw_hash"]):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)", (token, u["id"]))
    response.set_cookie("session", token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 7)
    return user_json(u)


@app.post("/api/logout")
def logout(response: Response, session: str | None = Cookie(default=None),
           db: sqlite3.Connection = Depends(get_db)):
    if session:
        db.execute("DELETE FROM sessions WHERE token=?", (session,))
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user_json(user)


# ---------------------------------------------------------------- 글
class PostIn(BaseModel):
    content: str = Field(max_length=MAX_POST)


class CommentIn(BaseModel):
    content: str = Field(max_length=MAX_COMMENT)


class ReportIn(BaseModel):
    reason: str = Field(max_length=200)


POST_SQL = """
SELECT p.id, p.content, p.pinned, p.created_at, p.user_id, u.name AS author, u.dept, u.is_admin AS author_admin,
  (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comment_count,
  (SELECT COUNT(*) FROM reports r WHERE r.post_id=p.id) AS report_count,
  EXISTS(SELECT 1 FROM reports r WHERE r.post_id=p.id AND r.user_id=:me) AS reported_by_me
FROM posts p JOIN users u ON u.id=p.user_id
"""


def post_json(row, user):
    return {
        "id": row["id"], "content": row["content"], "pinned": bool(row["pinned"]),
        "created_at": row["created_at"], "author": row["author"], "dept": row["dept"],
        "author_admin": bool(row["author_admin"]), "comment_count": row["comment_count"],
        "mine": row["user_id"] == user["id"], "reported_by_me": bool(row["reported_by_me"]),
        # 신고 건수는 운영자에게만 노출
        "report_count": row["report_count"] if user["is_admin"] else None,
    }


@app.get("/api/posts")
def list_posts(before: int | None = None, user=Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)):
    """고정글은 첫 페이지(before 없음)에서만 맨 위에 내려가고, 일반 글은 id 내림차순 커서 페이징."""
    pinned = []
    if before is None:
        rows = db.execute(POST_SQL + " WHERE p.pinned=1 ORDER BY p.pinned_at DESC", {"me": user["id"]}).fetchall()
        pinned = [post_json(r, user) for r in rows]
    rows = db.execute(
        POST_SQL + " WHERE p.pinned=0 AND (:before IS NULL OR p.id < :before) ORDER BY p.id DESC LIMIT :n",
        {"me": user["id"], "before": before, "n": PAGE_SIZE + 1}).fetchall()
    has_more = len(rows) > PAGE_SIZE
    posts = [post_json(r, user) for r in rows[:PAGE_SIZE]]
    return {"pinned": pinned, "posts": posts, "has_more": has_more,
            "next_before": posts[-1]["id"] if posts else None}


@app.post("/api/posts", status_code=201)
def create_post(body: PostIn, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "내용을 입력해 주세요.")
    cur = db.execute("INSERT INTO posts(user_id,content,created_at) VALUES(?,?,?)",
                     (user["id"], text, now_iso()))
    row = db.execute(POST_SQL + " WHERE p.id=:id", {"me": user["id"], "id": cur.lastrowid}).fetchone()
    return post_json(row, user)


def get_post_or_404(db, post_id):
    row = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not row:
        raise HTTPException(404, "글을 찾을 수 없습니다.")
    return row


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    post = get_post_or_404(db, post_id)
    if post["user_id"] != user["id"]:
        raise HTTPException(403, "자기 글만 삭제할 수 있습니다.")
    db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    return {"ok": True}


@app.post("/api/posts/{post_id}/pin")
def pin_post(post_id: int, user=Depends(admin_only), db: sqlite3.Connection = Depends(get_db)):
    post = get_post_or_404(db, post_id)
    if post["pinned"]:
        db.execute("UPDATE posts SET pinned=0, pinned_at=NULL WHERE id=?", (post_id,))
    else:
        db.execute("UPDATE posts SET pinned=1, pinned_at=? WHERE id=?", (now_iso(), post_id))
    return {"pinned": not post["pinned"]}


@app.post("/api/posts/{post_id}/report", status_code=201)
def report_post(post_id: int, body: ReportIn, user=Depends(current_user),
                db: sqlite3.Connection = Depends(get_db)):
    post = get_post_or_404(db, post_id)
    if post["user_id"] == user["id"]:
        raise HTTPException(400, "자기 글은 신고할 수 없습니다.")
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "신고 사유를 입력해 주세요.")
    try:
        db.execute("INSERT INTO reports(post_id,user_id,reason,created_at) VALUES(?,?,?,?)",
                   (post_id, user["id"], reason, now_iso()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "이미 신고한 글입니다.")
    return {"ok": True}


@app.get("/api/reports")
def list_reports(user=Depends(admin_only), db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("""
        SELECT p.id AS post_id, p.content, a.name AS author, COUNT(r.id) AS count,
               GROUP_CONCAT(r.reason, ' / ') AS reasons
        FROM reports r JOIN posts p ON p.id=r.post_id JOIN users a ON a.id=p.user_id
        GROUP BY p.id ORDER BY count DESC, MAX(r.id) DESC""").fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/posts/{post_id}/reports")
def dismiss_reports(post_id: int, user=Depends(admin_only), db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM reports WHERE post_id=?", (post_id,))
    return {"ok": True}


# ---------------------------------------------------------------- 댓글
@app.get("/api/posts/{post_id}/comments")
def list_comments(post_id: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    get_post_or_404(db, post_id)
    rows = db.execute("""SELECT c.id, c.content, c.created_at, c.user_id, u.name AS author, u.dept
                         FROM comments c JOIN users u ON u.id=c.user_id
                         WHERE c.post_id=? ORDER BY c.id""", (post_id,)).fetchall()
    return [{"id": r["id"], "content": r["content"], "created_at": r["created_at"],
             "author": r["author"], "dept": r["dept"], "mine": r["user_id"] == user["id"]} for r in rows]


@app.post("/api/posts/{post_id}/comments", status_code=201)
def add_comment(post_id: int, body: CommentIn, user=Depends(current_user),
                db: sqlite3.Connection = Depends(get_db)):
    get_post_or_404(db, post_id)
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "내용을 입력해 주세요.")
    db.execute("INSERT INTO comments(post_id,user_id,content,created_at) VALUES(?,?,?,?)",
               (post_id, user["id"], text, now_iso()))
    return {"ok": True}


@app.delete("/api/comments/{comment_id}")
def delete_comment(comment_id: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    c = db.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not c:
        raise HTTPException(404, "댓글을 찾을 수 없습니다.")
    if c["user_id"] != user["id"]:
        raise HTTPException(403, "자기 댓글만 삭제할 수 있습니다.")
    db.execute("DELETE FROM comments WHERE id=?", (comment_id,))
    return {"ok": True}


# ---------------------------------------------------------------- 정적 파일
@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

init_db()
