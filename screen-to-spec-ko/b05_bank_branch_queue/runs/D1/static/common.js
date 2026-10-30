async function api(path, method = "GET", body, token) {
  const h = {"Content-Type": "application/json"};
  if (token) h.Authorization = "Bearer " + token;
  const r = await fetch(path, {method, headers: h, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    let d = j.detail;
    if (Array.isArray(d)) d = "입력값을 확인하세요: " + d.map(x => x.loc.slice(-1)[0]).join(", ");
    const e = new Error(d || "오류"); e.status = r.status; throw e;
  }
  return j;
}
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
function say(node, text, ok) { node.textContent = text; node.className = "msg " + (ok ? "ok" : "err"); }
