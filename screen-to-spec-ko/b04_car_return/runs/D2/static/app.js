"use strict";
const $app = document.getElementById("app");
let me = null, meta = null;

const won = n => (n ?? 0).toLocaleString("ko-KR") + "원";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = iso => iso ? new Date(iso).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" }) : "-";

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (res.status === 401 && path !== "/api/login") { me = null; render(); throw new Error("로그인이 필요합니다."); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join("\n") : "요청 실패");
  }
  return body;
}

function setWho() {
  document.getElementById("who").hidden = !me;
  document.getElementById("whoName").textContent = me ? `${me.name} (${me.role === "staff" ? "직원" : "고객"})` : "";
}
document.getElementById("logout").onclick = async () => { await api("/api/logout", { method: "POST" }); me = null; render(); };

async function render() {
  setWho();
  if (!me) return loginView();
  if (!meta) meta = await api("/api/meta");
  return listView();
}

function loginView() {
  $app.innerHTML = `<div class="card" style="max-width:380px;margin:40px auto">
    <h2>로그인</h2>
    <form id="f"><label>아이디<input name="username" autocomplete="username" required></label>
    <label>비밀번호<input name="password" type="password" autocomplete="current-password" required></label>
    <div class="err" id="err"></div><button>로그인</button></form>
    <p class="hint" style="margin-top:14px">데모 계정<br>직원: staff / staff1234<br>고객: kim / kim1234 · lee / lee1234 · park / park1234</p></div>`;
  document.getElementById("f").onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      me = await api("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: fd.get("username"), password: fd.get("password") }) });
      render();
    } catch (x) { document.getElementById("err").textContent = x.message; }
  };
}

async function listView() {
  const rows = await api("/api/rentals");
  const staff = me.role === "staff";
  $app.innerHTML = `<div class="card"><h2>${staff ? "대여 건 (반납 대기 우선)" : "내 대여 내역"}</h2>
    <table><thead><tr><th>#</th><th>차량</th>${staff ? "<th>고객</th>" : ""}<th>반납 예정</th><th>상태</th><th class="num">청구액</th></tr></thead><tbody>
    ${rows.map(r => `<tr class="click" data-id="${r.id}"><td>${r.id}</td><td>${esc(r.model)} <span class="mute">${esc(r.plate)}</span></td>
      ${staff ? `<td>${esc(r.customer_name)}</td>` : ""}<td>${fmt(r.due_at)}</td>
      <td><span class="badge ${r.status === "returned" ? "done" : ""}">${r.status === "returned" ? "반납 완료" : "대여 중"}</span></td>
      <td class="num">${r.status === "returned" ? won(r.total_charge) : "-"}</td></tr>`).join("") || `<tr><td colspan="6" class="mute">내역이 없습니다.</td></tr>`}
    </tbody></table></div>`;
  $app.querySelectorAll("tr.click").forEach(tr => tr.onclick = () => detailView(+tr.dataset.id));
}

function damageList(r) {
  if (!r.damages.length) return `<p class="mute">기록된 흠집이 없습니다.</p>`;
  return `<table><thead><tr><th>시점</th><th>부위</th><th>등급</th><th>사진</th><th>메모</th><th class="num">청구</th></tr></thead><tbody>` +
    r.damages.map(d => `<tr><td>${d.phase === "pickup" ? "대여 시" : "반납 시"}</td><td>${esc(meta.parts[d.part])}</td>
      <td>${esc(meta.grades[d.grade])}</td>
      <td class="thumbs"><a href="/api/photos/${d.id}" target="_blank" rel="noopener"><img src="/api/photos/${d.id}" alt="흠집 사진"></a></td>
      <td>${esc(d.note)}${d.pre_existing ? ' <span class="badge waive">대여 전부터 있음</span>' : ""}</td>
      <td class="num">${d.phase === "pickup" ? "-" : won(d.fee)}</td></tr>`).join("") + `</tbody></table>`;
}

async function detailView(id) {
  const r = await api(`/api/rentals/${id}`);
  const staff = me.role === "staff";
  const back = `<p><button class="ghost" id="back">← 목록</button></p>`;
  let html = back + `<div class="card"><h2>${esc(r.model)} <span class="mute">${esc(r.plate)}</span></h2>
    <div class="row mute"><div>고객<br><b>${esc(r.customer_name)}</b></div><div>대여 시작<br><b>${fmt(r.started_at)}</b></div>
    <div>반납 예정<br><b>${fmt(r.due_at)}</b></div><div>대여 시 연료/주행<br><b>${r.start_fuel}/8칸 · ${r.start_odometer.toLocaleString()}km</b></div>
    ${r.status === "returned" ? `<div>반납<br><b>${fmt(r.returned_at)}</b></div><div>반납 시 연료/주행<br><b>${r.end_fuel}/8칸 · ${r.end_odometer.toLocaleString()}km</b></div>` : ""}</div></div>
    <div class="card"><h2>흠집 기록</h2>${damageList(r)}</div>`;
  if (r.status === "returned") {
    html += `<div class="card"><h2>청구 내역</h2><table><tbody>${r.charges.map(c =>
      `<tr><td>${esc(c.description)}</td><td class="num">${won(c.amount)}</td></tr>`).join("")}</tbody></table>
      <div class="total">합계 ${won(r.total_charge)}</div></div>`;
    $app.innerHTML = html;
  } else if (staff) {
    $app.innerHTML = html + `<div class="card" id="form"></div>`;
    inspectionForm(r);
  } else {
    $app.innerHTML = html + `<div class="card mute">아직 반납 전입니다. 반납 점검이 끝나면 청구 내역이 표시됩니다.</div>`;
  }
  document.getElementById("back").onclick = listView;
}

function toLocalInput(d) {
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function inspectionForm(r) {
  const pickups = r.damages.filter(d => d.phase === "pickup");
  const partOpts = Object.entries(meta.parts).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  const gradeOpts = Object.entries(meta.grades).map(([k, v]) =>
    `<option value="${k}">${esc(v)} (${won(meta.damage_fees[k])})</option>`).join("");
  const linkOpts = `<option value="">새 흠집 (청구 대상)</option>` + pickups.map(p =>
    `<option value="${p.id}" data-part="${p.part}" data-grade="${p.grade}">대여 전 흠집과 동일: ${esc(meta.parts[p.part])} ${esc(meta.grades[p.grade])}</option>`).join("");
  document.getElementById("form").innerHTML = `<h2>반납 점검</h2><form id="f">
    <div class="row"><label>반납 시각<input type="datetime-local" name="returned_at" value="${toLocalInput(new Date())}" required></label>
    <label>연료 (0~8칸)<select name="end_fuel">${[8,7,6,5,4,3,2,1,0].map(n => `<option ${n === r.start_fuel ? "selected" : ""}>${n}</option>`).join("")}</select></label>
    <label>주행거리 (km)<input type="number" name="end_odometer" min="${r.start_odometer}" value="${r.start_odometer}" required></label></div>
    <h2>흠집 <button type="button" class="ghost" id="add">+ 추가</button></h2>
    <p class="mute">사진이 없는 흠집은 접수되지 않습니다. 대여 전부터 있던 흠집은 '동일' 항목을 선택하면 기록만 남고 0원입니다.</p>
    <div id="dmgs"></div><div class="err" id="err"></div><button id="submit">반납 확정 · 요금 계산</button></form>`;
  const box = document.getElementById("dmgs");
  document.getElementById("add").onclick = () => {
    const el = document.createElement("div");
    el.className = "dmg";
    el.innerHTML = `<div class="row"><label>기존 흠집 여부<select class="link">${linkOpts}</select></label>
      <label>부위<select class="part">${partOpts}</select></label><label>등급<select class="grade">${gradeOpts}</select></label>
      <label>사진 (필수)<input type="file" class="photo" accept="image/jpeg,image/png,image/webp" required></label></div>
      <label>메모<input class="note" maxlength="200"></label><button type="button" class="ghost rm">삭제</button>`;
    el.querySelector(".rm").onclick = () => el.remove();
    const link = el.querySelector(".link"), part = el.querySelector(".part"), grade = el.querySelector(".grade");
    link.onchange = () => {  // 기존 흠집을 고르면 부위·등급을 맞춰 주고 잠근다
      const o = link.selectedOptions[0];
      part.disabled = grade.disabled = !!link.value;
      if (link.value) { part.value = o.dataset.part; grade.value = o.dataset.grade; }
    };
    box.appendChild(el);
  };
  document.getElementById("f").onsubmit = async e => {
    e.preventDefault();
    const err = document.getElementById("err"), btn = document.getElementById("submit");
    err.textContent = "";
    const fd = new FormData();
    const f = e.target;
    fd.append("returned_at", f.returned_at.value);
    fd.append("end_fuel", f.end_fuel.value);
    fd.append("end_odometer", f.end_odometer.value);
    const items = [];
    for (const [i, el] of [...box.children].entries()) {
      const file = el.querySelector(".photo").files[0];
      if (!file) { err.textContent = `${i + 1}번 흠집: 사진이 없는 흠집은 접수할 수 없습니다.`; return; }
      fd.append(`photo_${i}`, file);
      items.push({ part: el.querySelector(".part").value, grade: el.querySelector(".grade").value,
        note: el.querySelector(".note").value, pre_existing_id: el.querySelector(".link").value ? +el.querySelector(".link").value : null });
    }
    fd.append("damages", JSON.stringify(items));
    if (!confirm("반납을 확정하고 요금을 청구합니다. 확정 후에는 수정할 수 없습니다.")) return;
    btn.disabled = true;
    try { await api(`/api/rentals/${r.id}/return`, { method: "POST", body: fd }); detailView(r.id); }
    catch (x) { err.textContent = x.message; btn.disabled = false; }
  };
}

api("/api/me").then(u => { me = u; }).catch(() => {}).finally(render);
