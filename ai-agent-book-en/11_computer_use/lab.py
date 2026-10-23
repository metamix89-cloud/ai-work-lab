# -*- coding: utf-8 -*-
"""EN ep11 lab — bonus 2: an agent that operates a screen (book ch.6 'computer use · action space · visual grounding' · experiment 6-9).
English re-run of the Korean ep046 lab. A fake Yummy Tummy Foods back-office page (erp.html, a local file) opened with Playwright; 5 requests; gpt-4.1-mini.
  DOM  element index : a numbered list of the buttons and inputs on screen + the visible text; click / type by number (the book's 'structured element index')
  SOM  set-of-mark   : a screenshot with a red number drawn on each element; click / type by number (picture only, no text list)
  SHOT screenshot    : only the 1280×800 screenshot; click(x, y) by coordinates and keyboard typing (the book's 'pure coordinate prediction')
  RPA  freeze in code: the steps a person checked once, written as Playwright code and replayed (book ch.5 'lock in the success path as RPA')
Graded from the app state in the page (window.APP_STATE) and the final answer. Self-test first: the RPA run must pass all, a do-nothing run must fail all.
Built in from the Korean run: the SOM number is drawn inside the top-left of each element (drawn above the box, it looked attached to the field above).
Parallel: each job launches its own Playwright browser (no shared files); results are written once from the main thread.
Usage: python lab.py selftest · python lab.py DOM,SOM,SHOT 3 results.json"""
import base64, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "file:///" + os.path.join(HERE, "erp.html").replace("\\", "/")
load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = 3
MAX_STEPS = 15
W, H = 1280, 800

TASKS = [
    ("T1", "On the Stock screen, find how many cases of 'Pepperoni Pizza 2-pack' are on hand at Dayton DC, and tell me."),
    ("T2", "On the Purchase Order screen, save a purchase order: supplier Sunrise Supply, item Pizza Sauce, quantity 200 lb, due date 2026-10-28."),
    ("T3", "In Accounts, change ValueMart's contact to Sam Park and the phone to ext. 4417, and save."),
    ("T4", "In the Orders list, find the status of order YT-4410 and tell me."),
    ("T5", "On the Stock screen, find the warehouse where Mac & Cheese Bake has 0 in stock, and tell me its restock date."),
]


def grade(tid, state, answer):
    po, cu = state.get("orders_po", []), state.get("customers", [])
    if tid == "T1":
        return bool(re.search(r"\b320\b", answer))
    if tid == "T2":
        return po == [{"supplier": "Sunrise Supply", "item": "Pizza Sauce", "qty": "200", "due": "2026-10-28"}]
    if tid == "T3":
        v = next((c for c in cu if c["name"] == "ValueMart"), {})
        others_ok = all(c["person"] in ("Dana Choi", "Max Kim") for c in cu if c["name"] != "ValueMart")
        return v.get("person") == "Sam Park" and v.get("tel") == "ext. 4417" and others_ok
    if tid == "T4":
        return "out for delivery" in answer.lower()
    if tid == "T5":
        return "Dayton" in answer and bool(re.search(r"\b11\s*/\s*12\b|November 12|Nov\.? 12", answer))


# ------------- element index (DOM)
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
  return '[Elements]\n' + lines.join('\n') + '\n\n[Visible text]\n' + txt.slice(0, 2500);
}"""

T_DOM = [
    {"type": "function", "function": {"name": "look", "description": "See the current element index and visible text.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "click", "description": "Click the element with this number.", "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}}},
    {"type": "function", "function": {"name": "type", "description": "Clear the input with this number and type text into it.", "parameters": {"type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}}, "required": ["id", "text"]}}},
    {"type": "function", "function": {"name": "done", "description": "Finish and answer the user.", "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}}},
]
T_SHOT = [
    {"type": "function", "function": {"name": "click", "description": f"Click at screen coordinates (x, y). The screen is {W}×{H}.", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}}},
    {"type": "function", "function": {"name": "type_text", "description": "Type text into the focused input (replacing what is there).", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "done", "description": "Finish and answer the user.", "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}}},
]
SYS = ("You operate the Yummy Tummy Foods (a fictional company) back-office screen on behalf of an employee. Use the tools to work the screen and handle the request, "
       "then answer briefly with done. If a save confirmation appears, check it and press 'OK'. Answer only from what is on screen.")


def chat(msgs, tools, log):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, tools=tools, parallel_tool_calls=False)
            break
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


def shot_msg(page, note):
    b = base64.b64encode(page.screenshot()).decode()
    return {"role": "user", "content": [{"type": "text", "text": note}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b, "detail": "high"}}]}


def som_msg(page, note):
    page.evaluate(INDEX_JS)
    page.evaluate(MARK_JS)
    m = shot_msg(page, note)
    page.evaluate(UNMARK_JS)
    return m


def run_agent(method, task):
    tid, req = task
    log = dict(tokens=0, steps=0, actions=[], answer="")
    t0 = time.time()
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome")
        page = br.new_page(viewport={"width": W, "height": H}, locale="en-US")
        page.goto(URL)
        if method == "DOM":
            msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": req + "\n\n" + page.evaluate(INDEX_JS)}]
            tools = T_DOM
        elif method == "SOM":
            msgs = [{"role": "system", "content": SYS + " Each element in the screenshot has a red number. Act by number."},
                    {"role": "user", "content": req}, som_msg(page, "Current screen")]
            tools = [T_DOM[1], T_DOM[2], T_DOM[3]]
        else:
            msgs = [{"role": "system", "content": SYS + f" You see the screen as a {W}×{H} pixel screenshot; coordinates are in that space."},
                    {"role": "user", "content": req}, shot_msg(page, "Current screen")]
            tools = T_SHOT
        for _ in range(MAX_STEPS):
            m = chat(msgs, tools, log)
            log["steps"] += 1
            if not m.tool_calls:
                msgs.append({"role": "assistant", "content": m.content or ""})
                msgs.append({"role": "user", "content": "Keep going with the tools, and call done when you're finished."})
                continue
            msgs.append(m)
            tc = m.tool_calls[0]
            a = json.loads(tc.function.arguments or "{}")
            n = tc.function.name
            log["actions"].append(f"{n}({json.dumps(a)})")
            out = "ok"
            try:
                if n == "done":
                    log["answer"] = a.get("answer", "")
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "content": "finished"})
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
                        page.keyboard.press("Control+A")
                        page.keyboard.type(a.get("text", ""))
                    page.wait_for_timeout(350)
            except Exception as e:
                out = f"failed: {str(e)[:120]}"
                if method == "DOM":
                    out += "\n" + page.evaluate(INDEX_JS)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out if method == "DOM" else ("done" if out == "ok" else out)})
            if method == "SHOT":
                msgs.append(shot_msg(page, "Screen after the action"))
            elif method == "SOM":
                msgs.append(som_msg(page, "Screen after the action"))
        state = page.evaluate("() => window.APP_STATE")
        br.close()
    log["sec"] = round(time.time() - t0, 1)
    return grade(tid, state, log["answer"]), state, log


# ------------- freeze in code (RPA): the steps a person checked once
def rpa(tid, page):
    tab = lambda name: page.click(f'nav button:has-text("{name}")')
    pick = lambda dd, opt: (page.click(f"#{dd} .ddb"), page.click(f'#{dd} .ddo:has-text("{opt}")'))
    if tid in ("T1", "T5"):
        tab("Stock")
        page.fill("#sq", "Pepperoni Pizza 2-pack" if tid == "T1" else "Mac & Cheese Bake")
        page.click("#sbtn")
        rows = page.eval_on_selector_all("#stbl tbody tr", "rs => rs.map(r => Array.from(r.cells).map(c => c.innerText))")
        if tid == "T1":
            return next(r[2] for r in rows if r[1] == "Dayton DC") + " cases (Dayton DC)"
        r = next(r for r in rows if r[2] == "0")
        return f"{r[1]}, restock {r[3]}"
    if tid == "T2":
        tab("Purchase Order")
        pick("ps", "Sunrise Supply")
        pick("pi", "Pizza Sauce")
        page.fill("#pq", "200")
        page.fill("#pd", "2026-10-28")
        page.click("#psave")
        page.click("#mok")
        return page.inner_text("#pmsg")
    if tid == "T3":
        tab("Accounts")
        page.click('[data-ci="0"]')
        page.fill("#cep", "Sam Park")
        page.fill("#cet", "ext. 4417")
        page.click("#cesave")
        page.click("#mok")
        return page.inner_text("#cmsg")
    if tid == "T4":
        tab("Orders")
        for _ in range(10):
            rows = page.eval_on_selector_all("#otbl tbody tr", "rs => rs.map(r => Array.from(r.cells).map(c => c.innerText))")
            hit = next((r for r in rows if r[0] == "YT-4410"), None)
            if hit:
                return hit[3]
            page.click("#onext")
    return ""


def run_rpa(task, noop=False):
    tid = task[0]
    t0 = time.time()
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome")
        page = br.new_page(viewport={"width": W, "height": H})
        page.goto(URL)
        ans = "" if noop else rpa(tid, page)
        state = page.evaluate("() => window.APP_STATE")
        br.close()
    return grade(tid, state, ans), ans, round(time.time() - t0, 2)


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:          # test the grader and the page first
        for t in TASKS:
            ok, ans, sec = run_rpa(t)
            bad, _, _ = run_rpa(t, noop=True)
            print(t[0], "RPA correct →", ok, f"({ans}, {sec}s)", "| do nothing →", bad)
        sys.exit()
    methods = sys.argv[1].split(",") if len(sys.argv) > 1 else ["DOM", "SOM", "SHOT"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS

    def one(j):
        m, t, s = j
        try:
            ok, state, log = run_agent(m, t)
            return dict(method=m, task=t[0], seed=s, ok=ok, answer=log["answer"][:300], steps=log["steps"], tokens=log["tokens"], sec=log["sec"],
                        actions=log["actions"], state=state)
        except Exception as e:
            return dict(method=m, task=t[0], seed=s, error=str(e)[:300])
    jobs = [(m, t, s) for m in methods for t in TASKS for s in range(trials)]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, jobs))
    rp = []
    for t in TASKS:
        ok, ans, sec = run_rpa(t)
        rp.append(dict(method="RPA", task=t[0], seed=0, ok=ok, answer=ans, sec=sec, tokens=0, steps=0))
    with open(os.path.join(HERE, sys.argv[3] if len(sys.argv) > 3 else "results.json"), "w", encoding="utf-8") as f:
        json.dump(res + rp, f, ensure_ascii=False, indent=1)
    for m in methods:
        rs = [r for r in res if r["method"] == m and "error" not in r]
        print(m, "success", sum(r["ok"] for r in rs), "/", len(rs), "|", " ".join(f"{t[0]} {sum(r['ok'] for r in rs if r['task'] == t[0])}" for t in TASKS),
              "| avg steps", round(sum(r["steps"] for r in rs) / max(1, len(rs)), 1), "| tokens", round(sum(r["tokens"] for r in rs) / max(1, len(rs))),
              "| sec", round(sum(r["sec"] for r in rs) / max(1, len(rs)), 1), "| errors", sum(1 for r in res if r["method"] == m and "error" in r))
    print("RPA success", sum(r["ok"] for r in rp), "/ 5 · avg", round(sum(r["sec"] for r in rp) / 5, 2), "s")
