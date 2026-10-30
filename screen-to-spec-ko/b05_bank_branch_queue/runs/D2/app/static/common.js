const $ = s => document.querySelector(s);
// 사용자 입력은 전부 textContent/append(문자열)로만 넣는다 (innerHTML 금지)
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const x of kids.flat()) e.append(x instanceof Node ? x : String(x));
  return e;
}
async function api(path, { method = 'GET', body, auth } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const t = auth && sessionStorage.getItem('tok:' + auth);
  if (t) headers['X-Token'] = t;
  const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let d = {};
  try { d = await r.json(); } catch { /* empty */ }
  if (!r.ok) {
    const m = Array.isArray(d.detail) ? d.detail.map(x => x.msg.replace(/^Value error, /, '')).join(', ') : d.detail;
    const e = new Error(m || '오류가 발생했습니다');
    e.status = r.status;
    throw e;
  }
  return d;
}
function say(el, text, err) { el.className = 'msg' + (err ? ' err' : ''); el.textContent = text; }
