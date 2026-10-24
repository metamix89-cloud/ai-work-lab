const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS_COLOR = { reported: "#94a3b8", analyzing: "#8b5cf6", in_action: "#2563eb", verifying: "#0d9488", closed: "#16a34a" };
const ROLE = { worker: "작업자", quality: "품질팀", owner: "조치 담당" };
const KIND = { report: "신고", analyze: "분석 시작", assign: "원인 확정 · 담당 지정", reassign: "담당/계획 변경", complete: "조치 완료 등록", close: "검증 통과 · 종결", reject: "검증 반려", comment: "메모" };

const S = { meta: null, users: [], me: null, soon: false, openId: null, list: [], sum: null };

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (S.me) headers["X-User-Id"] = S.me.id;
  const r = await fetch(path, { ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : j.detail.map(d => `${d.loc.slice(-1)[0]}: ${d.msg}`).join(", "); } catch {}
    throw new Error(msg);
  }
  return r.json();
}
function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast.h); toast.h = setTimeout(() => t.hidden = true, 3200);
}
const pad = n => String(n).padStart(2, "0");
const fmtDT = s => { if (!s) return "-"; const d = new Date(s); return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
function span(ms) {
  const m = Math.floor(Math.abs(ms) / 60000), h = Math.floor(m / 60), d = Math.floor(h / 24);
  if (d >= 1) return `${d}일 ${h % 24}시간`;
  if (h >= 1) return `${h}시간 ${m % 60}분`;
  return `${m}분`;
}
function dueText(d) {
  if (d.status === "closed") return d.late_closed ? `종결 ${fmtDT(d.closed_at)} (기한 초과 종결)` : `종결 ${fmtDT(d.closed_at)}`;
  const ms = new Date(d.due_at) - Date.now();
  return ms < 0 ? `${span(ms)} 초과` : `${span(ms)} 남음`;
}
const sevBadge = k => `<span class="badge sev-${k}">${S.meta.severity.find(x => x.key === k).label}</span>`;
const stBadge = k => `<span class="badge st" style="--c:${STATUS_COLOR[k]}">${S.meta.status.find(x => x.key === k).label}</span>`;
const stLabel = k => S.meta.status.find(x => x.key === k).label;
const sevLabel = k => S.meta.severity.find(x => x.key === k).label;

function qs() {
  const p = new URLSearchParams();
  if ($("#q").value.trim()) p.set("q", $("#q").value.trim());
  if ($("#fStatus").value) p.set("status", $("#fStatus").value);
  if ($("#fSev").value) p.set("severity", $("#fSev").value);
  if ($("#fAsg").value) p.set("assignee_id", $("#fAsg").value);
  if ($("#fOverdue").checked) p.set("overdue", "true");
  if ($("#fOpen").checked && $("#fStatus").value !== "closed") p.set("open_only", "true");
  return p.toString();
}

async function refresh() {
  const [sum, list] = await Promise.all([api("/api/summary"), api("/api/defects?" + qs())]);
  S.sum = sum; S.list = S.soon ? list.filter(d => d.due_state === "soon") : list;
  renderCards(); renderPipeline(); renderWorkload(); renderSev(); renderTable();
  if (S.openId) openDrawer(S.openId, true);
}

function renderCards() {
  const s = S.sum;
  $("#cards").innerHTML = `
    <div class="card open" data-f="all"><div class="n">${s.open}</div><div class="l">미종결 신고</div></div>
    <div class="card over ${s.overdue ? "pulse" : ""}" data-f="overdue"><div class="n">${s.overdue}</div><div class="l">기한 초과</div></div>
    <div class="card soon" data-f="soon"><div class="n">${s.soon}</div><div class="l">${S.meta.soon_hours}시간 내 마감 임박</div></div>
    <div class="card done" data-f="closed"><div class="n">${s.closed_7d}</div><div class="l">최근 7일 종결 · 담당 미지정 ${s.unassigned}건 대기</div></div>`;
  $("#cards").querySelectorAll(".card").forEach(c => c.onclick = () => {
    const f = c.dataset.f; resetFilters();
    if (f === "overdue") $("#fOverdue").checked = true;
    if (f === "soon") S.soon = true;
    if (f === "closed") { $("#fOpen").checked = false; $("#fStatus").value = "closed"; }
    refresh();
  });
}
function renderPipeline() {
  const s = S.sum, cur = $("#fStatus").value;
  $("#pipeline").innerHTML = S.meta.status.map(st => `
    <div class="step ${cur === st.key ? "active" : ""}" data-k="${st.key}" style="--c:${STATUS_COLOR[st.key]}">
      <div class="muted">${st.label}</div><div class="n">${s.by_status[st.key]}</div>
      <div class="od">${s.by_status_overdue[st.key] ? "기한 초과 " + s.by_status_overdue[st.key] : "&nbsp;"}</div></div>`).join("");
  $("#pipeline").querySelectorAll(".step").forEach(el => el.onclick = () => {
    const k = el.dataset.k; S.soon = false;
    $("#fStatus").value = cur === k ? "" : k; if (k === "closed" && !cur) $("#fOpen").checked = false;
    refresh();
  });
}
function renderWorkload() {
  const w = S.sum.workload, max = Math.max(1, ...w.map(x => x.in_action + x.verifying));
  $("#workload").innerHTML = w.length ? w.map(x => `
    <div class="wl" data-id="${x.id}">
      <div class="nm"><b>${esc(x.name)}</b><span>${esc(x.dept)}</span></div>
      <div><div class="bar" title="조치중 ${x.in_action} · 검증대기 ${x.verifying}">
        <i class="a" style="width:${x.in_action / max * 100}%"></i><i class="v" style="width:${x.verifying / max * 100}%"></i></div>
        <span class="sub">조치중 ${x.in_action} · 검증대기 ${x.verifying}</span></div>
      <div class="od">${x.overdue ? "초과 " + x.overdue : ""}</div>
      <div class="nx ${new Date(x.next_due) < Date.now() ? "due overdue" : ""}">${x.next_due ? "가장 빠른 기한 " + fmtDT(x.next_due) : ""}</div>
    </div>`).join("") : '<div class="muted">조치 중인 건이 없습니다.</div>';
  $("#workload").querySelectorAll(".wl").forEach(el => el.onclick = () => {
    resetFilters(); $("#fAsg").value = el.dataset.id; refresh();
  });
}
function renderSev() {
  const bs = S.sum.by_severity, max = Math.max(1, ...Object.values(bs).map(v => v.open));
  $("#sev").innerHTML = S.meta.severity.map(sv => {
    const v = bs[sv.key], ok = v.open - v.overdue;
    return `<div class="sevrow" data-k="${sv.key}">${sevBadge(sv.key)}
      <div class="bar"><i style="width:${ok / max * 100}%;background:#94a3b8"></i><i style="width:${v.overdue / max * 100}%;background:var(--over)"></i></div>
      <div class="tot">${v.open}건${v.overdue ? ` <b style="color:var(--over)">(초과 ${v.overdue})</b>` : ""}</div></div>`;
  }).join("") + '<div class="sub">회색: 기한 내 · 빨강: 기한 초과</div>';
  $("#sev").querySelectorAll(".sevrow").forEach(el => el.onclick = () => { resetFilters(); $("#fSev").value = el.dataset.k; refresh(); });
}
function renderTable() {
  const rows = S.list.map(d => `
    <tr class="row ${d.due_state}" data-id="${d.id}">
      <td><div class="code">${esc(d.code)}</div><div class="sub">${fmtDT(d.reported_at)} 신고</div></td>
      <td>${sevBadge(d.severity)}</td>
      <td>${esc(d.lot_no)}<div class="sub">${esc(d.product)} · ${esc(d.line)}</div></td>
      <td>${esc(d.defect_type)}<div class="sub">${esc(d.process)} · ${d.qty.toLocaleString()}개</div></td>
      <td>${stBadge(d.status)}</td>
      <td class="who-cell">${d.assignee ? `<b>${esc(d.assignee.name)}</b><div class="sub">${esc(d.assignee.dept)}</div>`
        : d.status === "closed" ? "-" : `<span class="none">${d.status === "analyzing" ? "분석중 · 담당 미정" : "담당 미정"}</span>${d.analyst ? `<div class="sub">분석 ${esc(d.analyst.name)}</div>` : ""}`}</td>
      <td><div class="due ${d.due_state}">${dueText(d)}</div><div class="sub">기한 ${fmtDT(d.due_at)}</div></td>
    </tr>`).join("");
  $("#tbl").innerHTML = `<thead><tr><th>신고</th><th>심각도</th><th>로트 / 제품</th><th>불량</th><th>단계</th><th>조치 담당</th><th>기한</th></tr></thead><tbody>${rows}</tbody>`;
  $("#empty").hidden = S.list.length > 0;
  $("#tbl").querySelectorAll("tr.row").forEach(tr => tr.onclick = () => openDrawer(+tr.dataset.id));
}
function resetFilters() {
  S.soon = false; $("#q").value = ""; $("#fStatus").value = ""; $("#fSev").value = ""; $("#fAsg").value = "";
  $("#fOverdue").checked = false; $("#fOpen").checked = true;
}

// ------------------------------------------------------------ detail drawer
async function openDrawer(id, silent) {
  let d;
  try { d = await api("/api/defects/" + id); } catch (e) { S.openId = null; $("#drawer").hidden = true; return; }
  // 입력 중인 폼이 새로고침으로 지워지지 않도록, 자동 갱신 시 폼 포커스가 있으면 건드리지 않음
  if (silent && $("#drawerBody").contains(document.activeElement) && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
  S.openId = id;
  const me = S.me, quality = me.role === "quality";
  const dl = [["심각도", sevBadge(d.severity) + ` · 기한 ${fmtDT(d.due_at)}`],
    ["로트/제품", `${esc(d.lot_no)} · ${esc(d.product)} · ${esc(d.line)}`],
    ["공정/유형", `${esc(d.process)} · ${esc(d.defect_type)} · ${d.qty.toLocaleString()}개`],
    ["신고", `${esc(d.reporter.name)} (${esc(d.reporter.dept)}) · ${fmtDT(d.reported_at)}`],
    ["증상", esc(d.description)]];
  if (d.analyst) dl.push(["분석", esc(d.analyst.name)]);
  if (d.cause_category) dl.push(["원인", `[${esc(d.cause_category)}] ${esc(d.root_cause)}`]);
  if (d.assignee) dl.push(["조치 담당", `<b>${esc(d.assignee.name)}</b> (${esc(d.assignee.dept)})`]);
  if (d.action_plan) dl.push(["조치 계획", esc(d.action_plan)]);
  if (d.action_result) dl.push(["조치 결과", esc(d.action_result)]);
  if (d.verification_note) dl.push(["검증 의견", esc(d.verification_note)]);

  $("#drawerBody").innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:start"><div>
      <h3>${esc(d.code)} ${stBadge(d.status)}</h3><div class="due ${d.due_state}">${dueText(d)}</div></div>
      <button id="closeDrawer">닫기 ✕</button></div>
    ${d.is_overdue ? `<div class="alert">기한을 ${span(new Date(d.due_at) - Date.now())} 넘겼습니다. ${d.assignee ? esc(d.assignee.name) + " 님 조치 필요" : "담당자 지정이 필요합니다"}.</div>` : ""}
    <dl class="dl">${dl.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    <div class="sect" id="actionArea">${actionForm(d, me, quality)}</div>
    <div class="sect"><h4>처리 이력</h4><ul class="timeline">${d.events.map(e => `
      <li class="${e.kind}"><b>${KIND[e.kind] || e.kind}</b> · ${esc(e.actor)}
        <div class="t">${fmtDT(e.at)}${e.to_status && e.from_status ? ` · ${stLabel(e.from_status)} → ${stLabel(e.to_status)}` : ""}</div>
        ${e.note ? `<div>${esc(e.note)}</div>` : ""}</li>`).join("")}</ul></div>`;
  $("#drawer").hidden = false;
  $("#closeDrawer").onclick = closeDrawer;
  wireActions(d);
}
function closeDrawer() { S.openId = null; $("#drawer").hidden = true; }

function ownerOptions(sel) {
  return S.users.filter(u => u.role !== "worker").map(u => `<option value="${u.id}" ${u.id === sel ? "selected" : ""}>${esc(u.name)} · ${esc(u.dept)}</option>`).join("");
}
function analysisForm(d, label) {
  return `<form class="f" data-action="assign">
    <label>원인 분류<select name="cause_category">${S.meta.cause_categories.map(c => `<option ${c === d.cause_category ? "selected" : ""}>${c}</option>`).join("")}</select></label>
    <label>근본 원인<textarea name="root_cause" rows="2" required>${esc(d.root_cause || "")}</textarea></label>
    <label>조치 담당자<select name="assignee_id">${ownerOptions(d.assignee_id)}</select></label>
    <label>조치 계획<textarea name="action_plan" rows="2" required>${esc(d.action_plan || "")}</textarea></label>
    <div class="err"></div><div class="actions"><button class="primary">${label}</button></div></form>`;
}
function actionForm(d, me, quality) {
  const memo = `<form class="f" data-action="comment" style="margin-top:14px"><label>메모 남기기<textarea name="note" rows="2"></textarea></label>
    <div class="err"></div><div class="actions"><button>메모 등록</button></div></form>`;
  if (d.status === "closed") return `<div class="muted">종결된 건입니다.</div>` + memo;
  let h = "";
  if (d.status === "reported") {
    h = quality ? `<h4>다음 단계</h4><form class="f" data-action="analyze"><div class="err"></div><div class="actions"><button class="primary">원인 분석 시작 (내가 분석)</button></div></form>`
      : `<div class="muted">품질팀이 분석을 시작하기를 기다리는 중입니다.</div>`;
  } else if (d.status === "analyzing") {
    h = quality ? `<h4>원인 확정 · 담당자 지정</h4>` + analysisForm(d, "조치 시작")
      : `<div class="muted">품질팀이 원인을 분석하는 중입니다.</div>`;
  } else if (d.status === "in_action") {
    const mine = d.assignee_id === me.id || quality;
    h = mine ? `<h4>조치 완료 등록</h4>${d.verification_note ? `<div class="alert">검증 반려: ${esc(d.verification_note)}</div>` : ""}
      <form class="f" data-action="complete"><label>조치 결과<textarea name="action_result" rows="3" required placeholder="무엇을 했고, 어떻게 확인했는지"></textarea></label>
      <div class="err"></div><div class="actions"><button class="primary">조치 완료 → 검증 요청</button></div></form>`
      : `<div class="muted">${esc(d.assignee.name)} 님이 조치 중입니다.</div>`;
    if (quality) h += `<details style="margin-top:10px"><summary>담당자/계획 변경</summary>${analysisForm(d, "변경 저장")}</details>`;
  } else if (d.status === "verifying") {
    if (!quality) h = `<div class="muted">품질팀 검증을 기다리는 중입니다.</div>`;
    else if (d.assignee_id === me.id) h = `<div class="muted">조치 담당자 본인은 검증할 수 없습니다. 다른 품질팀원으로 전환하세요.</div>`;
    else h = `<h4>검증</h4><form class="f" data-action="verify"><label>검증 의견 (반려 시 필수)<textarea name="note" rows="2"></textarea></label>
      <div class="err"></div><div class="actions"><button type="button" class="danger" data-result="reject">반려 → 재조치</button>
      <button type="button" class="primary" data-result="ok">검증 통과 · 종결</button></div></form>`;
  }
  return h + memo;
}
function wireActions(d) {
  $("#actionArea").querySelectorAll("form.f").forEach(f => {
    const run = async result => {
      const body = Object.fromEntries(new FormData(f)); body.action = f.dataset.action;
      if (body.assignee_id) body.assignee_id = +body.assignee_id;
      if (result) body.result = result;
      try { await api(`/api/defects/${d.id}/transition`, { method: "POST", body }); toast("처리되었습니다"); await refresh(); }
      catch (e) { f.querySelector(".err").textContent = e.message; }
    };
    f.onsubmit = ev => { ev.preventDefault(); run(); };
    f.querySelectorAll("[data-result]").forEach(b => b.onclick = () => run(b.dataset.result));
  });
}
$("#drawer").addEventListener("click", e => { if (e.target.classList.contains("drawer-bg")) closeDrawer(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

// ------------------------------------------------------------ new report
function dueHint() {
  const f = $("#newForm"), h = S.meta.severity.find(x => x.key === f.severity.value).hours;
  const due = new Date(Date.now() + h * 3600e3);
  $("#dueHint").textContent = `이 심각도의 처리 기한: ${h >= 48 ? h / 24 + "일" : h + "시간"} → ${fmtDT(due)} 까지`;
}
$("#newBtn").onclick = () => {
  $("#newErr").textContent = ""; dueHint(); $("#newDlg").showModal();
};
$("#newCancel").onclick = () => $("#newDlg").close();
$("#newForm").onsubmit = async ev => {
  ev.preventDefault();
  const body = Object.fromEntries(new FormData(ev.target)); body.qty = +body.qty;
  try {
    const r = await api("/api/defects", { method: "POST", body });
    $("#newDlg").close(); ev.target.reset(); toast(`${r.code} 신고 완료`); resetFilters(); await refresh();
  } catch (e) { $("#newErr").textContent = e.message; }
};

// ------------------------------------------------------------ init
function fillSelect(el, first, items) {
  el.innerHTML = (first ? `<option value="">${first}</option>` : "") + items.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
}
async function init() {
  [S.meta, S.users] = await Promise.all([api("/api/meta"), api("/api/users")]);
  const saved = +localStorage.getItem("uid");
  S.me = S.users.find(u => u.id === saved) || S.users.find(u => u.role === "quality");
  fillSelect($("#userSel"), null, S.users.map(u => [u.id, `${u.name} (${ROLE[u.role]} · ${u.dept})`]));
  $("#userSel").value = S.me.id;
  $("#userSel").onchange = () => { S.me = S.users.find(u => u.id === +$("#userSel").value); localStorage.setItem("uid", S.me.id); refresh(); };
  fillSelect($("#fStatus"), "모든 단계", S.meta.status.map(s => [s.key, s.label]));
  fillSelect($("#fSev"), "모든 심각도", S.meta.severity.map(s => [s.key, s.label]));
  fillSelect($("#fAsg"), "모든 담당자", S.users.filter(u => u.role !== "worker").map(u => [u.id, u.name]));
  const nf = $("#newForm");
  fillSelect(nf.process, null, S.meta.processes.map(x => [x, x]));
  fillSelect(nf.defect_type, null, S.meta.defect_types.map(x => [x, x]));
  fillSelect(nf.severity, null, S.meta.severity.map(s => [s.key, `${s.label} (기한 ${s.hours >= 48 ? s.hours / 24 + "일" : s.hours + "시간"})`]));
  nf.severity.value = "medium"; nf.severity.onchange = dueHint;
  ["fStatus", "fSev", "fAsg", "fOverdue", "fOpen"].forEach(id => $("#" + id).onchange = () => { S.soon = false; refresh(); });
  let t; $("#q").oninput = () => { clearTimeout(t); t = setTimeout(refresh, 250); };
  setInterval(() => { $("#clock").textContent = new Date().toLocaleString("ko-KR"); }, 1000);
  await refresh();
  setInterval(() => refresh().catch(() => {}), 30000);
}
init().catch(e => toast("불러오기 실패: " + e.message, true));
