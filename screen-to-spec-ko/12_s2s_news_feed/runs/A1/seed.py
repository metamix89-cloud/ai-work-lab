"""가상 데이터 (DB가 비어 있을 때 최초 1회 자동 삽입). 모든 계정 비밀번호: daon1234"""
import random
import secrets
from datetime import datetime, timedelta

from main import DEMO_PASSWORD, hash_pw

USERS = [  # username, 이름, 부서, 운영자
    ("admin", "박운영", "경영지원팀", 1),
    ("minjun", "김민준", "개발1팀", 0),
    ("seoyeon", "이서연", "개발2팀", 0),
    ("jiwoo", "최지우", "디자인팀", 0),
    ("hyunwoo", "정현우", "QA팀", 0),
    ("yuna", "한유나", "마케팅팀", 0),
    ("doyun", "오도윤", "인프라팀", 0),
    ("sua", "강수아", "인사팀", 0),
    ("taeho", "윤태호", "영업팀", 0),
    ("hana", "서하나", "개발1팀", 0),
]

NOTICES = [
    "[공지] 10월 31일(금) 전사 보안 교육이 있습니다. 14:00 대회의실, 온라인 참석도 가능합니다. 미이수 시 인사팀에서 개별 연락드립니다.",
    "[공지] 사내 메신저 점검으로 11월 2일(일) 02:00~04:00 서비스가 중단됩니다. 업무에 참고해 주세요.",
]

POSTS = [
    "오늘 점심 구내식당 제육볶음 정말 맛있네요 🍚", "배포 끝났습니다! 다들 수고 많으셨어요 🎉",
    "3층 프린터 용지 보충했습니다. 필요하시면 말씀하세요.", "다음 주 팀 회식 장소 추천 받습니다. 강남역 근처로요!",
    "신규 디자인 시스템 v2 문서 공유드립니다. 피드백 환영해요.", "비 오는데 우산 놓고 오신 분? 로비에 하나 남아 있어요 ☔",
    "QA 자동화 스크립트 개선해서 회귀 테스트 시간이 40분에서 15분으로 줄었습니다.",
    "신입사원 환영합니다! 개발2팀에 새 식구가 왔어요 👋", "서버 비용 리포트 나왔습니다. 지난달 대비 12% 절감!",
    "혹시 회의실 B 빔프로젝터 리모컨 못 보셨나요?", "주말에 사내 풋살 동호회 모집합니다. 초보 환영 ⚽",
    "도넛 사 왔어요. 탕비실에 있으니 드세요 🍩", "코드 리뷰 문화 개선 아이디어 있으신 분 의견 부탁드립니다.",
    "오늘 야근하시는 분들 파이팅입니다 💪", "고객사 데모 무사히 마쳤습니다. 도와주신 모든 분께 감사드려요.",
    "사내 도서 신청 받습니다. 이번 달 주제는 '클린 아키텍처'예요.", "엘리베이터 2호기 점검 중이니 1호기 이용 부탁드립니다.",
    "슬랙 채널 #잡담 에 퇴근길 맛집 공유 스레드 열었어요.", "FastAPI 사내 스터디 2기 모집 중입니다. 매주 목요일 19시!",
    "복사기 토너 교체 완료. 흑백/컬러 모두 정상입니다.", "내일 비 예보 있으니 재택 신청 마감 전에 확인하세요.",
    "새로 나온 디자인 툴 써 봤는데 협업 기능이 괜찮더라고요.", "분리수거 함 위치가 바뀌었습니다. 탕비실 옆으로 이동!",
    "제 자리 모니터 암 남는 거 필요하신 분 가져가세요.", "이번 스프린트 회고 정리해서 위키에 올렸습니다.",
    "커피머신 원두 새로 바꿨어요. 취향 투표 올립니다 ☕", "연차 사용 촉진 안내 메일 확인해 주세요.",
    "장애 대응 훈련 결과 공유합니다. 평균 복구 시간 8분.", "금요일 점심 팀 간 교류 런치, 신청은 인사팀으로!",
    "회의실 예약 시스템에 반복 예약 기능이 추가됐습니다.", "사무실 온도 너무 춥지 않나요? 담요 하나 빌려드려요.",
    "블로그에 기술 포스팅 올렸어요. 읽어 주시면 감사하겠습니다.", "오늘 생일인 분 축하해요! 🎂 케이크는 4시에.",
    "신제품 랜딩 페이지 시안 3종 투표 부탁드립니다.", "VPN 접속이 느리다면 인프라팀에 티켓 남겨 주세요.",
    "사내 헬스장 이용 시간이 22시까지로 연장됐어요.", "점심시간 주차 정산 방법 정리해 둡니다.",
    "신입 온보딩 자료 리뉴얼했습니다. 피드백 주세요.", "보안 패치 적용 안 된 노트북은 이번 주까지 업데이트해 주세요.",
    "다음 주 월요일은 대체공휴일 아니고 정상 근무입니다!", "개발 문서 번역 자원봉사자 구해요. 영어 잘하시는 분~",
    "오늘 구내식당 후식 아이스크림 👍", "사내 해커톤 아이디어 접수 시작합니다. 팀당 최대 5명.",
    "마케팅 캠페인 성과 요약: 신규 가입자 +23%.", "택배 보관함 비밀번호가 변경되었습니다. 총무에 문의하세요.",
    "점심 같이 드실 분 12시에 로비에서 만나요.", "테스트 서버 데이터 초기화 예정입니다. 금요일 18시.",
    "회사 근처 새로 생긴 카페 괜찮더라고요. 쿠폰 공유해요.", "접근성 점검 체크리스트 초안 공유합니다.",
    "이번 주 금요일은 가정의 날, 정시 퇴근 합시다 🏠", "프론트엔드 번들 크기 30% 줄였어요. 방법 정리해서 공유할게요.",
    "사내 설문에 많은 참여 부탁드립니다. 5분이면 끝나요.", "누가 탕비실 냉장고 정리 좀… 유통기한 지난 게 많아요 😅",
    "야근 식대 정산 규정이 바뀌었습니다. 인사팀 공지 확인!", "좋은 아침입니다! 오늘도 힘내봐요 ☀️",
    "주간 회의록 템플릿 업데이트했습니다.", "화상회의 시 마이크 음소거 습관, 우리 모두 지켜요 🎤",
    "사내 스터디룸 이용 후 정리 부탁드립니다.", "릴리즈 노트 초안 올렸어요. 오탈자 제보 환영.",
    "남는 영화 시사회 티켓 2장, 원하는 분 댓글 주세요.", "신규 모니터 지급 신청은 총무팀 게시판에서!",
    "오늘 회의 자료 폴더 권한 열어 두었습니다.", "비밀번호 90일 변경 주기, 잊지 마세요 🔐",
    "점심 메뉴 투표: 국밥 vs 파스타 — 댓글로 의견 주세요.", "개발자 컨퍼런스 참가 후기 공유드립니다.",
    "엘리베이터에서 만난 고양이 사진 보고 가세요 🐱", "다음 달 워크숍 장소 후보 세 곳을 정리했습니다.",
]

COMMENTS = [
    "좋은 정보 감사합니다!", "저도 동의해요 👍", "수고하셨습니다~", "오 대박이네요", "확인했습니다.",
    "저 참여할게요!", "다음에는 저도 불러 주세요 ㅎㅎ", "공유 감사합니다 🙏", "역시 팀장님 센스!",
    "혹시 자료 링크 있을까요?", "맛있겠다…", "고생 많으셨어요.", "내일 더 자세히 얘기해요.",
]

REPORT_REASONS = ["광고성 글입니다", "업무와 무관한 내용입니다", "불쾌한 표현이 있습니다"]


def run(con):
    rnd = random.Random(42)  # 항상 같은 데이터가 나오도록 고정
    ids = []
    for username, name, dept, admin in USERS:
        salt = secrets.token_hex(16)
        cur = con.execute("INSERT INTO users(username,name,dept,is_admin,salt,pw_hash) VALUES (?,?,?,?,?,?)",
                          (username, name, dept, admin, salt, hash_pw(DEMO_PASSWORD, salt)))
        ids.append(cur.lastrowid)
    admin_id, member_ids = ids[0], ids[1:]

    start = datetime.now() - timedelta(days=30)
    step = timedelta(days=30) / (len(POSTS) + len(NOTICES) + 3)
    t = start

    def ts():
        return t.strftime("%Y-%m-%d %H:%M:%S")

    post_ids = []
    for content in POSTS:
        t += step
        cur = con.execute("INSERT INTO posts(author_id,content,created_at) VALUES (?,?,?)",
                          (rnd.choice(member_ids), content, ts()))
        post_ids.append(cur.lastrowid)
    for notice in NOTICES:  # 공지는 운영자 글, 고정 상태
        t += step
        con.execute("INSERT INTO posts(author_id,content,pinned,created_at) VALUES (?,?,1,?)",
                    (admin_id, notice, ts()))
    # 고정되지 않은 일반 운영자 글 하나
    t += step
    con.execute("INSERT INTO posts(author_id,content,created_at) VALUES (?,?,?)",
                (admin_id, "이번 달 우수 사원 추천을 받습니다. 인사팀 게시판을 이용해 주세요.", ts()))

    for pid in post_ids:
        if rnd.random() < 0.55:
            for _ in range(rnd.randint(1, 4)):
                con.execute("INSERT INTO comments(post_id,author_id,content,created_at) VALUES (?,?,?,?)",
                            (pid, rnd.choice(ids), rnd.choice(COMMENTS), ts()))
    # 신고 예시: 한 글에 2건, 다른 글에 1건
    for pid, reporters in ((post_ids[9], member_ids[:2]), (post_ids[40], member_ids[3:4])):
        for uid in reporters:
            con.execute("INSERT OR IGNORE INTO reports(post_id,reporter_id,reason,created_at) VALUES (?,?,?,?)",
                        (pid, uid, rnd.choice(REPORT_REASONS), ts()))
