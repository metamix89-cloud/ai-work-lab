// 사용자 입력은 항상 textContent(텍스트 노드)로만 렌더링한다 (XSS 방지)
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
function fillTable(tb, rows) { tb.replaceChildren(...rows.map(r => h('tr', {}, r.map(c => h('td', {}, c))))); }
async function api(path, opt = {}) {
  const tok = sessionStorage.getItem('tok');
  const r = await fetch(path, {
    method: opt.body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', ...(tok ? { 'X-Token': tok } : {}) },
    body: opt.body ? JSON.stringify(opt.body) : undefined,
  });
  let j = {}; try { j = await r.json(); } catch (e) {}
  if (!r.ok) {
    let d = j.detail;
    if (Array.isArray(d)) d = d.map(x => (x.msg || '').replace('Value error, ', '')).join(' / ');
    const err = new Error(d || '요청 실패'); err.status = r.status; throw err;
  }
  return j;
}
const hhmm = s => s ? s.slice(11, 16) : '';
const KIND = k => k === 'reservation' ? h('span', { class: 'tag r' }, '예약') : h('span', { class: 'tag' }, '현장');
const NAV = () => h('nav', {}, h('a', { href: '/static/index.html' }, '고객'), h('a', { href: '/static/display.html' }, '대기화면'),
  h('a', { href: '/static/teller.html' }, '창구'), h('a', { href: '/static/manager.html' }, '지점장'));
function loginBox(role, onOk) {
  const pin = h('input', { type: 'password', placeholder: 'PIN', autocomplete: 'off' });
  const m = h('div');
  const go = async () => {
    try { const j = await api('/api/login', { body: { role, pin: pin.value } }); sessionStorage.setItem('tok', j.token); onOk(); }
    catch (e) { m.replaceChildren(h('div', { class: 'msg err' }, e.message)); }
  };
  pin.onkeydown = e => { if (e.key === 'Enter') go(); };
  return h('div', { class: 'card', style: 'max-width:340px;margin:60px auto' },
    h('h2', {}, role === 'teller' ? '창구 직원 로그인' : '지점장 로그인'), pin, h('button', { onclick: go }, '로그인'), m);
}
