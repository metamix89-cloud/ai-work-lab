# -*- coding: utf-8 -*-
"""ep097 — 기존 테스트 9개가 보지 않는 자리에서 '원래 동작' 이 바뀌었나.
바탕 앱(base/)과 각 실행에 **기존 API 만** 쓰는 같은 요청을 차례로 보내고(반복 칸은 안 쓴다) 상태 코드 · 응답 칸 이름을 나란히 비교한다.
고정 데이터는 tests/test_dod.py 의 것을 그대로 쓴다. 서버는 앱마다 새로 띄운다.
사용: python _scratch/s2s/20_feature_regression/behavior_probe.py [--only=M1_1]   → behavior.json (+ summary.json 의 behavior_changed)"""
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "tests"))
from port_block import PortBlock   # noqa: E402
import test_dod   # noqa: E402

D = test_dod.DATE
Q = urllib.request.quote
# (이름, 방법, 주소, 본문) — 위에서 아래로 차례로 보낸다. 앞 요청이 만든 예약을 뒤 요청이 쓴다.
CASES = [
    ("한 번 예약", "POST", "/api/reservations", {"room_id": "C", "date": D, "start": "09:00", "end": "09:30", "user": "박지연"}),
    ("그 날 목록", "GET", "/api/reservations?date=" + D, None),
    ("날짜가 글자(내일)", "POST", "/api/reservations", {"room_id": "C", "date": "내일", "start": "10:00", "end": "10:30", "user": "박지연"}),
    ("없는 날짜(13월 45일)", "POST", "/api/reservations", {"room_id": "C", "date": "2026-13-45", "start": "10:00", "end": "10:30", "user": "박지연"}),
    ("날짜 형식 다름(2026/11/03)", "POST", "/api/reservations", {"room_id": "C", "date": "2026/11/03", "start": "12:00", "end": "12:30", "user": "박지연"}),
    ("빈 사용자", "POST", "/api/reservations", {"room_id": "C", "date": D, "start": "13:00", "end": "13:30", "user": ""}),
    ("없는 회의실", "POST", "/api/reservations", {"room_id": "Z", "date": D, "start": "13:00", "end": "13:30", "user": "박지연"}),
    ("명단에 없는 사람", "POST", "/api/reservations", {"room_id": "C", "date": D, "start": "13:30", "end": "14:00", "user": "홍길동"}),
    ("겹침", "POST", "/api/reservations", {"room_id": "A", "date": D, "start": "10:30", "end": "11:30", "user": "박지연"}),
    ("3시간", "POST", "/api/reservations", {"room_id": "C", "date": D, "start": "12:00", "end": "15:00", "user": "박지연"}),
    ("남의 예약 취소", "DELETE", "/api/reservations/1?user=" + Q("박지연"), None),
    ("사용자 없이 취소", "DELETE", "/api/reservations/1", None),
    ("본인 취소", "DELETE", "/api/reservations/1?user=" + Q("김민수"), None),
    ("없는 예약 취소", "DELETE", "/api/reservations/9999?user=" + Q("김민수"), None),
    ("날짜 없이 목록", "GET", "/api/reservations", None),
    ("회의실 목록", "GET", "/api/rooms", None),
    ("사용자 목록", "GET", "/api/users", None),
]


def shape(body):
    if isinstance(body, dict):
        return "{" + ",".join(sorted(body)) + "}"
    if isinstance(body, list):
        return "[%s]" % (shape(body[0]) if body else "")
    return type(body).__name__


def run_app(d, port):
    test_dod.APP = d
    target, _ = test_dod.find_app_target()
    test_dod.write_seed()
    for p in glob.glob(os.path.join(d, "**", "*.db"), recursive=True):
        try:
            os.remove(p)
        except OSError:
            pass
    pr = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--port", str(port)], cwd=d,
                          env=dict(os.environ, PORT=str(port), PYTHONUTF8="1"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    out = {}
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        for name, method, url, body in CASES:
            st, data = test_dod.http(method, base + url, body)
            detail = data.get("detail") if isinstance(data, dict) and st >= 400 else None
            out[name] = {"status": st, "shape": shape(data) if st < 400 else "", "detail": detail if isinstance(detail, str) else None}
    finally:
        pr.kill()
        pr.wait()
        test_dod.restore_seed()
    return out


def main():
    only = next((set(a.split("=", 1)[1].split(",")) for a in sys.argv[1:] if a.startswith("--only=")), None)
    out_path, sum_path = os.path.join(HERE, "behavior.json"), os.path.join(HERE, "summary.json")
    allres = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
    summary = json.load(open(sum_path, encoding="utf-8")) if os.path.exists(sum_path) else {}
    with PortBlock(9400) as pb:
        ref = run_app(os.path.join(HERE, "base"), pb.port)
        allres["base"] = ref
        for d in sorted(glob.glob(os.path.join(HERE, "runs", "*"))):
            name = os.path.basename(d)
            if only and name not in only:
                continue
            got = run_app(d, pb.port + 1)
            allres[name] = got
            status_changed = [c for c in ref if got[c]["status"] != ref[c]["status"]]
            shape_changed = [c for c in ref if got[c]["status"] == ref[c]["status"] and got[c]["shape"] != ref[c]["shape"]]
            text_changed = [c for c in ref if got[c]["status"] == ref[c]["status"] and got[c]["detail"] != ref[c]["detail"]]
            summary.setdefault(name, {}).update(behavior_status_changed=status_changed, behavior_shape_changed=shape_changed,
                                                behavior_text_changed=text_changed)
            print("%s 상태 코드가 달라진 요청 %d · 응답 칸이 달라진 요청 %d · 거부 문구가 달라진 요청 %d" % (
                name, len(status_changed), len(shape_changed), len(text_changed)))
            for c in status_changed:
                print("    [코드] %s: %s → %s %s" % (c, ref[c]["status"], got[c]["status"], got[c]["detail"] or ""))
            for c in shape_changed:
                print("    [칸]   %s: %s → %s" % (c, ref[c]["shape"], got[c]["shape"]))
            for c in text_changed:
                print("    [문구] %s: %s → %s" % (c, ref[c]["detail"], got[c]["detail"]))
    json.dump(allres, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(dict(sorted(summary.items())), open(sum_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("바탕 앱:", {c: v["status"] for c, v in ref.items()})


if __name__ == "__main__":
    main()
