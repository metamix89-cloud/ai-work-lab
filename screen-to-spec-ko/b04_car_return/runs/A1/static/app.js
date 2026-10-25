"use strict";
const $app = document.getElementById("app");
let me = null, meta = null;

// ---------- 유틸 ----------
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);   // 문자열은 텍스트 노드로 들어가 XSS 안전
  return el;
}
const won = n => n.toLocaleString("ko-KR") + "원";
const when = s => s ? s.replace("T", " ") : "-";
const nowLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const STATUS = { new: ["신규 손상", "b-new"], worse: ["기존 흠집 악화", "b-worse"], existing: ["대여 전 기존 흠집 · 청구 제외", "b-existing"] };

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const res = await fetch("/api" + path, init);
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (res.status === 401 && path !== "/login") { me = null; showLogin(); throw new Error("로그인이 필요합니다."); }
  if (!res.ok) {
    let msg = data?.detail || res.statusText;
    if (Array.isArray(msg)) msg = msg.map(e => e.msg).join("\n");
    throw new Error(msg);
  }
  return data;
}

function photoThumb(name) {
  if (!name) return h("span", { class: "mute" }, "사진 없음");
  const url = "/api/photos/" + name;
  return h("img", { class: "thumb", src: url, alt: "흠집 사진", onclick: () => {
    const v = document.getElementById("viewer"); v.querySelector("img").src = url; v.showModal();
  } });
}
document.getElementById("viewer").addEventListener("click", e => e.currentTarget.close());

// ---------- 로그인 ----------
function showLogin() {
  document.getElementById("who").textContent = "";
  document.getElementById("logout").hidden = true;
  const err = h("div", { class: "err" });
  const u = h("input", { name: "username", autocomplete: "username", required: true });
  const p = h("input", { name: "password", type: "password", autocomplete: "current-password", required: true });
  const form = h("form", { class: "card login", onsubmit: async e => {
    e.preventDefault(); err.textContent = "";
    try { await api("/login", { method: "POST", body: { username: u.value, password: p.value } }); await boot(); }
    catch (ex) { err.textContent = ex.message; }
  } },
    h("h2", {}, "로그인"),
    h("label", {}, "아이디"), u, h("div", { style: "height:8px" }),
    h("label", {}, "비밀번호"), p, err,
    h("button", { class: "primary", style: "width:100%;margin-top:8px" }, "로그인"),
    h("div", { class: "hint" }, "데모 계정 (비밀번호 모두 demo1234)", h("br"),
      "직원: staff · 고객: minsu, jiyeon, hyunwoo"));
  $app.replaceChildren(form);
}
document.getElementById("logout").onclick = async () => { await api("/logout", { method: "POST" }); me = null; showLogin(); };

// ---------- 부팅 ----------
async function boot() {
  try { me = await api("/me"); } catch { return showLogin(); }
  meta = await api("/meta");
  document.getElementById("who").textContent = `${me.name} (${me.role === "staff" ? "직원" : "고객"})`;
  document.getElementById("logout").hidden = false;
  showList();
}

// ---------- 목록 ----------
async function showList(tab = "active") {
  const rentals = await api("/rentals");
  const staff = me.role === "staff";
  const shown = staff ? rentals.filter(r => r.status === tab) : rentals;
  const tabs = staff ? h("div", { class: "row tabs", style: "margin-bottom:10px" },
    ["active", "returned"].map(t => h("button", { class: tab === t ? "on" : "", onclick: () => showList(t) },
      t === "active" ? `대여 중 (${rentals.filter(r => r.status === "active").length})` : "반납 완료")),
    h("span", { style: "flex:1" }),
    h("button", { class: "primary", onclick: showNewRental }, "+ 새 대여 등록")) : null;

  const rows = shown.map(r => h("tr", { class: "list-item", onclick: () => showDetail(r.id) },
    h("td", {}, "#" + r.id),
    staff ? h("td", {}, r.customer) : null,
    h("td", {}, `${r.vehicle.model} (${r.vehicle.plate})`),
    h("td", {}, when(r.start_at)),
    h("td", {}, when(r.status === "returned" ? r.returned_at : r.due_at)),
    h("td", {}, h("span", { class: "badge " + (r.status === "active" ? "b-active" : "b-returned") },
      r.status === "active" ? "대여 중" : "반납 완료")),
    h("td", { class: "num" }, r.invoice ? won(r.invoice.total) : "-")));

  $app.replaceChildren(
    h("div", { class: "card" },
      h("h2", {}, staff ? "대여 건 목록" : "내 대여 내역"), tabs,
      shown.length ? h("table", {},
        h("thead", {}, h("tr", {}, ["번호", staff ? "고객" : null, "차량", "대여 시작", "반납(예정)", "상태", "청구액"]
          .filter(Boolean).map((t, i, a) => h("th", { class: i === a.length - 1 ? "num" : "" }, t)))),
        h("tbody", {}, rows)) : h("div", { class: "mute" }, "표시할 대여 건이 없습니다.")));
}

// ---------- 상세 ----------
function damageTable(list, { withFee }) {
  if (!list.length) return h("div", { class: "mute" }, "기록된 흠집 없음");
  return h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "부위"), h("th", {}, "등급"), h("th", {}, "메모"), h("th", {}, "사진"),
      withFee ? h("th", {}, "판정") : null, withFee ? h("th", { class: "num" }, "청구") : null)),
    h("tbody", {}, list.map(d => h("tr", {},
      h("td", {}, d.part), h("td", {}, `${d.grade}등급 ${meta.grades[d.grade].label}`), h("td", {}, d.note || "-"),
      h("td", {}, photoThumb(d.photo)),
      withFee ? h("td", {}, h("span", { class: "badge " + STATUS[d.status][1] }, STATUS[d.status][0])) : null,
      withFee ? h("td", { class: "num" }, won(d.fee)) : null))));
}

function invoiceView(r) {
  const i = r.invoice;
  if (!i) return h("div", { class: "mute" }, "아직 반납 처리 전이라 청구 내역이 없습니다.");
  const lateTxt = i.late_minutes ? `${Math.floor(i.late_minutes / 60)}시간 ${i.late_minutes % 60}분 초과` +
    (i.late_fee ? "" : ` (유예 ${meta.policy.grace_minutes}분 이내)`) : "정시 반납";
  const fuelTxt = i.fuel_short ? `${i.fuel_short}/8칸 부족 (${r.start_fuel}/8 → ${r.return_fuel}/8)` : `기준 이상 (${r.return_fuel}/8)`;
  const row = (a, b, c) => h("tr", {}, h("td", {}, a), h("td", { class: "mute" }, b), h("td", { class: "num" }, won(c)));
  return h("div", {},
    h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "항목"), h("th", {}, "내용"), h("th", { class: "num" }, "금액"))),
      h("tbody", {}, row("지연 요금", lateTxt, i.late_fee), row("연료 요금", fuelTxt, i.fuel_fee),
        row("손상 요금", r.return_damages.some(d => d.fee) ? "아래 흠집 표 참고" : "청구 대상 없음", i.damage_fee))),
    h("div", { class: "row", style: "justify-content:flex-end;margin-top:10px" },
      h("span", { class: "total" }, "총 청구액 " + won(i.total))));
}

async function showDetail(id) {
  const r = await api("/rentals/" + id);
  const staff = me.role === "staff";
  const info = [
    ["고객", r.customer], ["차량", `${r.vehicle.model} (${r.vehicle.plate})`], ["대여 시작", when(r.start_at)],
    ["반납 예정", when(r.due_at)], ["반납 시각", when(r.returned_at)], ["일 요금", won(r.daily_rate)],
    ["연료 (대여 시)", `${r.start_fuel}/8`], ["주행거리 (대여 시)", r.start_odometer.toLocaleString() + " km"],
    r.status === "returned" ? ["연료 (반납 시)", `${r.return_fuel}/8`] : null,
    r.status === "returned" ? ["주행거리 (반납 시)", `${r.return_odometer.toLocaleString()} km (+${(r.return_odometer - r.start_odometer).toLocaleString()})`] : null,
  ].filter(Boolean);
  $app.replaceChildren(
    h("button", { onclick: () => showList(r.status), style: "margin-bottom:10px" }, "← 목록"),
    h("div", { class: "card" },
      h("h2", {}, `대여 #${r.id} `, h("span", { class: "badge " + (r.status === "active" ? "b-active" : "b-returned") },
        r.status === "active" ? "대여 중" : "반납 완료")),
      h("div", { class: "grid" }, info.map(([k, v]) => h("div", {}, h("label", {}, k), v)))),
    h("div", { class: "card" }, h("h2", {}, "대여 전부터 있던 흠집"),
      h("div", { class: "mute", style: "margin-bottom:6px" }, "대여 시작 시점에 고정된 기록이며, 이 흠집은 청구되지 않습니다."),
      damageTable(r.pickup_damages, { withFee: false })),
    r.status === "returned" ? h("div", { class: "card" }, h("h2", {}, "반납 시 확인된 흠집"),
      damageTable(r.return_damages, { withFee: true })) : null,
    r.status === "returned" ? h("div", { class: "card" }, h("h2", {}, "청구 내역"), invoiceView(r)) : null,
    r.status === "active" && staff ? returnForm(r) : null,
    r.status === "active" && !staff ? h("div", { class: "card mute" }, "아직 반납 전입니다. 반납이 처리되면 청구 내역이 여기에 표시됩니다.") : null);
}

// ---------- 반납 점검표 (직원) ----------
function returnForm(r) {
  const err = h("div", { class: "err" });
  const result = h("div", {});
  const at = h("input", { type: "datetime-local", value: nowLocal(), required: true });
  const fuel = h("select", {}, Array.from({ length: meta.policy.fuel_levels + 1 }, (_, i) =>
    h("option", { value: i, selected: i === r.start_fuel }, `${i}/8` + (i === 0 ? " (빈 탱크)" : i === 8 ? " (만땅)" : ""))));
  const odo = h("input", { type: "number", min: r.start_odometer, step: 1, value: r.start_odometer, required: true });
  const list = h("div", {});
  let timer = null, busy = false;

  const collect = () => ({
    returned_at: at.value, fuel: +fuel.value, odometer: +odo.value,
    damages: [...list.children].map(el => el._get()),
  });
  const refresh = () => { clearTimeout(timer); timer = setTimeout(preview, 300); };

  async function preview() {
    err.textContent = "";
    try {
      const c = await api(`/rentals/${r.id}/preview`, { method: "POST", body: collect() });
      result.replaceChildren(
        h("table", {}, h("tbody", {},
          h("tr", {}, h("td", {}, "지연 요금"), h("td", { class: "mute" }, c.late_minutes ? `${c.late_minutes}분 초과` : "정시"), h("td", { class: "num" }, won(c.late_fee))),
          h("tr", {}, h("td", {}, "연료 요금"), h("td", { class: "mute" }, c.fuel_short ? `${c.fuel_short}/8칸 부족` : "-"), h("td", { class: "num" }, won(c.fuel_fee))),
          h("tr", {}, h("td", {}, "손상 요금"), h("td", { class: "mute" }, c.damages.map(d => `${d.part}: ${STATUS[d.status][0]}`).join(" / ") || "-"), h("td", { class: "num" }, won(c.damage_fee))))),
        h("div", { class: "total", style: "text-align:right;margin-top:8px" }, "예상 청구액 " + won(c.total)));
      return c;
    } catch (ex) { result.replaceChildren(); err.textContent = ex.message; return null; }
  }

  function addDamage() {
    const part = h("select", {}, meta.parts.map(p => h("option", {}, p)));
    const grade = h("select", {}, Object.entries(meta.grades).map(([g, v]) =>
      h("option", { value: g }, `${g}등급 ${v.label} (${won(v.fee)})`)));
    const note = h("input", { placeholder: "상태 메모", maxlength: 200, style: "width:100%" });
    const prev = h("div", {});
    let photo = null;
    const file = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", onchange: async () => {
      if (!file.files[0]) return;
      const fd = new FormData(); fd.append("file", file.files[0]);
      try { photo = (await api("/photos", { method: "POST", body: fd })).photo; prev.replaceChildren(photoThumb(photo)); err.textContent = ""; }
      catch (ex) { photo = null; prev.replaceChildren(); file.value = ""; err.textContent = ex.message; }
      refresh();
    } });
    const el = h("div", { class: "dmg" },
      h("div", { class: "row" },
        h("div", {}, h("label", {}, "부위"), part), h("div", {}, h("label", {}, "등급"), grade),
        h("div", {}, h("label", {}, "사진"), file), prev, h("span", { style: "flex:1" }),
        h("button", { type: "button", class: "danger", onclick: () => { el.remove(); refresh(); } }, "삭제")),
      h("div", { style: "margin-top:8px" }, note));
    el._get = () => ({ part: part.value, grade: +grade.value, note: note.value, photo });
    for (const x of [part, grade, note]) x.addEventListener("input", refresh);
    list.append(el); refresh();
  }

  for (const x of [at, fuel, odo]) x.addEventListener("input", refresh);
  setTimeout(preview, 0);

  return h("form", { class: "card", onsubmit: async e => {
    e.preventDefault();
    if (busy) return;
    const c = await preview();
    if (!c || !confirm(`반납을 확정하고 ${won(c.total)}을 청구합니다. 확정 후에는 수정할 수 없습니다.`)) return;
    busy = true;
    try { await api(`/rentals/${r.id}/return`, { method: "POST", body: collect() }); await showDetail(r.id); }
    catch (ex) { err.textContent = ex.message; busy = false; }
  } },
    h("h2", {}, "반납 점검표"),
    h("div", { class: "grid" },
      h("div", {}, h("label", {}, "반납 시각"), at),
      h("div", {}, h("label", {}, "연료 게이지"), fuel),
      h("div", {}, h("label", {}, `주행거리 (km) · 대여 시 ${r.start_odometer.toLocaleString()}`), odo)),
    h("h3", {}, "반납 시 확인한 흠집"),
    h("div", { class: "mute" }, "대여 전부터 있던 흠집을 다시 적어도 청구되지 않습니다. 같은 부위의 등급이 올라간 경우 차액만 청구됩니다."),
    list,
    h("button", { type: "button", onclick: addDamage }, "+ 흠집 추가"),
    h("h3", {}, "요금 미리보기"), result, err,
    h("div", { class: "row", style: "justify-content:flex-end;margin-top:10px" },
      h("button", { class: "primary" }, "반납 확정 · 청구서 발행")));
}

// ---------- 새 대여 등록 (직원) ----------
async function showNewRental() {
  const opt = await api("/staff/options");
  const err = h("div", { class: "err" });
  const cust = h("select", {}, opt.customers.map(c => h("option", { value: c.id }, `${c.name} (${c.username})`)));
  const veh = h("select", {}, opt.vehicles.map(v => h("option", { value: v.id }, `${v.model} ${v.plate} · ${won(v.daily_rate)}/일 · ${v.odometer.toLocaleString()}km`)));
  const due = h("input", { type: "datetime-local", required: true });
  const d = new Date(); d.setDate(d.getDate() + 1); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  due.value = d.toISOString().slice(0, 16);
  const fuel = h("select", {}, Array.from({ length: 9 }, (_, i) => h("option", { value: i, selected: i === 8 }, `${i}/8`)));
  $app.replaceChildren(
    h("button", { onclick: () => showList(), style: "margin-bottom:10px" }, "← 목록"),
    h("form", { class: "card", onsubmit: async e => {
      e.preventDefault(); err.textContent = "";
      try {
        const res = await api("/rentals", { method: "POST", body: { user_id: +cust.value, vehicle_id: +veh.value, due_at: due.value, start_fuel: +fuel.value } });
        showDetail(res.id);
      } catch (ex) { err.textContent = ex.message; }
    } },
      h("h2", {}, "새 대여 등록"),
      opt.vehicles.length ? null : h("div", { class: "err" }, "대여 가능한 차량이 없습니다."),
      h("div", { class: "grid" }, h("div", {}, h("label", {}, "고객"), cust), h("div", {}, h("label", {}, "차량"), veh),
        h("div", {}, h("label", {}, "반납 예정"), due), h("div", {}, h("label", {}, "인도 시 연료"), fuel)),
      h("div", { class: "mute", style: "margin-top:8px" }, "등록 시 차량에 기록된 모든 흠집이 '대여 전 흠집'으로 고정되어 청구에서 제외됩니다."),
      err, h("button", { class: "primary", disabled: !opt.vehicles.length, style: "margin-top:8px" }, "대여 시작")));
}

boot();
