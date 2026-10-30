// 모든 화면 공통: API 호출, DOM 헬퍼 (사용자 입력은 항상 textContent로만 넣는다)
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  const tok = sessionStorage.getItem("token");
  if (tok) headers["X-Token"] = tok;
  const res = await fetch(path, { ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map(m => (m.msg || "").replace("Value error, ", "")).join(" / ");
    const err = new Error(msg || "요청에 실패했습니다");
    err.status = res.status;
    throw err;
  }
  return data;
}

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k);
  return e;
}

function fill(el, ...kids) { el.replaceChildren(...kids.flat()); }
