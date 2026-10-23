# -*- coding: utf-8 -*-
"""ep046 실습 — 보너스 2: 화면을 조작하는 에이전트 (원서 6장 '컴퓨터 사용 · 행동 공간 · 시각적 그라운딩' · 실험 6-9 방식).
가나다식품(가상) 업무 시스템 흉내 페이지(erp.html, 로컬 파일)를 Playwright 로 띄우고 요청 5건 처리. gpt-4.1-mini.
  DOM  요소 번호표 : 화면의 버튼 · 입력칸에 번호를 붙인 목록 + 보이는 글을 주고, 번호로 click / type (원서의 '구조화된 요소 색인')
  SOM  번호 그림   : 스크린샷 위에 요소마다 빨간 번호표를 그려 주고 번호로 click / type (원서의 Set-of-Mark, 글자 목록 없이 그림만)
  SHOT 스크린샷   : 1280×800 화면 캡처만 보고 좌표로 click(x,y) / 키보드 입력 (원서의 '순수 좌표 예측')
  RPA  코드로 굳히기: 사람이 한 번 확인한 순서를 Playwright 코드로 적어 다시 실행 (원서 5장 '성공 경로를 RPA 로 확정')
채점: 화면 속 앱 상태(window.APP_STATE)와 최종 답 문장. 채점기는 RPA 정답 실행(전부 통과) · 아무것도 안 한 실행(전부 실패)으로 먼저 시험.
겪은 실수: SOM 첫 실행(results_som.json)은 번호표를 칸 바깥 위쪽에 그려, 세로로 붙은 입력칸에서 아래 칸 번호가 위 칸에 붙어 보였다
  → 번호표를 칸 안쪽 왼쪽 위로 옮겨 다시 실행(results_som2.json). 화면 숫자는 다시 실행한 값.
병렬: 작업마다 Playwright 를 따로 띄운다(공유 파일 없음). 결과 파일은 메인에서 한 번만 쓴다."""
import base64, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HERE, "erp.html").replace("\\", "/")
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = 3
MAX_STEPS = 15
W, H = 1280, 800

TASKS = [
    ("T1", "재고 조회 화면에서 '냉동만두 1kg' 의 이천센터 현재고가 몇 박스인지 찾아서 답해 줘."),
    ("T2", "발주 입력 화면에서 공급사 가나공급, 품목 떡볶이 소스, 수량 200kg, 납기일 2026-10-28 로 발주를 저장해 줘."),
    ("T3", "거래처 관리에서 가나마트의 담당자를 박민호, 연락처를 내선 4417 로 고쳐서 저장해 줘."),
    ("T4", "주문 목록에서 주문번호 GND-4410 의 상태를 찾아서 답해 줘."),
    ("T5", "재고 조회 화면에서 떡볶이 밀키트 재고가 0인 센터를 찾고, 그 센터의 입고 예정일을 답해 줘."),
]


def grade(tid, state, answer):
    po, cu = state.get("orders_po", []), state.get("customers", [])
    if tid == "T1":
        return "320" in answer
    if tid == "T2":
        return po == [{"supplier": "가나공급", "item": "떡볶이 소스", "qty": "200", "due": "2026-10-28"}]
    if tid == "T3":
        g = next((c for c in cu if c["name"] == "가나마트"), {})
        others_ok = all(c["person"] in ("최다라", "김마바") for c in cu if c["name"] != "가나마트")
        return g.get("person") == "박민호" and g.get("tel") == "내선 4417" and others_ok
    if tid == "T4":
        return "배송 중" in answer or "배송중" in answer
    if tid == "T5":
        return "이천" in answer and bool(re.search(r"11\s*/\s*12|11월\s*12일", answer))


# ───────────── 요소 번호표 (DOM)
INDEX_JS = r"""() => {
  document.querySelectorAll('[data-aid]').forEach(e => e.removeAttribute('data-aid'));
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && e.offsetParent !== null; };
  const els = Array.from(document.querySelectorAll('button, input, .ddo, a')).filter(vis);
  const lines = els.map((e, i) => { e.setAttribute('data-aid', i);
    const lab = e.id ? (document.querySelector('label[for="'+e.id+'"]') || {}).textContent : '';
    const kind = e.classList.contains('ddo') ? 'option' : e.tagName.toLowerCase();
    let t = (e.textContent || '').trim();
    if (e.tagName === 'INPUT') t = 'value="' + e.value + '" placeholder="' + (e.placeholder || '') + '"';
    return '[' + i + '] ' + kind + (lab ? ' (' + lab.trim() + ')' : '') + ' ' + t; });
  const txt = Array.from(document.querySelectorAll('section.on h2, section.on table, section.on .msg, section.on .pager span, #modal, #ad'))
    .filter(vis).map(e => e.innerText.trim()).filter(Boolean).join('\n');
  return '[요소]\n' + lines.join('\n') + '\n\n[보이는 글]\n' + txt.slice(0, 2500);
}"""

T_DOM = [
    {"type": "function", "function": {"name": "look", "description": "지금 화면의 요소 번호표와 보이는 글을 본다.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "click", "description": "번호의 요소를 클릭한다.", "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "type", "description": "번호의 입력칸 내용을 지우고 글을 넣는다.", "parameters": {"type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}}, "required": ["id", "text"]}}},
    {"type": "function", "function": {"name": "done", "description": "작업을 끝내고 사용자에게 답한다.", "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}}},
]
T_SHOT = [
    {"type": "function", "function": {"name": "click", "description": f"화면 좌표(x, y)를 클릭한다. 화면은 {W}×{H}.", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}}},
    {"type": "function", "function": {"name": "type_text", "description": "지금 커서가 있는 입력칸에 글을 입력한다(기존 내용은 지우고).", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "done", "description": "작업을 끝내고 사용자에게 답한다.", "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}}},
]
SYS = ("너는 가나다식품(가상 회사) 직원 대신 사내 업무 시스템 화면을 조작하는 에이전트다. 도구로 화면을 조작해 요청을 처리하고, 끝나면 done 으로 짧게 답한다. "
       "저장 확인 창이 뜨면 내용을 확인하고 '확인'을 누른다. 화면 내용만 근거로 답한다.")


def chat(msgs, tools, log):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, tools=tools, parallel_tool_calls=False); break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
    return r.choices[0].message


MARK_JS = r"""() => { document.querySelectorAll('.somk').forEach(e => e.remove());
  document.querySelectorAll('[data-aid]').forEach(e => { const r = e.getBoundingClientRect();
    const b = document.createElement('div'); b.className = 'somk';
    b.style.cssText = 'position:fixed;z-index:99999;pointer-events:none;border:2px solid #e11;left:'+(r.left-1)+'px;top:'+(r.top-1)+'px;width:'+r.width+'px;height:'+r.height+'px';
    const t = document.createElement('div'); t.textContent = e.getAttribute('data-aid');
    t.style.cssText = 'position:absolute;left:0;top:0;background:#e11;color:#fff;font:bold 12px Arial;padding:0 3px;line-height:14px';
    b.appendChild(t); document.body.appendChild(b); }); }"""
UNMARK_JS = "() => document.querySelectorAll('.somk').forEach(e => e.remove())"


def som_msg(page, note):
    page.evaluate(INDEX_JS); page.evaluate(MARK_JS)
    m = shot_msg(page, note)
    page.evaluate(UNMARK_JS)
    return m


def shot_msg(page, note):
    b = base64.b64encode(page.screenshot()).decode()
    return {"role": "user", "content": [{"type": "text", "text": note}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b, "detail": "high"}}]}


def run_agent(method, task):
    tid, req = task
    log = dict(tokens=0, steps=0, actions=[], answer="")
    t0 = time.time()
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome")
        page = br.new_page(viewport={"width": W, "height": H}, locale="ko-KR")
        page.goto(URL)
        if method == "DOM":
            msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": req + "\n\n" + page.evaluate(INDEX_JS)}]
            tools = T_DOM
        elif method == "SOM":
            msgs = [{"role": "system", "content": SYS + " 화면 캡처에 요소마다 빨간 번호표가 붙어 있다. 번호로 조작한다."}, {"role": "user", "content": req}, som_msg(page, "지금 화면")]
            tools = [T_DOM[1], T_DOM[2], T_DOM[3]]
        else:
            msgs = [{"role": "system", "content": SYS + f" 화면은 {W}×{H} 픽셀 캡처로 보인다. 좌표는 그 기준."}, {"role": "user", "content": req}, shot_msg(page, "지금 화면")]
            tools = T_SHOT
        for _ in range(MAX_STEPS):
            m = chat(msgs, tools, log)
            log["steps"] += 1
            if not m.tool_calls:
                msgs.append({"role": "assistant", "content": m.content or ""})
                msgs.append({"role": "user", "content": "도구로 계속 진행하고, 끝났으면 done 을 불러."})
                continue
            msgs.append(m)
            tc = m.tool_calls[0]
            a = json.loads(tc.function.arguments or "{}")
            n = tc.function.name
            log["actions"].append(f"{n}({json.dumps(a, ensure_ascii=False)})")
            out = "ok"
            try:
                if n == "done":
                    log["answer"] = a.get("answer", "")
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": "끝"})
                    break
                if method in ("DOM", "SOM"):
                    if n == "click":
                        page.click(f'[data-aid="{a["id"]}"]', timeout=3000)
                    elif n == "type":
                        page.fill(f'[data-aid="{a["id"]}"]', a.get("text", ""), timeout=3000)
                    page.wait_for_timeout(350)
                    out = page.evaluate(INDEX_JS) if method == "DOM" else "ok"
                else:
                    if n == "click":
                        page.mouse.click(int(a["x"]), int(a["y"]))
                    elif n == "type_text":
                        page.keyboard.press("Control+A"); page.keyboard.type(a.get("text", ""))
                    page.wait_for_timeout(350)
            except Exception as e:
                out = f"실패: {str(e)[:120]}"
                if method == "DOM":
                    out += "\n" + page.evaluate(INDEX_JS)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out if method == "DOM" else ("실행함" if out == "ok" else out)})
            if method == "SHOT":
                msgs.append(shot_msg(page, "실행 뒤 화면"))
            elif method == "SOM":
                msgs.append(som_msg(page, "실행 뒤 화면"))
        state = page.evaluate("() => window.APP_STATE")
        log["final_png"] = base64.b64encode(page.screenshot()).decode() if False else ""
        br.close()
    log["sec"] = round(time.time() - t0, 1)
    return grade(tid, state, log["answer"]), state, log


# ───────────── 코드로 굳히기 (RPA): 사람이 확인한 순서
def rpa(tid, page):
    tab = lambda name: page.click(f'nav button:has-text("{name}")')
    pick = lambda dd, opt: (page.click(f"#{dd} .ddb"), page.click(f'#{dd} .ddo:has-text("{opt}")'))
    if tid in ("T1", "T5"):
        tab("재고 조회"); page.fill("#sq", "냉동만두 1kg" if tid == "T1" else "떡볶이 밀키트"); page.click("#sbtn")
        rows = page.eval_on_selector_all("#stbl tbody tr", "rs => rs.map(r => Array.from(r.cells).map(c => c.innerText))")
        if tid == "T1":
            return next(r[2] for r in rows if r[1] == "이천센터") + "박스 (이천센터)"
        r = next(r for r in rows if r[2] == "0")
        return f"{r[1]} 입고 예정 {r[3]}"
    if tid == "T2":
        tab("발주 입력"); pick("ps", "가나공급"); pick("pi", "떡볶이 소스"); page.fill("#pq", "200"); page.fill("#pd", "2026-10-28")
        page.click("#psave"); page.click("#mok"); return page.inner_text("#pmsg")
    if tid == "T3":
        tab("거래처 관리"); page.click('[data-ci="0"]'); page.fill("#cep", "박민호"); page.fill("#cet", "내선 4417"); page.click("#cesave"); page.click("#mok")
        return page.inner_text("#cmsg")
    if tid == "T4":
        tab("주문 목록")
        for _ in range(10):
            rows = page.eval_on_selector_all("#otbl tbody tr", "rs => rs.map(r => Array.from(r.cells).map(c => c.innerText))")
            hit = next((r for r in rows if r[0] == "GND-4410"), None)
            if hit:
                return hit[3]
            page.click("#onext")
    return ""


def run_rpa(task, noop=False):
    tid = task[0]
    t0 = time.time()
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome"); page = br.new_page(viewport={"width": W, "height": H}); page.goto(URL)
        ans = "" if noop else rpa(tid, page)
        state = page.evaluate("() => window.APP_STATE"); br.close()
    return grade(tid, state, ans), ans, round(time.time() - t0, 2)


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:          # 채점기 · 화면 먼저 시험
        for t in TASKS:
            ok, ans, sec = run_rpa(t); bad, _, _ = run_rpa(t, noop=True)
            print(t[0], "RPA 정답 →", ok, f"({ans}, {sec}s)", "| 아무것도 안 함 →", bad)
        sys.exit()
    methods = sys.argv[1].split(",") if len(sys.argv) > 1 else ["DOM", "SHOT"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    jobs = [(m, t, s) for m in methods for t in TASKS for s in range(trials)]
    def one(j):
        m, t, s = j
        try:
            ok, state, log = run_agent(m, t)
            return dict(method=m, task=t[0], seed=s, ok=ok, answer=log["answer"][:300], steps=log["steps"], tokens=log["tokens"], sec=log["sec"],
                        actions=log["actions"], state=state)
        except Exception as e:
            return dict(method=m, task=t[0], seed=s, error=str(e)[:300])
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, jobs))
    rp = [dict(method="RPA", task=t[0], seed=0, ok=run_rpa(t)[0], sec=run_rpa(t)[2], tokens=0, steps=0) for t in TASKS]
    json.dump(res + rp, open(os.path.join(HERE, sys.argv[3] if len(sys.argv) > 3 else "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for m in methods:
        rs = [r for r in res if r["method"] == m and "error" not in r]
        print(m, "성공", sum(r["ok"] for r in rs), "/", len(rs), "|", " ".join(f"{t[0]} {sum(r['ok'] for r in rs if r['task'] == t[0])}" for t in TASKS),
              "| 평균 단계", round(sum(r["steps"] for r in rs) / max(1, len(rs)), 1), "| 토큰", round(sum(r["tokens"] for r in rs) / max(1, len(rs))),
              "| 초", round(sum(r["sec"] for r in rs) / max(1, len(rs)), 1), "| 오류", sum(1 for r in res if r["method"] == m and "error" in r))
    print("RPA 성공", sum(r["ok"] for r in rp), "/ 5 · 평균", round(sum(r["sec"] for r in rp) / 5, 2), "초")
