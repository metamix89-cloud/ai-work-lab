"use strict";
// 모든 동적 텍스트는 textContent 로만 넣어서 XSS 를 막는다 (innerHTML 미사용).
const $app = document.getElementById("app");
const $who = document.getElementById("who");
let CFG = null, ME = null;

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const won = n => Number(n).toLocaleString("ko-KR") + "원";
const fmt = s => s ? s.replace("T", " ") : "-";
const fuelTxt = n => `${n}/${CFG.fuel_units}`;

async function api(path, opts = {}) {
  const o = { credentials: "same-origin", ...opts };
  if (opts.json !== undefined) {
    o.method = o.method || "POST";
    o.headers = { "Content-Type": "application/json" };
    o.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch (_) { /* 본문 없음 */ }
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("로그인이 필요합니다"); }
  if (!r.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = "입력값을 확인하세요 (" + msg.map(m => m.loc.slice(1).join(".")).join(", ") + ")";
    throw new Error(msg || "요청 실패 " + r.status);
  }
  return data;
}

function msg(kind, text) { return h("div", { class: "msg " + kind }, text); }

// ------------------------------------------------------------ login
function showLogin() {
  ME = null; $who.replaceChildren();
  const u = h("input", { id: "u", autocomplete: "username", autofocus: true });
  const p = h("input", { id: "p", type: "password", autocomplete: "current-password" });
  const err = h("div");
  const go = async () => {
    try {
      await api("/api/login", { json: { username: u.value, password: p.value } });
      start();
    } catch (e) { err.replaceChildren(msg("err", e.message)); }
  };
  p.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  $app.replaceChildren(h("div", { class: "card login" },
    h("h2", {}, "로그인"),
    h("label", {}, "아이디"), u, h("label", {}, "비밀번호"), p, err,
    h("p", {}, h("button", { onclick: go }, "로그인")),
    h("div", { class: "hint" },
      "데모 계정 (비밀번호 모두 demo1234)", h("br"),
      "직원: staff1, staff2", h("br"),
      "고객: minjun(김민준), seoyeon(이서연), jihun(박지훈)")));
}

async function start() {
  try {
    ME = await api("/api/me");
    CFG = await api("/api/config");
  } catch (_) { return; }
  $who.replaceChildren(`${ME.name} (${ME.role === "staff" ? "직원" : "고객"}) `,
    h("button", { class: "ghost", onclick: async () => { await api("/api/logout", { method: "POST" }); showLogin(); } }, "로그아웃"));
  ME.role === "staff" ? staffList("rented") : customerList();
}

// ------------------------------------------------------------ shared views
const partName = k => (CFG.parts[k] || { name: k }).name;
const gradeName = g => `${g}등급(${CFG.grades[g].name})`;
const STATUS = { new: "신규 손상", worsened: "기존 흠집 악화", pre_existing: "대여 전부터 있던 흠집 (비청구)" };

function photoImg(id) {
  return id ? h("a", { href: "/api/photos/" + id, target: "_blank", rel: "noopener" },
    h("img", { class: "thumb", src: "/api/photos/" + id, alt: "흠집 사진" })) : null;
}

function pickupTable(list) {
  if (!list.length) return h("p", { class: "muted" }, "대여 전 기록된 흠집 없음");
  return h("table", {}, h("tr", {}, h("th", {}, "부위"), h("th", {}, "등급"), h("th", {}, "메모")),
    list.map(d => h("tr", {}, h("td", {}, partName(d.part)), h("td", {}, gradeName(d.grade)), h("td", {}, d.note))));
}

function invoiceView(r) {
  const i = r.invoice;
  if (!i) return null;
  const dmgRows = r.return_damages.map(d => h("tr", {},
    h("td", {}, partName(d.part), photoImg(d.photo_id)),
    h("td", {}, gradeName(d.grade) + (d.prior_grade ? ` (대여 전 ${d.prior_grade}등급)` : "")),
    h("td", {}, STATUS[d.status] || d.status, d.note ? h("div", { class: "muted" }, d.note) : null),
    h("td", { class: "num" }, won(d.fee))));
  return h("div", { class: "card" }, h("h2", {}, "청구 내역"),
    h("table", {},
      h("tr", {}, h("th", {}, "항목"), h("th", {}, "상세"), h("th", { class: "num" }, "금액")),
      h("tr", {}, h("td", {}, "지연 요금"),
        h("td", {}, i.late_fee ? `${Math.floor(i.late_minutes / 60)}시간 ${i.late_minutes % 60}분 지연` : `지연 없음 (유예 ${CFG.grace_minutes}분)`),
        h("td", { class: "num" }, won(i.late_fee))),
      h("tr", {}, h("td", {}, "연료 요금"),
        h("td", {}, `대여 ${fuelTxt(r.start_fuel)} → 반납 ${fuelTxt(r.return_fuel)}` + (i.fuel_short_units ? ` (${i.fuel_short_units}칸 부족)` : "")),
        h("td", { class: "num" }, won(i.fuel_fee))),
      h("tr", {}, h("td", {}, "손상 요금"), h("td", {}, r.return_damages.length ? `${r.return_damages.length}건 점검` : "손상 없음"),
        h("td", { class: "num" }, won(i.damage_fee)))),
    r.return_damages.length ? h("h3", {}, "흠집 점검 결과") : null,
    r.return_damages.length ? h("table", {},
      h("tr", {}, h("th", {}, "부위"), h("th", {}, "등급"), h("th", {}, "판정"), h("th", { class: "num" }, "청구")), dmgRows) : null,
    h("p", { class: "total" }, "합계 " + won(i.total)));
}

function rentalHeader(r) {
  return h("div", { class: "card" },
    h("h2", {}, `${r.model} · ${r.plate}`),
    h("div", {}, `고객: ${r.customer_name}`),
    h("div", {}, `대여 ${fmt(r.start_at)} → 반납 예정 ${fmt(r.due_at)}`),
    h("div", {}, `대여 시 연료 ${fuelTxt(r.start_fuel)} · 주행거리 ${r.start_odo.toLocaleString()}km · 일 대여료 ${won(r.daily_rate)}`),
    r.status === "returned" ? h("div", {}, `반납 ${fmt(r.returned_at)} · 연료 ${fuelTxt(r.return_fuel)} · ${r.return_odo.toLocaleString()}km (주행 ${(r.return_odo - r.start_odo).toLocaleString()}km)`) : null);
}

function statusBadge(r) {
  if (r.status === "returned") return h("span", { class: "badge ok" }, "반납 완료");
  const late = new Date(r.due_at) < new Date();
  return h("span", { class: "badge " + (late ? "late" : "warn") }, late ? "반납 지연 중" : "대여 중");
}

// ------------------------------------------------------------ customer
async function customerList() {
  const list = await api("/api/rentals");
  $app.replaceChildren(h("div", { class: "card" }, h("h2", {}, "내 대여 내역"),
    list.length ? h("table", {}, h("tr", {}, h("th", {}, "차량"), h("th", {}, "기간"), h("th", {}, "상태"), h("th", { class: "num" }, "청구액"), h("th", {})),
      list.map(r => h("tr", {}, h("td", {}, `${r.model} (${r.plate})`),
        h("td", {}, `${fmt(r.start_at)} ~ ${fmt(r.due_at)}`), h("td", {}, statusBadge(r)),
        h("td", { class: "num" }, r.invoice ? won(r.invoice.total) : "-"),
        h("td", {}, h("button", { class: "ghost", onclick: () => customerDetail(r.id) }, "상세"))))) : h("p", {}, "대여 내역이 없습니다.")));
}

async function customerDetail(id) {
  const r = await api("/api/rentals/" + id);
  $app.replaceChildren(h("button", { class: "ghost", onclick: customerList }, "← 목록"), h("p"),
    rentalHeader(r),
    h("div", { class: "card" }, h("h3", {}, "대여 전부터 있던 흠집 (청구 제외)"), pickupTable(r.pickup_damages)),
    r.invoice ? invoiceView(r) : msg("info", "아직 반납 점검 전이라 청구 내역이 없습니다."));
}

// ------------------------------------------------------------ staff
async function staffList(status) {
  const list = await api("/api/rentals?status=" + status);
  const tab = (s, label) => h("button", { class: status === s ? "on" : "", onclick: () => staffList(s) }, label);
  $app.replaceChildren(h("div", { class: "card" },
    h("div", { class: "row tabs" }, tab("rented", "반납 대기"), tab("returned", "반납 완료")), h("p"),
    list.length ? h("table", {}, h("tr", {}, h("th", {}, "차량"), h("th", {}, "고객"), h("th", {}, "반납 예정"), h("th", {}, "상태"), h("th", { class: "num" }, "청구액"), h("th", {})),
      list.map(r => h("tr", {}, h("td", {}, `${r.model} (${r.plate})`), h("td", {}, r.customer_name),
        h("td", {}, fmt(r.due_at)), h("td", {}, statusBadge(r)),
        h("td", { class: "num" }, r.invoice ? won(r.invoice.total) : "-"),
        h("td", {}, r.status === "rented"
          ? h("button", { onclick: () => returnForm(r.id) }, "반납 점검")
          : h("button", { class: "ghost", onclick: () => staffDetail(r.id) }, "상세"))))) : h("p", {}, "해당하는 건이 없습니다.")));
}

async function staffDetail(id) {
  const r = await api("/api/rentals/" + id);
  $app.replaceChildren(h("button", { class: "ghost", onclick: () => staffList("returned") }, "← 목록"), h("p"),
    rentalHeader(r), h("div", { class: "card" }, h("h3", {}, "대여 전부터 있던 흠집"), pickupTable(r.pickup_damages)), invoiceView(r));
}

function localNow() {
  const d = new Date(); d.setSeconds(0, 0);
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

async function returnForm(id) {
  const r = await api("/api/rentals/" + id);
  if (r.status !== "rented") return staffDetail(id);
  const at = h("input", { type: "datetime-local", value: localNow() });
  const fuel = h("select", {}, [...Array(CFG.fuel_units + 1).keys()].reverse().map(n =>
    h("option", { value: n, selected: n === r.start_fuel }, `${n}/${CFG.fuel_units}` + (n === 0 ? " (빈 탱크)" : n === CFG.fuel_units ? " (만땅)" : ""))));
  const odo = h("input", { type: "number", min: r.start_odo, value: r.start_odo, step: 1 });
  const rows = h("div");
  const out = h("div"), note = h("div");
  const photoIds = new Map();      // row element -> photo id

  function addRow() {
    const part = h("select", {}, Object.entries(CFG.parts).map(([k, v]) => h("option", { value: k }, v.name)));
    const grade = h("select", {}, Object.entries(CFG.grades).map(([k, v]) => h("option", { value: k }, `${k}등급 · ${v.name}`)));
    const memo = h("input", { maxlength: 200, placeholder: "메모 (선택)" });
    const thumb = h("div");
    const file = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp" });
    const row = h("div", { class: "damage-row" },
      h("div", { class: "row" }, part, grade, memo,
        h("button", { class: "danger", onclick: () => { photoIds.delete(row); row.remove(); } }, "삭제")),
      h("div", { class: "row" }, h("span", { class: "muted" }, "사진:"), file), thumb);
    row.read = () => ({ part: part.value, grade: Number(grade.value), note: memo.value, photo_id: photoIds.get(row) ?? null });
    file.addEventListener("change", async () => {
      if (!file.files[0]) return;
      const fd = new FormData(); fd.append("file", file.files[0]);
      thumb.replaceChildren("업로드 중…");
      try {
        const res = await api(`/api/rentals/${id}/photos`, { method: "POST", body: fd });
        photoIds.set(row, res.photo_id);
        thumb.replaceChildren(photoImg(res.photo_id));
      } catch (e) { photoIds.delete(row); thumb.replaceChildren(msg("err", e.message)); }
    });
    rows.append(row);
  }

  const payload = () => ({
    returned_at: at.value || null, return_fuel: Number(fuel.value), return_odo: Number(odo.value),
    damages: [...rows.children].map(x => x.read()),
  });

  function showResult(res, final) {
    const dmg = res.damage_items.map(d => h("tr", {},
      h("td", {}, partName(d.part)), h("td", {}, gradeName(d.grade)),
      h("td", {}, STATUS[d.status]), h("td", { class: "num" }, won(d.fee))));
    out.replaceChildren(h("div", { class: "card" }, h("h2", {}, "예상 청구액"),
      h("table", {},
        h("tr", {}, h("td", {}, "지연 요금"), h("td", {}, res.late_fee ? `${Math.floor(res.late_minutes / 60)}시간 ${res.late_minutes % 60}분 지연` : "지연 없음"), h("td", { class: "num" }, won(res.late_fee))),
        h("tr", {}, h("td", {}, "연료 요금"), h("td", {}, res.fuel_short_units ? `${res.fuel_short_units}칸 부족` : "부족 없음"), h("td", { class: "num" }, won(res.fuel_fee))),
        h("tr", {}, h("td", {}, "손상 요금"), h("td", {}, `${res.damage_items.length}건`), h("td", { class: "num" }, won(res.damage_fee)))),
      dmg.length ? h("table", {}, h("tr", {}, h("th", {}, "부위"), h("th", {}, "등급"), h("th", {}, "판정"), h("th", { class: "num" }, "청구")), dmg) : null,
      h("p", { class: "total" }, "합계 " + won(res.total))));
  }

  const preview = async () => {
    note.replaceChildren();
    try { showResult(await api(`/api/rentals/${id}/preview`, { json: payload() })); }
    catch (e) { note.replaceChildren(msg("err", e.message)); }
  };
  const submit = async btn => {
    note.replaceChildren();
    try {
      const res = await api(`/api/rentals/${id}/preview`, { json: payload() });
      if (!confirm(`반납을 확정하고 ${won(res.total)} 을(를) 청구합니다. 확정 후에는 수정할 수 없습니다.`)) return;
      btn.disabled = true;
      await api(`/api/rentals/${id}/return`, { json: payload() });
      staffDetail(id);
    } catch (e) { btn.disabled = false; note.replaceChildren(msg("err", e.message)); }
  };

  const confirmBtn = h("button", { onclick: () => submit(confirmBtn) }, "반납 확정 · 청구");
  $app.replaceChildren(h("button", { class: "ghost", onclick: () => staffList("rented") }, "← 목록"), h("p"),
    rentalHeader(r),
    h("div", { class: "card" }, h("h3", {}, "대여 전부터 있던 흠집 (청구 제외 기준)"), pickupTable(r.pickup_damages),
      h("p", { class: "muted" }, "같은 부위에 같거나 낮은 등급으로 기록하면 0원, 등급이 올라가면 차액만 청구됩니다.")),
    h("div", { class: "card" }, h("h2", {}, "반납 점검"),
      h("label", {}, "반납 시각"), at,
      h("label", {}, "연료 게이지"), fuel,
      h("label", {}, "주행거리 (km)"), odo,
      h("h3", {}, "흠집 (부위 · 등급 · 사진)"),
      h("p", { class: "muted" }, "대여 전 흠집이 그대로 있으면 같은 부위·등급으로 기록하거나 생략해도 됩니다. 청구되는 흠집은 사진이 필수입니다."),
      rows, h("button", { class: "ghost", onclick: addRow }, "+ 흠집 추가"), h("p"),
      note, h("div", { class: "row" }, h("button", { class: "ghost", onclick: preview }, "요금 계산"), confirmBtn)),
    out);
}

start();
