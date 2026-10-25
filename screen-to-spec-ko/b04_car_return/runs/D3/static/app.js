// DOM은 전부 textContent/createElement로 만들어 서버 데이터가 HTML로 해석되지 않게 한다.
const $app = document.getElementById("app"), $who = document.getElementById("who");
let ME = null, META = null;
const won = n => n.toLocaleString("ko-KR") + "원";
const GRADE = { minor: "경미", major: "중간", severe: "심각" };

function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else if (v !== false && v != null) e[k] = v;
  }
  for (const c of kids.flat()) e.append(c instanceof Node ? c : document.createTextNode(c ?? ""));
  return e;
}

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  if (r.status === 401 && ME) { ME = null; render(); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join("\n") : "요청 실패 (" + r.status + ")");
  }
  return data;
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function render() {
  $app.replaceChildren();
  if (!ME) {
    try { ME = await api("/api/me"); } catch { return loginView(); }
  }
  META = META || await api("/api/meta");
  $who.replaceChildren(`${ME.name} (${ME.role === "staff" ? "직원" : "고객"}) `,
    h("button", { class: "ghost", onclick: async () => { await post("/api/logout", {}); ME = null; render(); } }, "로그아웃"));
  listView();
}

function loginView() {
  $who.replaceChildren();
  const err = h("div", { class: "err" });
  const u = h("input", { autocomplete: "username" }), p = h("input", { type: "password", autocomplete: "current-password" });
  const go = async () => {
    try { await post("/api/login", { username: u.value, password: p.value }); ME = null; render(); }
    catch (e) { err.textContent = e.message; }
  };
  p.addEventListener("keydown", e => e.key === "Enter" && go());
  $app.append(h("div", { class: "card", style: "max-width:360px;margin:40px auto" },
    h("h2", {}, "로그인"), h("label", {}, "아이디"), u, h("label", {}, "비밀번호"), p, err,
    h("button", { onclick: go }, "로그인"),
    h("p", { class: "muted" }, "데모 계정: staff1 / kim / lee / park — 비밀번호 demo1234")));
}

function tag(r) {
  if (r.status === "returned") return h("span", { class: "tag done" }, "반납 완료");
  return h("span", { class: new Date(r.due_at) < new Date() ? "tag late" : "tag" }, new Date(r.due_at) < new Date() ? "반납 예정 지남" : "대여 중");
}

async function listView() {
  $app.replaceChildren(h("div", { class: "muted" }, "불러오는 중…"));
  const rows = await api("/api/rentals");
  const staff = ME.role === "staff";
  $app.replaceChildren(h("div", { class: "card" },
    h("h2", {}, staff ? "대여 건 (전체)" : "내 대여 건"),
    rows.length ? h("table", {},
      h("thead", {}, h("tr", {}, ...[staff ? "고객" : null, "차량", "반납 예정", "상태", "청구액", ""].filter(x => x !== null).map(t => h("th", {}, t)))),
      h("tbody", {}, rows.map(r => h("tr", {},
        staff ? h("td", {}, r.customer) : null,
        h("td", {}, `${r.model} (${r.plate})`),
        h("td", {}, r.due_at.replace("T", " ")),
        h("td", {}, tag(r)),
        h("td", { class: "n" }, r.return ? won(r.return.total) : "-"),
        h("td", {}, h("button", { class: "ghost", onclick: () => detailView(r.id) },
          staff && r.status === "active" ? "반납 점검" : "상세")))))) : h("p", {}, "대여 건이 없습니다.")));
}

function photoImg(id) {
  return h("a", { href: "/api/photos/" + id, target: "_blank", rel: "noopener" }, h("img", { class: "thumb", src: "/api/photos/" + id, alt: "흠집 사진" }));
}

function damageTable(list, title) {
  if (!list.length) return h("p", { class: "muted" }, title + ": 없음");
  return h("div", {}, h("h3", {}, title), h("table", {},
    h("thead", {}, h("tr", {}, ["부위", "등급", "사진", "청구", "비고"].map(t => h("th", {}, t)))),
    h("tbody", {}, list.map(d => h("tr", {},
      h("td", {}, META.parts[d.part]), h("td", {}, GRADE[d.grade]), h("td", {}, photoImg(d.photo_id)),
      h("td", { class: "n" }, d.phase === "checkout" ? "-" : won(d.fee)),
      h("td", {}, d.pre_existing ? (d.note || "대여 전부터 있던 흠집") : d.note))))));
}

function chargeTable(c) {
  return h("table", {},
    h("tbody", {},
      h("tr", {}, h("td", {}, `지연 요금 (${c.late_minutes > 0 ? c.late_minutes + "분 지연" : "지연 없음"})`), h("td", { class: "n" }, won(c.late_fee))),
      h("tr", {}, h("td", {}, `연료 요금 (${c.fuel_short}칸 부족)`), h("td", { class: "n" }, won(c.fuel_fee))),
      h("tr", {}, h("td", {}, "손상 요금"), h("td", { class: "n" }, won(c.damage_fee)))),
    h("tfoot", {}, h("tr", {}, h("th", {}, "총 청구액"), h("th", { class: "n" }, won(c.total)))));
}

async function detailView(id) {
  const r = await api("/api/rentals/" + id);
  const back = h("button", { class: "ghost", onclick: listView }, "← 목록");
  const info = h("div", { class: "card" }, h("h2", {}, `${r.model} (${r.plate}) `, tag(r)),
    h("p", {}, `대여 ${r.start_at.replace("T", " ")} → 반납 예정 ${r.due_at.replace("T", " ")}`),
    h("p", {}, `대여 시 연료 ${r.start_fuel}/8칸 · 주행거리 ${r.start_odometer.toLocaleString()}km`),
    r.customer ? h("p", {}, "고객: " + r.customer) : null,
    damageTable(r.checkout_damages, "대여 전부터 있던 흠집"));
  $app.replaceChildren(back, info);
  if (r.return) {
    $app.append(h("div", { class: "card" }, h("h2", {}, "반납 결과 · 청구 내역"),
      h("p", {}, `반납 ${r.return.returned_at.replace("T", " ")} · 연료 ${r.return.fuel}/8칸 · 주행거리 ${r.return.odometer.toLocaleString()}km`),
      chargeTable(r.return), damageTable(r.return.damages, "반납 시 확인된 흠집")));
  } else if (ME.role === "staff") {
    $app.append(returnForm(r));
  } else {
    $app.append(h("div", { class: "card" }, "아직 반납 전입니다. 반납이 처리되면 청구 내역이 여기에 표시됩니다."));
  }
}

function pad(n) { return String(n).padStart(2, "0"); }
function localNow() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }

function returnForm(r) {
  const err = h("div", { class: "err" }), result = h("div");
  const at = h("input", { type: "datetime-local", value: localNow() });
  const fuel = h("select", {}, [...Array(9).keys()].map(i => h("option", { value: i, selected: i === r.start_fuel }, i + "칸")));
  const odo = h("input", { type: "number", min: r.start_odometer, value: r.start_odometer });
  const dmgBox = h("div"); const items = [];
  let committed = false;

  const addDamage = () => {
    const part = h("select", {}, Object.entries(META.parts).map(([k, v]) => h("option", { value: k }, v)));
    const grade = h("select", {}, Object.keys(GRADE).map(k => h("option", { value: k }, `${GRADE[k]} (${won(META.damage_fee[k])})`)));
    const file = h("input", { type: "file", accept: "image/*", capture: "environment" });
    const status = h("span", { class: "muted" }, "사진 필수");
    const it = { part, grade, photo_id: null };
    file.addEventListener("change", async () => {
      it.photo_id = null; status.textContent = "업로드 중…";
      const fd = new FormData(); fd.append("file", file.files[0]);
      try { it.photo_id = (await api("/api/photos", { method: "POST", body: fd })).photo_id; status.textContent = "✔ 업로드됨"; }
      catch (e) { status.textContent = "✘ " + e.message; }
    });
    const box = h("div", { class: "dmg" }, part, " ", grade, " ", file, " ", status, " ",
      h("button", { class: "ghost", onclick: () => { items.splice(items.indexOf(it), 1); box.remove(); } }, "삭제"));
    items.push(it); dmgBox.append(box);
  };

  const body = () => ({
    returned_at: at.value, fuel: +fuel.value, odometer: +odo.value,
    damages: items.map(i => ({ part: i.part.value, grade: i.grade.value, photo_id: i.photo_id })),
  });
  const confirmBtn = h("button", { disabled: true }, "반납 확정 · 청구");
  const calc = h("button", { class: "ghost", onclick: async () => {
    err.textContent = ""; result.replaceChildren(); confirmBtn.disabled = true;
    try {
      const c = await post(`/api/rentals/${r.id}/return/preview`, body());
      result.append(h("h3", {}, "요금 미리보기"), chargeTable(c), damageTable(c.damages.map(d => ({ ...d, phase: "return" })), "흠집"));
      confirmBtn.disabled = false;
    } catch (e) { err.textContent = e.message; }
  } }, "요금 계산");
  confirmBtn.addEventListener("click", async () => {
    if (committed) return;
    if (!confirm("반납을 확정하고 청구합니다. 되돌릴 수 없습니다.")) return;
    committed = true; confirmBtn.disabled = true;
    try { await post(`/api/rentals/${r.id}/return`, body()); detailView(r.id); }
    catch (e) { committed = false; err.textContent = e.message; }
  });
  // 입력이 바뀌면 이전 미리보기는 무효
  for (const el of [at, fuel, odo, dmgBox]) { el.addEventListener("input", () => { confirmBtn.disabled = true; result.replaceChildren(); }); el.addEventListener("change", () => { confirmBtn.disabled = true; result.replaceChildren(); }); }

  return h("div", { class: "card" }, h("h2", {}, "반납 점검표"),
    h("div", { class: "row" },
      h("div", {}, h("label", {}, "반납 시각"), at),
      h("div", {}, h("label", {}, "연료 게이지 (대여 시 " + r.start_fuel + "칸)"), fuel),
      h("div", {}, h("label", {}, "주행거리 (km)"), odo)),
    h("h3", { style: "margin-top:16px" }, "흠집"),
    h("p", { class: "muted" }, "대여 전 흠집과 같은 부위면 자동으로 0원 처리됩니다. 사진이 없는 흠집은 계산·저장되지 않습니다."),
    dmgBox, h("button", { class: "ghost", onclick: addDamage }, "+ 흠집 추가"),
    err, h("div", { class: "row", style: "margin-top:12px" }, calc, confirmBtn), result);
}

render();
