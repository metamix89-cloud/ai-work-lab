const $ = (s, r = document) => r.querySelector(s);
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}
async function api(path, opts = {}, pin) {
  const headers = {'Content-Type': 'application/json'};
  if (pin) headers['X-Staff-PIN'] = pin;
  const r = await fetch(path, {...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(typeof data.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다.'); e.status = r.status; throw e; }
  return data;
}
function msg(el, text, ok) { el.className = 'msg ' + (ok ? 'ok' : 'err'); el.textContent = text; }
function pinFor(key, label) {
  let p = sessionStorage.getItem(key);
  if (!p) { p = prompt(label + ' PIN을 입력하세요'); if (p) sessionStorage.setItem(key, p); }
  return p;
}
const hhmm = s => s ? s.slice(11, 16) : '-';
