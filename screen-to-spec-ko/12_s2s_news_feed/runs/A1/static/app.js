const $ = (s) => document.querySelector(s);
let token = localStorage.getItem("token");
let me = null;
let nextBefore = null; // 일반 글 커서: 지금까지 불러온 가장 작은 id
const seen = new Set();

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("show"), 2200);
}

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && path !== "/login") { logout(true); throw new Error("로그인이 필요합니다."); }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : "요청을 처리하지 못했습니다.");
  }
  return data;
}

// 요소 생성 헬퍼: 사용자 입력은 항상 textContent 로만 넣어 XSS 를 막는다.
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  e.append(...kids.filter((k) => k != null));
  return e;
}
const fmt = (s) => s.slice(0, 16).replace("T", " ");

// ---------- 로그인 ----------
function showLogin() {
  $("#login").hidden = false; $("#feed").hidden = true; $("#who").hidden = true;
}
function logout(silent) {
  if (!silent && token) api("/logout", { method: "POST" }).catch(() => {});
  token = null; me = null; localStorage.removeItem("token");
  showLogin();
}
$("#btn-logout").onclick = () => logout();
document.querySelectorAll("[data-u]").forEach((a) => a.onclick = (e) => {
  e.preventDefault();
  const f = $("#login-form");
  f.username.value = a.dataset.u; f.password.value = "daon1234";
});
$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await api("/login", { method: "POST", body: { username: e.target.username.value, password: e.target.password.value } });
    token = r.token; localStorage.setItem("token", token);
    e.target.reset();
    start(r.user);
  } catch (err) { toast(err.message); }
};

function start(user) {
  me = user;
  $("#login").hidden = true; $("#feed").hidden = false; $("#who").hidden = false;
  $("#who-text").textContent = `${me.name} · ${me.dept}${me.is_admin ? " (운영자)" : ""}`;
  $("#btn-reports").hidden = !me.is_admin;
  $("#reports-panel").hidden = true;
  reload();
}

// ---------- 목록 ----------
async function reload() {
  $("#list").replaceChildren(); seen.clear(); nextBefore = null;
  await loadMore(true);
}
async function loadMore(first = false) {
  const btn = $("#more");
  btn.disabled = true;
  try {
    const r = await api("/posts" + (first ? "" : "?before=" + nextBefore));
    [...r.pinned, ...r.posts].forEach((p) => {
      if (seen.has(p.id)) return;
      seen.add(p.id);
      $("#list").append(renderPost(p));
    });
    if (r.posts.length) nextBefore = r.posts[r.posts.length - 1].id;
    btn.hidden = !r.has_more;
    $("#empty").hidden = seen.size > 0;
  } catch (err) { toast(err.message); }
  btn.disabled = false;
}
$("#more").onclick = () => loadMore();

function renderPost(p) {
  const root = el("article", { className: "post" + (p.pinned ? " pinned" : "") });
  const cc = el("span", {}, `💬 댓글 ${p.comment_count}`);
  const box = el("div", { className: "comments", hidden: true });
  const actions = el("div", { className: "actions" });
  const body = el("div", { className: "body", textContent: p.content });

  root.append(
    el("div", { className: "meta" },
      el("span", {}, p.pinned ? el("span", { className: "badge" }, "📌 공지") : null,
        el("b", {}, p.author.name), ` · ${p.author.dept}`),
      el("span", {}, fmt(p.created_at))),
    body, actions, box);

  const toggle = el("button", {}, cc);
  let loaded = false;
  toggle.onclick = async () => {
    box.hidden = !box.hidden;
    if (!box.hidden && !loaded) { loaded = true; await renderComments(p, box, cc); }
  };
  actions.append(toggle);

  if (me.is_admin) {
    const pin = el("button", {}, p.pinned ? "고정 해제" : "📌 상단 고정");
    pin.onclick = async () => {
      try { await api(`/posts/${p.id}/pin`, { method: "PUT", body: { pinned: !p.pinned } }); reload(); }
      catch (err) { toast(err.message); }
    };
    actions.append(pin);
    if (p.report_count) actions.append(el("span", { className: "rc" }, `🚩 신고 ${p.report_count}건`));
  }
  if (p.mine) {
    const del = el("button", { className: "danger" }, "삭제");
    del.onclick = async () => {
      if (!confirm("이 글을 삭제할까요? 댓글도 함께 삭제됩니다.")) return;
      try { await api("/posts/" + p.id, { method: "DELETE" }); root.remove(); seen.delete(p.id); toast("삭제했습니다."); }
      catch (err) { toast(err.message); }
    };
    actions.append(del);
  } else {
    const rep = el("button", {}, p.reported_by_me ? "신고함" : "🚩 신고");
    rep.disabled = p.reported_by_me;
    rep.onclick = async () => {
      const reason = prompt("신고 사유를 입력해 주세요 (최대 200자)");
      if (!reason || !reason.trim()) return;
      try {
        await api(`/posts/${p.id}/report`, { method: "POST", body: { reason } });
        rep.textContent = "신고함"; rep.disabled = true; toast("신고가 접수되었습니다.");
      } catch (err) { toast(err.message); }
    };
    actions.append(rep);
  }
  return root;
}

async function renderComments(p, box, counter) {
  const list = el("div");
  const form = el("form");
  const input = el("input", { placeholder: "댓글 입력 (최대 200자)", maxLength: 200, required: true });
  form.append(input, el("button", { className: "primary" }, "등록"));
  box.append(list, form);
  let n = 0;
  const add = (c) => {
    const row = el("div", { className: "comment" },
      el("span", {}, el("b", {}, c.author.name), " ", c.content, " ", el("small", {}, fmt(c.created_at))));
    if (c.mine) {
      const x = el("button", { className: "x", title: "삭제" }, "삭제");
      x.onclick = async () => {
        try { await api("/comments/" + c.id, { method: "DELETE" }); row.remove(); counter.textContent = `💬 댓글 ${--n}`; }
        catch (err) { toast(err.message); }
      };
      row.append(x);
    }
    list.append(row); n++;
    counter.textContent = `💬 댓글 ${n}`;
  };
  form.onsubmit = async (e) => {
    e.preventDefault();
    try { add(await api(`/posts/${p.id}/comments`, { method: "POST", body: { content: input.value } })); input.value = ""; }
    catch (err) { toast(err.message); }
  };
  try { (await api(`/posts/${p.id}/comments`)).forEach(add); } catch (err) { toast(err.message); }
}

// ---------- 글쓰기 ----------
$("#post-form textarea").oninput = (e) => $("#post-count").textContent = `${e.target.value.length} / 500`;
$("#post-form").onsubmit = async (e) => {
  e.preventDefault();
  const ta = e.target.content;
  if (!ta.value.trim()) return toast("내용을 입력해 주세요.");
  try {
    const p = await api("/posts", { method: "POST", body: { content: ta.value } });
    ta.value = ""; $("#post-count").textContent = "0 / 500";
    seen.add(p.id);
    const node = renderPost(p);
    // 고정 글 바로 아래(= 일반 글 맨 위)에 끼워 넣는다
    const firstNormal = [...$("#list").children].find((c) => !c.classList.contains("pinned"));
    $("#list").insertBefore(node, firstNormal || null);
    $("#empty").hidden = true;
  } catch (err) { toast(err.message); }
};

// ---------- 신고 목록 (운영자) ----------
$("#btn-reports").onclick = async () => {
  const panel = $("#reports-panel");
  if (!panel.hidden) { panel.hidden = true; return; }
  try {
    const rows = await api("/reports");
    panel.replaceChildren(el("h3", {}, `신고된 글 (${rows.length})`));
    if (!rows.length) panel.append(el("p", { className: "hint" }, "신고된 글이 없습니다."));
    const ul = el("ul");
    rows.forEach((r) => ul.append(el("li", {},
      el("b", {}, `신고 ${r.cnt}건`), ` · ${r.author_name}: ${r.content.slice(0, 60)}`, el("br"),
      el("small", {}, "사유: " + r.reasons))));
    panel.append(ul); panel.hidden = false;
  } catch (err) { toast(err.message); }
};

// ---------- 시작 ----------
(async () => {
  if (!token) return showLogin();
  try { start(await api("/me")); } catch { showLogin(); }
})();
