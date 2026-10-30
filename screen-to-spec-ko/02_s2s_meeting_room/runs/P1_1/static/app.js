const USER_KEY = "mr_user_id";
let data = null;
let userId = null;

const $ = (id) => document.getElementById(id);

function endTime(slot) {
  const [h, m] = slot.split(":").map(Number);
  const t = h * 60 + m + 30;
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = !msg;
}

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  } : undefined);
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : "요청을 처리하지 못했습니다.");
  return json;
}

function confirmDialog(message, okLabel) {
  return new Promise((resolve) => {
    const dlg = $("dlg");
    $("dlg-msg").textContent = message;
    $("dlg-ok").textContent = okLabel;
    const done = (v) => { dlg.close(); resolve(v); };
    $("dlg-ok").onclick = () => done(true);
    $("dlg-close").onclick = () => done(false);
    dlg.oncancel = () => resolve(false);
    dlg.showModal();
  });
}

async function load() {
  data = await api("/api/schedule");
  $("today").textContent = `오늘: ${data.date}`;
  const sel = $("user");
  if (!sel.options.length) {
    data.users.forEach((u) => sel.add(new Option(u.name, u.id)));
    const saved = Number(localStorage.getItem(USER_KEY));
    userId = data.users.some((u) => u.id === saved) ? saved : data.users[0].id;
    sel.value = userId;
    sel.onchange = () => {
      userId = Number(sel.value);
      localStorage.setItem(USER_KEY, userId);
      render();
    };
  }
  render();
}

function th(text) {
  return Object.assign(document.createElement("th"), { textContent: text });
}

function render() {
  const rsvMap = {};
  data.reservations.forEach((r) => (rsvMap[`${r.room_id}|${r.slot_start}`] = r));
  const grid = $("grid");
  grid.replaceChildren();
  const head = grid.insertRow();
  head.appendChild(th("시간"));
  data.rooms.forEach((r) => head.appendChild(th(`회의실 ${r.name}`)));

  data.slots.forEach((slot) => {
    const row = grid.insertRow();
    const timeCell = row.insertCell();
    timeCell.className = "time";
    timeCell.textContent = slot;
    const past = slot < data.now; // 시작 시각이 현재보다 이전이면 지난 칸 (최종 판정은 서버)
    data.rooms.forEach((room) => {
      const td = row.insertCell();
      const rsv = rsvMap[`${room.id}|${slot}`];
      if (rsv) {
        td.textContent = rsv.user_name;
        td.className = rsv.user_id === userId ? "mine" : "other";
      } else {
        td.className = "empty";
      }
      if (past) {
        td.classList.add("past");
        return;
      }
      if (!rsv) td.onclick = () => onEmpty(room, slot);
      else if (rsv.user_id === userId) td.onclick = () => onMine(room, slot, rsv);
    });
  });
}

async function onEmpty(room, slot) {
  showError("");
  if (!(await confirmDialog(`회의실 ${room.name}, ${slot}~${endTime(slot)} 예약할까요?`, "예약"))) return;
  try {
    await api("/api/reservations", { room_id: room.id, user_id: userId, slot_start: slot });
  } catch (e) {
    showError(e.message);
  }
  await load();
}

async function onMine(room, slot, rsv) {
  showError("");
  if (!(await confirmDialog(`회의실 ${room.name}, ${slot}~${endTime(slot)} 예약을 취소할까요?`, "예약 취소"))) return;
  try {
    await api(`/api/reservations/${rsv.id}/cancel`, { user_id: userId });
  } catch (e) {
    showError(e.message);
  }
  await load();
}

load().catch((e) => showError(e.message));
