async function api(path, opts = {}) {
  const tok = sessionStorage.getItem('token');
  const r = await fetch(path, {
    method: opts.body ? 'POST' : (opts.method || 'GET'),
    headers: {'Content-Type': 'application/json', ...(tok ? {Authorization: 'Bearer ' + tok} : {})},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    let msg = d.detail;
    if (Array.isArray(msg)) msg = msg.map(e => (e.msg || '').replace(/^Value error, /, '')).join(' / ');
    const e = new Error(msg || '오류가 발생했습니다.'); e.status = r.status; throw e;
  }
  return d;
}
// 문자열 자식은 append 가 텍스트 노드로 처리하므로 HTML 주입이 불가능하다.
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) k === 'class' ? e.className = v : e[k] = v;
  for (const k of kids.flat()) e.append(k);
  return e;
}
const fmtTime = ts => new Date(ts * 1000).toLocaleString('ko-KR', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'});
