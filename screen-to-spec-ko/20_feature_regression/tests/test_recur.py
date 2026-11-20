# -*- coding: utf-8 -*-
"""ep097 — 매주 반복 예약의 새 완료 기준 T10~T12 (PRD v2 의 R10 · R11 · R12).
빌더(AI)에게는 주지 않는다. 채점할 때만 tests/test_dod.py 와 함께 _grader/ 로 복사해 돈다.

구현(표 이름 · 저장 구조)을 전제하지 않는다. 만든 예약은 GET /api/reservations?date= 로 날짜마다 다시 읽어 센다.
기본은 PRD v2 의 이름(repeat_weeks · scope=one|following)으로 부른다.
환경 변수 RECUR_ADAPTER(JSON 파일 경로)를 주면 그 앱이 스스로 정한 이름으로 부른다(문서 없이 만든 앱을 '자기 이름' 으로 재는 용도):
  create_path     반복 예약을 만드는 주소 (기본 /api/reservations)
  weeks_field     반복 횟수 칸 이름 (기본 repeat_weeks)
  weeks_mode      "count" 전체 횟수 | "extra" 첫 회 뺀 추가 횟수 | "until" 마지막 날짜(YYYY-MM-DD)를 보냄
  extra_body      같이 보내야 하는 칸 (예: {"repeat": "weekly"})
  cancel_one      한 실행 취소 주소 틀. {res_id} {user} {series_id} 를 쓸 수 있다
  cancel_following 남은 전부 취소 주소 틀. 없으면 null (그 기능이 없는 앱)
  following_is_all true 면 '남은 전부' 가 아니라 '묶음 전체' 를 지우는 앱 (그러면 첫 실행도 사라지는 것을 기대)
  series_field    GET 응답에서 묶음 번호 칸 이름
  bad_weeks       거부돼야 할 값들, ok_weeks 허용돼야 할 큰 값
  strict          true 면 상태 코드를 PRD 대로(201 · 204 · 400 · 403 · 409), false 면 2xx / 4xx 로만 본다
"""
import datetime
import json
import os
import urllib.request

import pytest

from test_dod import DATE, PORT, Server, http

AD = {"create_path": "/api/reservations", "weeks_field": "repeat_weeks", "weeks_mode": "count", "extra_body": {},
      "cancel_one": "/api/reservations/{res_id}?user={user}&scope=one",
      "cancel_following": "/api/reservations/{res_id}?user={user}&scope=following",
      "following_is_all": False, "series_field": "series_id",
      "bad_weeks": [1, 9, 0, "abc"], "ok_weeks": 8, "strict": True}
if os.environ.get("RECUR_ADAPTER"):
    AD.update(json.load(open(os.environ["RECUR_ADAPTER"], encoding="utf-8")))
STRICT = AD["strict"]


def day(k):
    """기준 날짜에서 k 주 뒤 (k=0 이 첫 실행)"""
    d = datetime.date.fromisoformat(DATE) + datetime.timedelta(days=7 * k)
    return d.isoformat()


class QuietServer(Server):
    """test_dod 의 Server 는 서버 출력을 PIPE 로 받고 읽지 않는다. 요청이 많은 이 파일에서는 접속 로그가 버퍼를 채워
    서버가 멈춘다(자가 시험에서 T12 가 시간 초과). 그래서 출력을 버린다. 나머지는 같다."""

    def start(self):
        import glob
        import subprocess
        import sys
        import time
        from test_dod import APP, write_seed
        if not self.target:
            pytest.fail("FastAPI 앱을 찾지 못함")
        write_seed()
        for p in glob.glob(os.path.join(APP, "**", "*.db"), recursive=True):
            try:
                os.remove(p)
            except OSError:
                pass
        env = dict(os.environ, PORT=str(self.port), PYTHONUTF8="1")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", self.target, "--port", str(self.port)],
                                     cwd=APP, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if self.proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(self.base + "/", timeout=1)
                return self
            except Exception:
                time.sleep(0.5)
        self.stop()
        pytest.fail("서버가 뜨지 않음: %s" % self.target)


@pytest.fixture(scope="module")
def srv():
    s = QuietServer(PORT).start()
    yield s
    s.stop()


def ok(st, want):
    return st == want if STRICT else 200 <= st < 300


def refused(st, want):
    return st == want if STRICT else 400 <= st < 500


def on(s, date, room, start, user=None):
    """그 날짜 · 회의실 · 시작 시각의 예약 목록"""
    st, data = http("GET", s.base + "/api/reservations?date=" + date)
    assert st == 200, "GET /api/reservations?date=%s 가 %s" % (date, st)
    return [r for r in data if r.get("room_id") == room and r.get("start") == start and (user is None or r.get("user") == user)]


def single(s, date, room, start, end, user):
    return http("POST", s.base + "/api/reservations", {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def recur(s, room, start, end, user, weeks):
    body = {"room_id": room, "date": DATE, "start": start, "end": end, "user": user}
    body.update(AD["extra_body"])
    if AD["weeks_mode"] == "until":
        body[AD["weeks_field"]] = day(weeks - 1) if isinstance(weeks, int) else weeks
    elif AD["weeks_mode"] == "extra":
        body[AD["weeks_field"]] = weeks - 1 if isinstance(weeks, int) else weeks
    else:
        body[AD["weeks_field"]] = weeks
    return http("POST", s.base + AD["create_path"], body)


def cancel(s, which, rec, user):
    tpl = AD["cancel_" + which]
    if not tpl:
        pytest.fail("이 앱에는 '%s' 취소가 없다" % which)
    url = tpl.format(res_id=rec.get("res_id", rec.get("id")), user=urllib.request.quote(user), series_id=rec.get(AD["series_field"]))
    return http("DELETE", s.base + url)[0]


def test_T10_weekly_repeat_all_or_nothing(srv):
    # 되는 경우: B 회의실 16:00~17:00 를 3주
    st, body = recur(srv, "B", "16:00", "17:00", "박지연", 3)
    assert ok(st, 201), ("3주 반복은 만들어져야 한다", st, body)
    for k in range(3):
        assert len(on(srv, day(k), "B", "16:00", "박지연")) == 1, "%d번째 주(%s)에 한 건이 있어야 한다" % (k + 1, day(k))
    assert on(srv, day(3), "B", "16:00") == [], "3주를 시켰는데 4번째 주에도 생겼다"
    # 안 되는 경우: 둘째 주에 남의 예약이 이미 있다 → 전체 거부, 한 건도 안 생긴다
    st, body = single(srv, day(1), "C", "09:00", "10:00", "최유나")
    assert ok(st, 201), ("준비: 둘째 주에 한 번짜리 예약", st, body)
    st, body = recur(srv, "C", "09:00", "10:00", "박지연", 3)
    assert refused(st, 409), ("둘째 주가 겹치면 반복 전체가 거부돼야 한다", st, body)
    assert on(srv, day(0), "C", "09:00", "박지연") == [], "거부됐는데 첫째 주에 예약이 생겼다"
    assert on(srv, day(2), "C", "09:00", "박지연") == [], "거부됐는데 셋째 주에 예약이 생겼다"
    assert len(on(srv, day(1), "C", "09:00")) == 1, "둘째 주의 원래 예약이 달라졌다"


def test_T11_cancel_one_or_following_owner_only(srv):
    st, body = recur(srv, "A", "16:00", "17:00", "정하늘", 4)
    assert ok(st, 201), ("준비: 4주 반복", st, body)
    occ = [on(srv, day(k), "A", "16:00", "정하늘") for k in range(4)]
    assert all(len(o) == 1 for o in occ), "4주에 한 건씩 있어야 한다: %s" % [len(o) for o in occ]
    # 남이 '남은 전부' 취소 → 거부, 4건 다 남는다
    st = cancel(srv, "following", occ[0][0], "한도윤")
    assert refused(st, 403), ("남의 반복 예약 취소는 거부돼야 한다", st)
    assert [len(on(srv, day(k), "A", "16:00", "정하늘")) for k in range(4)] == [1, 1, 1, 1], "거부됐는데 지워진 실행이 있다"
    # 본인이 둘째 실행만 취소 → 그 하나만 사라진다
    st = cancel(srv, "one", occ[1][0], "정하늘")
    assert ok(st, 204), ("본인의 한 실행 취소", st)
    assert [len(on(srv, day(k), "A", "16:00", "정하늘")) for k in range(4)] == [1, 0, 1, 1], "한 실행만 취소했는데 다른 실행이 달라졌다"
    # 본인이 셋째 실행부터 남은 전부 취소 → 셋째 · 넷째 사라지고 첫째는 남는다
    st = cancel(srv, "following", occ[2][0], "정하늘")
    assert ok(st, 204), ("본인의 남은 전부 취소", st)
    want = [0, 0, 0, 0] if AD["following_is_all"] else [1, 0, 0, 0]
    assert [len(on(srv, day(k), "A", "16:00", "정하늘")) for k in range(4)] == want, "남은 전부 취소 뒤 남은 실행이 기대와 다르다"


def test_T12_repeat_weeks_range(srv):
    for bad in AD["bad_weeks"]:
        st, body = recur(srv, "C", "11:00", "11:30", "한도윤", bad)
        assert refused(st, 400), ("반복 %r 은 거부돼야 한다" % (bad,), st, body)
        assert on(srv, DATE, "C", "11:00") == [], "반복 %r 이 거부됐는데 예약이 생겼다" % (bad,)
    n = AD["ok_weeks"]
    st, body = recur(srv, "C", "11:00", "11:30", "한도윤", n)
    assert ok(st, 201), ("반복 %d 은 허용돼야 한다" % n, st, body)
    assert [len(on(srv, day(k), "C", "11:00", "한도윤")) for k in range(n)] == [1] * n
