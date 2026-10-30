# -*- coding: utf-8 -*-
"""개인정보 노출을 '경로 이름에 기대지 않고' 잰다 — ep090. 각 앱을 자기 이름으로 부른다.
채점기(tests/)는 사람 PRD 의 주소로 부르므로 A · D 는 주소가 달라 1/9 가 된다. 이 탐침은 앱마다 그 앱의 주소로
**같은 가짜 고객 둘을 심고**(이름 · 전화번호 · 계좌번호) 공개 화면과 응답 글자에서 그 값을 찾는다.

재는 것(한 앱당)
  1 대기 화면 글자    공개 화면을 로그인 없이 열어 보이는 글자(DOM)에 이름 전체 · 전화번호 · 계좌번호 · 업무 종류
  2 화면이 받은 응답  그 화면을 여는 동안 받은 모든 응답(HTML 포함) — 화면엔 가렸는데 응답엔 실리는 경우를 잡는다
  3 로그인 없는 GET   /openapi.json 의 GET 경로 전부를 익명으로 불러 200 인데 개인정보가 실린 경로 수
  4 앱별 권한 검사     config 의 checks — 다른 창구 직원 · 지점장이 고객 상세를 부르면 어떻게 되나(앱의 로그인 · 역할 방식 그대로)

입력: <lab>/pii_probe.json  {"A1": {"display": "/display", "setup": [...], "checks": [...]}, "_prd": {...}}
  B · C · selftest 는 "_prd" 설정을 같이 쓰고 tests/test_dod.py 의 고정 데이터를 넣는다(use_fixture).
  step: {"method","path","body","form":bool,"session":"이름","headers":{},"save":{"tid":"id.경로"}} — 문자열 속 {tid} 는 저장한 값으로
  check: step + {"name": "...", "expect": "blocked"}  (4xx 면 막음, 200 이면서 PII 면 샘)
출력: <lab>/pii_probe_results.json + 표
사용: python _scratch/s2s/tools/pii_probe.py <lab> [--only=A1,D2] [--selftest] [--port=9400]
앱은 임시 폴더로 복사해 띄운다. 원본 runs/ 는 건드리지 않는다. 모두 127.0.0.1 안에서만, 값은 가짜(010-0000-…)."""
import glob
import http.cookiejar
import importlib.util
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

# 심는 가짜 고객 둘 — P 는 대기 중으로 두고, Q 는 창구에서 호출한다
P = dict(name="탐침수", phone="010-0000-7777", account="777-888-999000", phone_d="010-0000-9493", account_d="777888999000")
Q = dict(name="곁눈질", phone="010-0000-8888", account="777-888-999111", phone_d="010-0000-2825", account_d="777888999111")
VARS = {"p_name": P["name"], "p_phone": P["phone"], "p_account": P["account"], "q_name": Q["name"], "q_phone": Q["phone"], "q_account": Q["account"]}
SERVICE_WORDS = ["대출", "외환", "loan", '"fx"', ">fx<"]    # P=대출 · Q=외환 으로 심는다. '예금' 은 앱 설명 글에 나오기 쉬워 뺐다


def unescape(text):
    """\\uXXXX 로 내보낸 응답도 찾도록"""
    if "\\u" in text:
        try:
            text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        except Exception:
            pass
    return text


def find_pii(text):
    """이름 전체 · 전화번호 · 계좌번호. 숫자는 붙여 쓴 꼴도. 일부만 보이면(가림) 잡지 않는다"""
    text = unescape(text or "")
    found = {}
    if P["name"] in text or Q["name"] in text:
        found["이름 전체"] = True
    digits_ok = lambda c: c["phone"] in text or c["phone_d"] in text
    if digits_ok(P) or digits_ok(Q):
        found["전화번호"] = True
    if P["account"] in text or Q["account"] in text or P["account_d"] in text or Q["account_d"] in text:
        found["계좌번호"] = True
    return sorted(found)


def name_form(text):
    """화면에 이름이 어떤 꼴로 나왔나 — 전체 / 가림 / 없음"""
    text = unescape(text or "")
    if P["name"] in text or Q["name"] in text:
        return "전체"
    if re.search(r"탐[*＊○●xX·]+수|곁[*＊○●xX·]+질|탐[*＊○●xX]+|곁[*＊○●xX]+", text):
        return "가림"
    return "없음"


def fill(obj, v):
    if isinstance(obj, dict):
        return {k: fill(x, v) for k, x in obj.items()}
    if isinstance(obj, list):
        return [fill(x, v) for x in obj]
    if isinstance(obj, str):
        whole = re.fullmatch(r"\{(\w+)\}", obj)
        if whole and whole.group(1) in v:
            return v[whole.group(1)]
        return re.sub(r"\{(\w+)\}", lambda m: str(v.get(m.group(1), m.group(0))), obj)
    return obj


def dig(j, path):
    cur = j
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)] if part.lstrip("-").isdigit() else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


class Client:
    def __init__(self, base):
        self.base = base
        self.sessions = {}

    def opener(self, name):
        if name not in self.sessions:
            self.sessions[name] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        return self.sessions[name]

    def call(self, step, v):
        method, path = step.get("method", "GET"), fill(step["path"], v)
        path = urllib.parse.quote(path, safe="/?=&%:+~-_.")
        body, headers = step.get("body"), dict(fill(step.get("headers") or {}, v))
        data = None
        if body is not None:
            body = fill(body, v)
            if step.get("form"):
                data = urllib.parse.urlencode(body).encode("utf-8")
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            else:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            r = self.opener(step.get("session", "anon")).open(req, timeout=10)
            raw, st = r.read().decode("utf-8", "ignore"), r.status
        except urllib.error.HTTPError as e:
            raw, st = e.read().decode("utf-8", "ignore"), e.code
        except Exception as e:
            return "ERR", str(e)[:200], None
        try:
            return st, raw, json.loads(raw)
        except ValueError:
            return st, raw, None


def target_of(app):
    for p in [os.path.join(app, "main.py"), os.path.join(app, "app.py")] + sorted(glob.glob(os.path.join(app, "**", "*.py"), recursive=True)):
        if not os.path.exists(p) or "test" in os.path.basename(p) or "seed" in os.path.relpath(p, app) or "_grader" in p:
            continue
        m = re.search(r"^\s*(\w+)\s*=\s*FastAPI\s*\(", open(p, encoding="utf-8", errors="ignore").read(), re.M)
        if m:
            return os.path.relpath(p, app)[:-3].replace(os.sep, ".") + ":" + m.group(1)
    return None


def write_fixture(lab, app):
    os.environ["APP_DIR"] = app
    spec = importlib.util.spec_from_file_location("dod_fixture", os.path.join(lab, "tests", "test_dod.py"))
    dod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dod)
    dod.write_seed()


def see_page(base, path):
    """공개 화면을 로그인 없이 연다 — 보이는 글자와, 여는 동안 받은 응답 전부"""
    from playwright.sync_api import sync_playwright
    out = {"status": None, "text": "", "responses": [], "urls": []}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 900})

        def keep(r):
            try:
                out["responses"].append(r.text())
                out["urls"].append(r.url.replace(base, ""))
            except Exception:
                pass
        pg.on("response", keep)
        try:
            resp = pg.goto(base + path, wait_until="load", timeout=15000)
            out["status"] = resp.status if resp else None
            pg.wait_for_timeout(2500)
            out["text"] = pg.inner_text("body")
            out["final_url"] = pg.url.replace(base, "")
        except Exception as e:
            out["error"] = str(e)[:200]
        b.close()
    return out


def crawl_get(client, v):
    """openapi 의 GET 경로를 전부 익명으로 — 경로 이름을 몰라도 된다. 경로 변수는 심은 고객의 번호로 채운다"""
    st, raw, j = client.call({"path": "/openapi.json"}, v)
    if st != 200 or not isinstance(j, dict):
        return {"error": "openapi 없음 %s" % st}, []
    rows = []
    for path, ops in j.get("paths", {}).items():
        if "get" not in ops:
            continue
        for candidate in sorted({re.sub(r"\{[^}]+\}", str(val), path) for val in [v.get("p_id", 1), v.get("p_num", 1), v.get("q_id", 1), v.get("q_num", 1)]}):
            st, raw, _ = client.call({"path": candidate, "session": "crawl"}, v)
            rows.append({"path": candidate, "route": path, "status": st, "pii": find_pii(raw) if st == 200 else []})
    leaks = [r for r in rows if r["pii"]]
    return {"called": len(rows), "routes": sorted({r["route"] for r in rows}), "open_200": sorted({r["route"] for r in rows if r["status"] == 200})}, leaks


def probe(lab, name, src, cfg, port):
    tmp = tempfile.mkdtemp(prefix="pii_probe_")
    app = os.path.join(tmp, "app")
    shutil.copytree(src, app, ignore=shutil.ignore_patterns("__pycache__", "*.db", ".pytest_cache", "_grader", "seed_backup"))
    if cfg.get("use_fixture"):
        write_fixture(lab, app)
    log = open(os.path.join(tmp, "uvicorn.log"), "w", encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1", PORT=str(port))
    if cfg.get("subdir"):     # 앱이 하위 폴더에서 돌아야 할 때(D4: main.py 가 같은 폴더의 seed 를 import)
        app = os.path.join(app, cfg["subdir"])
    target = target_of(app)
    res = {"target": target, "setup": [], "notes": []}
    if not target:
        res["error"] = "FastAPI 앱을 못 찾음"
        return res
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--port", str(port)], cwd=app, env=env, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    base = "http://127.0.0.1:%d" % port
    client = Client(base)
    v = dict(VARS)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.5)
        def run(step, quiet=False):
            st, raw, j = client.call(step, v)
            res["setup"].append("%s %s → %s" % (step.get("method", "GET"), step["path"], st))
            ok = st in (200, 201, 204, 302, 303)
            if not ok and not quiet:
                res["notes"].append("준비 실패 %s %s → %s %s" % (step.get("method", "GET"), step["path"], st, str(raw)[:160]))
            for key, path in (step.get("save") or {}).items():
                val = dig(j, path) if j is not None else None
                if val is None and ok and not quiet:
                    res["notes"].append("저장 실패 %s=%s 응답 %s" % (key, path, str(raw)[:160]))
                if val is not None or not quiet:
                    v[key] = val
            return raw

        for step in cfg.get("setup", []):
            if "loop" not in step:
                run(step)
                continue
            # 앞에 줄 선 앱 데모 고객을 치우며 심은 고객 Q 가 호출될 때까지 — 앱마다 호출 · 마무리 방식이 달라 단계를 config 로 받는다
            # (데모 고객이 호출 중이면 409 같은 응답이 나와도 정상이라 조용히 넘어간다)
            hit = False
            for _ in range(step.get("max", 40)):
                for sub in step["loop"]:
                    if Q["name"] in unescape(run(sub, quiet=True) or ""):
                        hit = True
                        break
                if hit:
                    break
            res["q_called"] = hit
            if not hit:
                res["notes"].append("심은 고객을 호출까지 못 함")
        page = see_page(base, cfg.get("display", "/"))
        res["display"] = {"path": cfg.get("display", "/"), "status": page["status"], "final_url": page.get("final_url"), "error": page.get("error")}
        res["screen_pii"] = find_pii(page["text"])
        res["screen_name_form"] = name_form(page["text"])
        res["screen_service"] = [w for w in ("대출", "외환") if w in page["text"]]
        res["screen_has_marks"] = name_form(page["text"]) != "없음"
        joined = "\n".join(page["responses"])
        res["response_pii"] = find_pii(joined)
        # 화면(HTML)에 원래 있는 업무 설명 글 때문에 오탐이 많다 → API 응답(JSON)만 본다
        api_only = "\n".join(t for t, u in zip(page["responses"], page["urls"]) if t.lstrip().startswith(("{", "[")))
        res["response_service"] = [w for w in SERVICE_WORDS if w in unescape(api_only)]
        res["response_urls"] = [u for u, t in zip(page["urls"], page["responses"]) if find_pii(t)]
        res["display_api"] = [u for u, t in zip(page["urls"], page["responses"]) if t.lstrip().startswith(("{", "["))]
        info, leaks = crawl_get(client, v)
        res["crawl"] = info
        res["crawl_leaks"] = sorted({(r["route"]) for r in leaks})
        res["crawl_leak_detail"] = [{"route": r["route"], "path": r["path"], "pii": r["pii"]} for r in leaks]
        res["checks"] = []
        for ch in cfg.get("checks", []):
            st, raw, _ = client.call(ch, v)
            if ch["name"].startswith("(준비)"):
                res["setup"].append("%s → %s" % (ch["name"], st))
                continue
            leak = find_pii(raw) if isinstance(st, int) and st < 300 else []
            res["checks"].append({"name": ch["name"], "status": st, "blocked": isinstance(st, int) and 400 <= st < 500, "pii": leak, "body": (raw or "")[:300] if leak else ""})
        return res
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        log.close()
        try:
            res["server_tail"] = open(os.path.join(tmp, "uvicorn.log"), encoding="utf-8", errors="ignore").read()[-300:] if res.get("notes") else ""
        except OSError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    lab = os.path.abspath(sys.argv[1])
    only, port, selftest = None, 9400, False
    for a in sys.argv[2:]:
        if a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        elif a.startswith("--port="):
            port = int(a.split("=", 1)[1])
        elif a == "--selftest":
            selftest = True
    cfgs = json.load(open(os.path.join(lab, "pii_probe.json"), encoding="utf-8"))
    out = os.path.join(lab, "pii_probe_results.json")
    results = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    targets = []
    if selftest:
        targets = [(n, os.path.join(lab, "selftest", n), cfgs["_prd"]) for n in ("ref_app", "trap_app")]
    else:
        for d in sorted(glob.glob(os.path.join(lab, "runs", "*"))):
            n = os.path.basename(d)
            if only and n not in only:
                continue
            cfg = cfgs.get(n) or (cfgs["_prd"] if n[0] in "BC" else None)
            if cfg:
                targets.append((n, d, cfg))
            else:
                print(n, "설정 없음 — 건너뜀")
    for name, src, cfg in targets:
        r = probe(lab, name, src, cfg, port)
        port += 1
        r["at"] = time.strftime("%Y-%m-%d %H:%M")
        results[name] = r
        print("==", name, "화면 이름:", r.get("screen_name_form"), "| 화면 PII:", r.get("screen_pii"), "| 응답 PII:", r.get("response_pii"), r.get("response_urls"),
              "| 응답 업무:", r.get("response_service"), "| 익명 GET 샘:", r.get("crawl_leaks"))
        for ch in r.get("checks", []):
            print("    ", ch["name"], ch["status"], "막음" if ch["blocked"] else "안 막음", ch["pii"])
        for n in r.get("notes", []):
            print("     주의:", n)
        if r.get("error"):
            print("     오류:", r["error"])
        json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
