// 공용 유틸. 사용자 입력은 항상 textContent로만 넣어 XSS를 막는다.
const $ = (s, r = document) => r.querySelector(s);

function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) e.append(k instanceof Node ? k : document.createTextNode(k ?? ""));
  return e;
}

async function api(path, { method = "GET", body, role } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (role) headers["X-Token"] = sessionStorage.getItem("token_" + role) || "";
  const res = await fetch("/api" + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => (d.msg || "").replace(/^Value error, /, "")).join(" / ");
    const err = new Error(msg || "요청에 실패했습니다.");
    err.status = res.status;
    throw err;
  }
  return data;
}

async function login(role, pin) {
  const { token } = await api("/login", { method: "POST", body: { role, pin } });
  sessionStorage.setItem("token_" + role, token);
}

// 로그인 박스를 보여주고 성공하면 onOk 실행
function loginGate(role, label, onOk) {
  const box = $("#login");
  box.hidden = false;
  $("#app").hidden = true;
  $("#login form").onsubmit = async ev => {
    ev.preventDefault();
    try {
      await login(role, $("#pin").value);
      box.hidden = true;
      $("#app").hidden = false;
      onOk();
    } catch (e) { $("#login .err").textContent = e.message; }
  };
  $("#login h2").textContent = label + " 로그인";
}

const SVC_CLASS = { 예금: "svc-d", 대출: "svc-l", 외환: "svc-f" };
const svcTag = s => h("span", { class: "tag " + SVC_CLASS[s] }, s);
