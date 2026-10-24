import random
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "feed.db"
PAGE_SIZE = 20
HIDE_AT_REPORTS = 3  # 신고 N건 이상이면 일반 직원에게는 숨김 (운영자는 계속 보임)

app = FastAPI(title="다온소프트 사내 소식 피드")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  body TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports(
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, PRIMARY KEY(post_id, user_id));
CREATE INDEX IF NOT EXISTS idx_posts_order ON posts(pinned DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id, id);
"""

USERS = [
    ("박운영", "경영지원팀", 1), ("이관리", "인사팀", 1),
    ("김민준", "개발1팀", 0), ("이서연", "개발2팀", 0), ("박지호", "디자인팀", 0),
    ("최수아", "마케팅팀", 0), ("정도윤", "영업팀", 0), ("강하은", "QA팀", 0),
    ("조예린", "인사팀", 0), ("윤지우", "개발1팀", 0), ("장시우", "재무팀", 0),
    ("임나연", "고객지원팀", 0),
]
POST_TEXTS = [
    "오늘 점심 구내식당 메뉴가 제육볶음이래요. 줄 길어지기 전에 가세요!",
    "개발1팀 스프린트 회고 끝! 배포 자동화 덕분에 릴리스 시간이 반으로 줄었습니다.",
    "3층 휴게실 커피머신 원두가 새로 들어왔어요. 산미 있는 걸로 바꿨습니다.",
    "이번 주 금요일 팀 회식 장소 투표 받습니다. 댓글로 의견 주세요.",
    "신규 입사자 환영합니다! 다온소프트에서 즐겁게 일해요 :)",
    "디자인 시스템 v2 문서가 위키에 올라갔습니다. 피드백 환영해요.",
    "고객사 A의 만족도 조사에서 98점 받았습니다. 모두 수고하셨어요!",
    "사내 스터디 'FastAPI 입문' 참가자 모집합니다. 매주 수요일 저녁 7시.",
    "회의실 예약 시스템 점검으로 오늘 18시~19시 사용이 어렵습니다.",
    "비 오는 날엔 역시 전집이죠. 퇴근하고 한잔 하실 분?",
    "QA팀에서 회귀 테스트 자동화 범위를 80%까지 넓혔습니다.",
    "연차 사용 촉진 안내 메일 확인해 주세요. 하반기 잔여 연차를 미리 계획해 보세요.",
    "주차장 B구역 도색 작업으로 이번 주말 이용 불가입니다.",
    "마케팅팀 뉴스레터 10월호 발행했습니다. 읽어 주시면 감사해요.",
    "점심시간에 보드게임 번개 하실 분 계신가요? 4층 라운지입니다.",
    "서버 비용 최적화로 월 클라우드 비용을 18% 줄였습니다.",
    "사내 헬스장 샤워실 보수 완료! 이제 쾌적하게 쓰실 수 있어요.",
    "오늘 야근하시는 분들 간식 박스 3층에 두었습니다. 힘내세요!",
    "코드 리뷰 문화 개선 아이디어 있으면 공유해 주세요.",
    "분실물: 검은색 에어팟 케이스를 2층 복도에서 발견했어요. 경영지원팀에 맡겨두었습니다.",
]
COMMENT_TEXTS = [
    "좋은 소식이네요, 감사합니다!", "저도 참여하고 싶어요.", "오 대박, 수고하셨습니다 👏",
    "확인했습니다.", "다음에도 공유 부탁드려요.", "ㅋㅋㅋ 공감합니다", "시간 맞으면 갈게요!",
    "문서 링크 알려주실 수 있나요?", "덕분에 큰 도움 됐어요.", "정말 멋져요!",
]
NOTICES = [
    (1, "[공지] 10월 31일(금)은 전사 워크숍으로 정상 출근하지 않습니다. 세부 일정은 메일을 확인해 주세요."),
    (2, "[공지] 2026년 하반기 건강검진 신청이 11월 7일까지입니다. 인사팀 안내문을 참고하세요."),
]


def now_s(dt=None):
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        rnd = random.Random(42)
        conn.executemany("INSERT INTO users(name,dept,is_admin) VALUES(?,?,?)", USERS)
        member_ids = list(range(3, len(USERS) + 1))
        base = datetime.now()
        n = 70
        for i in range(n):  # 오래된 글부터 넣어 id가 클수록 최신
            created = base - timedelta(minutes=(n - i) * 97 + rnd.randint(0, 40))
            cur = conn.execute("INSERT INTO posts(user_id,body,pinned,created_at) VALUES(?,?,0,?)",
                               (rnd.choice(member_ids), rnd.choice(POST_TEXTS), now_s(created)))
            for _ in range(rnd.choice([0, 0, 1, 2, 3, 5])):
                conn.execute("INSERT INTO comments(post_id,user_id,body,created_at) VALUES(?,?,?,?)",
                             (cur.lastrowid, rnd.choice(member_ids), rnd.choice(COMMENT_TEXTS),
                              now_s(created + timedelta(minutes=rnd.randint(1, 600)))))
        for admin_id, text in NOTICES:
            conn.execute("INSERT INTO posts(user_id,body,pinned,created_at) VALUES(?,?,1,?)",
                         (admin_id, text, now_s(base - timedelta(minutes=5 + admin_id))))
        # 신고 데모: 한 글은 숨김 임계치 도달, 다른 글은 신고 1건
        spam = conn.execute("INSERT INTO posts(user_id,body,pinned,created_at) VALUES(?,?,0,?)",
                            (5, "지금 가입하면 100만원! 아래 링크 클릭 (광고성 스팸 예시)",
                             now_s(base - timedelta(minutes=30)))).lastrowid
        for uid in (3, 4, 6):
            conn.execute("INSERT INTO reports VALUES(?,?,?,?)", (spam, uid, "광고/스팸", now_s()))
        conn.execute("INSERT INTO reports VALUES(?,?,?,?)", (3, 7, "부적절한 내용", now_s()))
        conn.commit()


init_db()


# 인증(데모): X-User-Id 헤더로 '로그인한 사용자'를 식별한다. 실서비스에서는 세션/SSO로 교체할 것.
def current_user(x_user_id: int | None = Header(default=None), conn=Depends(db)):
    row = conn.execute("SELECT * FROM users WHERE id=?", (x_user_id,)).fetchone() if x_user_id else None
    if not row:
        raise HTTPException(401, "로그인이 필요합니다.")
    return row


class PostIn(BaseModel):
    body: str = Field(min_length=1, max_length=500)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=200)


class ReportIn(BaseModel):
    reason: str = Field(default="", max_length=100)


def clean(s: str) -> str:
    s = s.strip()
    if not s:
        raise HTTPException(422, "내용을 입력해 주세요.")
    return s


def get_post(conn, post_id):
    p = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not p:
        raise HTTPException(404, "글을 찾을 수 없습니다.")
    return p


def post_dict(r):
    return {
        "id": r["id"], "body": r["body"], "pinned": bool(r["pinned"]), "created_at": r["created_at"],
        "author": {"id": r["uid"], "name": r["name"], "dept": r["dept"], "is_admin": bool(r["is_admin"])},
        "comment_count": r["ccount"], "report_count": r["rcount"], "reported_by_me": bool(r["mine_rep"]),
        "mine": r["uid"] == r["me"],
    }


@app.get("/api/users")
def users(conn=Depends(db)):
    return [dict(r) for r in conn.execute("SELECT id,name,dept,is_admin FROM users ORDER BY is_admin DESC, id")]


@app.get("/api/me")
def me(u=Depends(current_user)):
    return {"id": u["id"], "name": u["name"], "dept": u["dept"], "is_admin": bool(u["is_admin"])}


@app.get("/api/posts")
def list_posts(cursor: str | None = Query(default=None, pattern=r"^[01]:\d+$"),
               u=Depends(current_user), conn=Depends(db)):
    """고정글 먼저, 그다음 최신순. 커서 기반이라 '더 보기' 도중 새 글이 올라와도 중복/누락이 없다."""
    where, params = [], [u["id"], u["id"]]
    if not u["is_admin"]:
        where.append("(SELECT COUNT(*) FROM reports r WHERE r.post_id=p.id) < ?")
        params.append(HIDE_AT_REPORTS)
    if cursor:
        pin, pid = map(int, cursor.split(":"))
        where.append("(p.pinned < ? OR (p.pinned = ? AND p.id < ?))")
        params += [pin, pin, pid]
    sql = f"""
      SELECT p.*, u.id AS uid, u.name, u.dept, u.is_admin, ? AS me,
        (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS ccount,
        (SELECT COUNT(*) FROM reports r WHERE r.post_id=p.id) AS rcount,
        (SELECT COUNT(*) FROM reports r WHERE r.post_id=p.id AND r.user_id=?) AS mine_rep
      FROM posts p JOIN users u ON u.id=p.user_id
      {'WHERE ' + ' AND '.join(where) if where else ''}
      ORDER BY p.pinned DESC, p.id DESC LIMIT ?"""
    rows = conn.execute(sql, params + [PAGE_SIZE + 1]).fetchall()
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    nxt = f"{rows[-1]['pinned']}:{rows[-1]['id']}" if more else None
    return {"items": [post_dict(r) for r in rows], "next_cursor": nxt}


@app.post("/api/posts", status_code=201)
def create_post(data: PostIn, u=Depends(current_user), conn=Depends(db)):
    cur = conn.execute("INSERT INTO posts(user_id,body,pinned,created_at) VALUES(?,?,0,?)",
                       (u["id"], clean(data.body), now_s()))
    return {"id": cur.lastrowid}


@app.delete("/api/posts/{post_id}", status_code=204)
def delete_post(post_id: int, u=Depends(current_user), conn=Depends(db)):
    p = get_post(conn, post_id)
    if p["user_id"] != u["id"]:
        raise HTTPException(403, "내가 쓴 글만 삭제할 수 있습니다.")
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))


@app.put("/api/posts/{post_id}/pin")
def pin_post(post_id: int, pinned: bool = True, u=Depends(current_user), conn=Depends(db)):
    if not u["is_admin"]:
        raise HTTPException(403, "운영자만 고정할 수 있습니다.")
    get_post(conn, post_id)
    conn.execute("UPDATE posts SET pinned=? WHERE id=?", (int(pinned), post_id))
    return {"pinned": pinned}


@app.post("/api/posts/{post_id}/report", status_code=201)
def report_post(post_id: int, data: ReportIn, u=Depends(current_user), conn=Depends(db)):
    p = get_post(conn, post_id)
    if p["user_id"] == u["id"]:
        raise HTTPException(400, "내 글은 신고할 수 없습니다.")
    try:
        conn.execute("INSERT INTO reports VALUES(?,?,?,?)", (post_id, u["id"], data.reason.strip(), now_s()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "이미 신고한 글입니다.")
    return {"ok": True}


@app.get("/api/posts/{post_id}/comments")
def list_comments(post_id: int, u=Depends(current_user), conn=Depends(db)):
    get_post(conn, post_id)
    rows = conn.execute("""SELECT c.id,c.body,c.created_at,c.user_id,u.name,u.dept FROM comments c
                           JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.id""", (post_id,))
    return [{"id": r["id"], "body": r["body"], "created_at": r["created_at"], "name": r["name"],
             "dept": r["dept"], "mine": r["user_id"] == u["id"]} for r in rows]


@app.post("/api/posts/{post_id}/comments", status_code=201)
def add_comment(post_id: int, data: CommentIn, u=Depends(current_user), conn=Depends(db)):
    get_post(conn, post_id)
    cur = conn.execute("INSERT INTO comments(post_id,user_id,body,created_at) VALUES(?,?,?,?)",
                       (post_id, u["id"], clean(data.body), now_s()))
    return {"id": cur.lastrowid}


@app.delete("/api/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, u=Depends(current_user), conn=Depends(db)):
    c = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not c:
        raise HTTPException(404, "댓글을 찾을 수 없습니다.")
    if c["user_id"] != u["id"]:
        raise HTTPException(403, "내가 쓴 댓글만 삭제할 수 있습니다.")
    conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
