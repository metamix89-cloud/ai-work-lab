# -*- coding: utf-8 -*-
"""앱을 '자기 문서의 이름'으로 불러 규칙이 실제로 도는지 본다 — ep088 공정성 확인.
채점기(tests/)는 사람 PRD 의 이름으로 부르므로, 낮은 점수가 '앱이 고장' 인지 '이름이 다름' 인지 이걸로 가른다.
사용: python _scratch/s2s/tools/own_contract_probe.py <lab_dir> [--only=P2_1,P2_2] [--port=9300]
입력: <lab_dir>/own_contract.json  {"P2_1": {"style": ..., ...}}  → 출력: <lab_dir>/own_contract_results.json (앱별 5항목)
항목: 겹침 거절 · 맞닿음 허용 · 시간대 밖 거절 · 남의 예약 취소 거절 · 본인 취소 허용
시각: 오늘 17:00 · 17:30 칸을 쓴다(지난 시간을 막는 앱이 많아 그 전에 돌려야 한다).
앱은 임시 폴더로 복사해 띄우고 DB 는 지운다. 원본 runs/ 는 건드리지 않는다."""
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
SLOT_A, SLOT_B = "17:30", "17:00"   # A = 처음 잡는 칸, B = 바로 앞에 맞닿는 칸
OUT_OF_RANGE = "18:00"
SLOT_INT = {"17:00": 16, "17:30": 17, "18:00": 18}


def call(base, method, path, body=None, headers=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    h = dict(headers or {})
    if data:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(base + "/" + path, data=data, method=method, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=8)
        raw, st = r.read().decode("utf-8"), r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read().decode("utf-8", "ignore"), e.code
    try:
        return st, json.loads(raw) if raw else None
    except ValueError:
        return st, raw


def end_of(slot):
    h, m = map(int, slot.split(":"))
    t = h * 60 + m + 30
    return "%02d:%02d" % (t // 60, t % 60)


def make_body(cfg, room, user, slot):
    """앱마다 다른 몸체 — cfg['style']: slot_str(칸 시작 글자) · slot_int(칸 번호) · range_str(시작 · 끝 글자)"""
    today = datetime.date.today().isoformat()
    b = {cfg.get("room_key", "room_id"): room}
    if cfg.get("user_in_body", True):
        b[cfg.get("user_key", "user_id")] = user
    style = cfg["style"]
    if style == "slot_str":
        b[cfg.get("slot_key", "slot_start")] = slot
    elif style == "slot_int":
        s = SLOT_INT[slot]
        b[cfg.get("start_key", "start_slot")] = s
        b[cfg.get("end_key", "end_slot")] = s + 1
    elif style == "slot_count":   # 시작 칸 번호 + 칸 수 (A3)
        b[cfg.get("start_key", "start_slot")] = SLOT_INT[slot]
        b[cfg.get("count_key", "slots")] = 1
    elif style == "range_str":
        b[cfg.get("start_key", "start_time")] = slot
        b[cfg.get("end_key", "end_time")] = end_of(slot)
    if cfg.get("date_key"):
        b[cfg["date_key"]] = today
    if cfg.get("title"):
        b["title"] = "점검"
    return b


def uheaders(cfg, user):
    if not cfg.get("user_header"):
        return {}
    return {cfg["user_header"]: urllib.parse.quote(str(user)) if cfg.get("header_quote") else str(user)}


def cancel(cfg, base, rid, user):
    kind = cfg["cancel"]
    path = cfg.get("cancel_path", cfg["path"] + "/{id}").replace("{id}", str(rid))
    if kind == "delete_query":
        return call(base, "DELETE", path + "?%s=%s" % (cfg.get("user_key", "user_id"), urllib.parse.quote(str(user))))
    if kind == "post_body":
        return call(base, "POST", path, {cfg.get("user_key", "user_id"): user})
    if kind == "post_header":
        return call(base, "POST", path, {}, uheaders(cfg, user))
    if kind == "delete_header":
        return call(base, "DELETE", path, None, uheaders(cfg, user))
    raise SystemExit("cancel 종류 모름: " + kind)


def find_id(resp, cfg):
    if isinstance(resp, dict):
        for k in [cfg.get("id_key")] + ["id", "reservation_id", "booking_id", "rsv_id", "res_id"]:
            if k and k in resp:
                return resp[k]
        for v in resp.values():
            if isinstance(v, dict):
                r = find_id(v, cfg)
                if r is not None:
                    return r
    return None


def target_of(app):
    for p in [os.path.join(app, "main.py"), os.path.join(app, "app.py")] + sorted(glob.glob(os.path.join(app, "**", "*.py"), recursive=True)):
        if not os.path.exists(p) or "test" in os.path.basename(p):
            continue
        m = re.search(r"^\s*(\w+)\s*=\s*FastAPI\s*\(", open(p, encoding="utf-8", errors="ignore").read(), re.M)
        if m:
            return os.path.relpath(p, app)[:-3].replace(os.sep, ".") + ":" + m.group(1)
    return None


def probe(name, src, cfg, port):
    tmp = tempfile.mkdtemp(prefix="own_probe_")
    app = os.path.join(tmp, "app")
    shutil.copytree(src, app, ignore=shutil.ignore_patterns("__pycache__", "*.db", ".pytest_cache", "_grader", "seed_backup"))
    log_path = os.path.join(tmp, "uvicorn.log")
    log = open(log_path, "w", encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1", PORT=str(port))
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", target_of(app), "--port", str(port)], cwd=app, env=env, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    base = "http://127.0.0.1:%d" % port
    res = {"checks": {}, "notes": []}
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.5)
        path, u1, u2 = cfg["path"], cfg.get("user_a", 1), cfg.get("user_b", 2)
        # 첫 예약 — 데모 예약과 부딪치면 다른 방으로
        rid, room = None, None
        for r in cfg.get("rooms", [1, 2, 3]):
            st, resp = call(base, "POST", path, make_body(cfg, r, u1, SLOT_A), uheaders(cfg, u1))
            if st in (200, 201):
                rid, room = find_id(resp, cfg), r
                break
            res["notes"].append("첫 예약 방%s → %s %s" % (r, st, str(resp)[:120]))
        if room is None:
            res["error"] = "첫 예약을 못 만듦"
            return res
        st, _ = call(base, "POST", path, make_body(cfg, room, u2, SLOT_A), uheaders(cfg, u2))
        res["checks"]["겹침 거절"] = (st, 400 <= st < 500)
        st, _ = call(base, "POST", path, make_body(cfg, room, u2, SLOT_B), uheaders(cfg, u2))
        res["checks"]["맞닿음 허용"] = (st, st in (200, 201))
        st, _ = call(base, "POST", path, make_body(cfg, room, u2, OUT_OF_RANGE), uheaders(cfg, u2))
        res["checks"]["시간대 밖 거절"] = (st, 400 <= st < 500)
        if rid is None:
            res["notes"].append("응답에서 예약 번호를 못 찾음")
        else:
            st, _ = cancel(cfg, base, rid, u2)
            res["checks"]["남의 예약 취소 거절"] = (st, 400 <= st < 500)
            st, _ = cancel(cfg, base, rid, u1)
            res["checks"]["본인 취소 허용"] = (st, st in (200, 204))
        return res
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    lab = os.path.abspath(sys.argv[1])
    only, port = None, 9300
    for a in sys.argv[2:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        elif a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    cfgs = json.load(open(os.path.join(lab, "own_contract.json"), encoding="utf-8"))
    out = os.path.join(lab, "own_contract_results.json")
    results = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    print("지금", time.strftime("%H:%M"), "(17:00 칸이 미래여야 함)")
    for name, cfg in cfgs.items():
        if only and name not in only:
            continue
        r = probe(name, os.path.join(lab, "runs", name), cfg, port)
        port += 1
        r["at"] = time.strftime("%Y-%m-%d %H:%M")
        results[name] = r
        ok = sum(1 for v in r["checks"].values() if v[1])
        print(name, "%d/%d" % (ok, len(r["checks"])), r["checks"], r.get("error", ""), r["notes"])
        json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
