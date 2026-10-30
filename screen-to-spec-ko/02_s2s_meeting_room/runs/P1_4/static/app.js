"use strict";

const SLOTS = [];
for (let m = 9 * 60; m < 18 * 60; m += 30) SLOTS.push(m);

const state = { users: [], rooms: [], rsvs: [], today: "", serverMinutes: 0, userId: null };

const $ = (id) => document.getElementById(id);
const fmt = (m) => String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
const toMin = (s) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3));

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : "요청을 처리하지 못했습니다.");
  }
  return data;
}

async function loadReservations() {
  const data = await api("/api/reservations");
  state.rsvs = data.reservations;
  state.today = data.today;
  state.serverMinutes = toMin(data.server_time);
  $("today").textContent = data.today;
}

function findRsv(roomId, minutes) {
  return state.rsvs.find(
    (r) => r.room_id === roomId && toMin(r.start_time) <= minutes && minutes < toMin(r.end_time)
  );
}

function renderGrid() {
  const grid = $("grid");
  grid.innerHTML = "";
  const head = grid.createTHead().insertRow();
  head.insertCell().outerHTML = '<th class="time"></th>';
  state.rooms.forEach((room) => {
    head.insertCell().outerHTML = `<th>${room.name}<br><small>정원 ${room.capacity}명</small></th>`;
  });

  const body = grid.createTBody();
  SLOTS.forEach((min) => {
    const tr = body.insertRow();
    tr.insertCell().outerHTML = `<th class="time">${fmt(min)}</th>`;
    state.rooms.forEach((room) => {
      const td = tr.insertCell();
      const rsv = findRsv(room.id, min);
      if (rsv) {
        const mine = rsv.user_id === state.userId;
        td.className = mine ? "mine" : "booked";
        if (toMin(rsv.start_time) === min) {
          td.classList.add("first");
          td.textContent = `${rsv.title} · ${rsv.user_name}`;
        }
        if (toMin(rsv.end_time) === min + 30) td.classList.add("last");
        td.title = `${rsv.start_time}~${rsv.end_time} ${rsv.title} (${rsv.user_name})`;
        td.onclick = () => openDetail(rsv, room);
      } else if (min < state.serverMinutes) {
        td.className = "past";
      } else {
        td.className = "free";
        td.onclick = () => openBooking(room, min);
      }
    });
  });
}

/* ---------- 모달 ---------- */
function showModal(title, bodyNode, buttons) {
  $("modal-title").textContent = title;
  const body = $("modal-body");
  body.innerHTML = "";
  body.appendChild(bodyNode);
  setError("");
  const box = $("modal-buttons");
  box.innerHTML = "";
  buttons.forEach(({ label, cls, onClick }) => {
    const b = document.createElement("button");
    b.textContent = label;
    if (cls) b.className = cls;
    b.onclick = onClick;
    box.appendChild(b);
  });
  $("modal").hidden = false;
}
const closeModal = () => { $("modal").hidden = true; };
function setError(msg) {
  const e = $("modal-error");
  e.textContent = msg;
  e.hidden = !msg;
}

function infoList(rows) {
  const dl = document.createElement("dl");
  rows.forEach(([k, v]) => {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    if (v instanceof Node) dd.appendChild(v); else dd.textContent = v;
    dl.append(dt, dd);
  });
  return dl;
}

function requireUser() {
  if (state.userId == null) {
    $("notice").hidden = false;
    $("notice").scrollIntoView({ block: "nearest" });
    return false;
  }
  return true;
}

function openBooking(room, startMin) {
  if (!requireUser()) return;

  // 종료 시각: 시작+30분 ~ min(시작+2시간, 18:00), 이미 예약된 칸 직전까지만 선택 가능
  const endSel = document.createElement("select");
  for (let end = startMin + 30; end <= Math.min(startMin + 120, 18 * 60); end += 30) {
    if (findRsv(room.id, end - 30)) break;
    endSel.add(new Option(fmt(end), fmt(end)));
  }
  const titleIn = document.createElement("input");
  titleIn.type = "text";
  titleIn.maxLength = 60; // 31자 이상 입력은 서버가 사유와 함께 거절한다
  titleIn.placeholder = "회의 제목 (1~30자)";

  const node = infoList([["회의실", room.name], ["시작", fmt(startMin)], ["종료", endSel], ["제목", titleIn]]);
  showModal("예약", node, [
    { label: "닫기", onClick: closeModal },
    {
      label: "예약", cls: "primary", onClick: async () => {
        try {
          await api("/api/reservations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              room_id: room.id, user_id: state.userId, rsv_date: state.today,
              start_time: fmt(startMin), end_time: endSel.value, title: titleIn.value,
            }),
          });
          closeModal();
          await refresh();
        } catch (e) {
          setError(e.message);
          refresh();
        }
      },
    },
  ]);
  titleIn.focus();
}

function openDetail(rsv, room) {
  const mine = state.userId != null && rsv.user_id === state.userId;
  const node = infoList([
    ["회의실", room.name], ["시간", `${rsv.start_time} ~ ${rsv.end_time}`],
    ["제목", rsv.title], ["예약자", rsv.user_name],
  ]);
  const buttons = [{ label: "닫기", onClick: closeModal }];
  if (mine) {
    buttons.unshift({
      label: "예약 취소", cls: "danger", onClick: async () => {
        try {
          await api(`/api/reservations/${rsv.id}/cancel`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: state.userId }),
          });
          closeModal();
          await refresh();
        } catch (e) {
          setError(e.message);
        }
      },
    });
  }
  showModal(mine ? "예약 취소" : "예약 상세", mine ? wrapWithQuestion(node) : node, buttons);
}

function wrapWithQuestion(node) {
  const wrap = document.createElement("div");
  const q = document.createElement("p");
  q.textContent = "이 예약을 취소할까요?";
  wrap.append(node, q);
  return wrap;
}

/* ---------- 초기화 ---------- */
async function refresh() {
  await loadReservations();
  renderGrid();
}

async function init() {
  [state.users, state.rooms] = await Promise.all([api("/api/users"), api("/api/rooms")]);
  const sel = $("user-select");
  sel.add(new Option("-- 선택 --", ""));
  state.users.forEach((u) => sel.add(new Option(`${u.name} (${u.dept})`, u.id)));

  const saved = Number(localStorage.getItem("mr_user_id"));
  if (state.users.some((u) => u.id === saved)) {
    state.userId = saved;
    sel.value = String(saved);
  }
  $("notice").hidden = state.userId != null;

  sel.onchange = () => {
    state.userId = sel.value ? Number(sel.value) : null;
    if (state.userId == null) localStorage.removeItem("mr_user_id");
    else localStorage.setItem("mr_user_id", String(state.userId));
    $("notice").hidden = state.userId != null;
    renderGrid();
  };
  $("modal").onclick = (e) => { if (e.target === $("modal")) closeModal(); };
  await refresh();
}

init().catch((e) => { document.body.insertAdjacentText("beforeend", "초기화 실패: " + e.message); });
