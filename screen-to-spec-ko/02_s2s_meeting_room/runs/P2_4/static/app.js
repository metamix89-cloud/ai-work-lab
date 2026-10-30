(function () {
  const OPEN = 9 * 60, CLOSE = 18 * 60, STEP = 30, MAX_LEN = 120;
  const NET_ERR = "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.";
  const LS_KEY = "mr_user_id";

  const $ = (id) => document.getElementById(id);
  const state = { users: [], rooms: [], rsvs: [], now: null, userId: null };

  const toMin = (s) => parseInt(s.slice(0, 2), 10) * 60 + parseInt(s.slice(3), 10);
  const toStr = (m) => String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  async function api(method, path, body) {
    let res;
    try {
      res = await fetch(path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      const err = new Error(NET_ERR);
      err.status = 0;
      throw err;
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
    if (!res.ok) {
      const err = new Error((data && typeof data.detail === "string" && data.detail) ||
        "일시적인 오류입니다. 잠시 후 다시 시도해 주세요.");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  /* ---------- 사용자 선택 ---------- */
  function renderUserSelect() {
    const sel = $("user-select");
    sel.textContent = "";
    const ph = el("option", "", "이름을 선택하세요");
    ph.value = "";
    sel.appendChild(ph);
    state.users.forEach((u) => {
      const o = el("option", "", u.name + " (" + (u.dept || "-") + ")");
      o.value = String(u.id);
      sel.appendChild(o);
    });
    sel.value = state.userId ? String(state.userId) : "";
    $("user-notice").hidden = !!state.userId;
  }

  function setUser(id) {
    state.userId = id || null;
    if (id) localStorage.setItem(LS_KEY, String(id));
    else localStorage.removeItem(LS_KEY);
    renderUserSelect();
    renderBoard();
  }

  /* ---------- 시간표 ---------- */
  async function load() {
    $("board-msg").hidden = true;
    $("board").textContent = "";
    $("board").appendChild(el("p", "board-msg", "불러오는 중…"));
    try {
      const [users, rooms, rsvs, now] = await Promise.all([
        api("GET", "/api/users"), api("GET", "/api/rooms"),
        api("GET", "/api/reservations"), api("GET", "/api/now"),
      ]);
      if (!rooms.length) throw new Error("no rooms");
      state.users = users; state.rooms = rooms; state.rsvs = rsvs; state.now = now;
    } catch (e) {
      showLoadError();
      return false;
    }
    $("today").textContent = state.now.date;
    const saved = parseInt(localStorage.getItem(LS_KEY), 10);
    state.userId = state.users.some((u) => u.id === saved) ? saved : null;
    if (!state.userId) localStorage.removeItem(LS_KEY);
    renderUserSelect();
    renderBoard();
    return true;
  }

  // 모달이 열려 있는 동안 시간표만 조용히 다시 불러온다.
  async function refresh() {
    try {
      const [rsvs, now] = await Promise.all([api("GET", "/api/reservations"), api("GET", "/api/now")]);
      state.rsvs = rsvs; state.now = now;
      renderBoard();
    } catch (e) {
      /* 모달 안 오류가 우선이므로 무시 */
    }
  }

  function showLoadError() {
    const b = $("board");
    b.textContent = "";
    $("board-msg").hidden = true;
    b.appendChild(el("p", "board-msg", "회의실 정보를 불러오지 못했습니다."));
    const btn = el("button", "btn", "다시 시도");
    btn.addEventListener("click", load);
    b.appendChild(btn);
  }

  function renderBoard() {
    const nowMin = toMin(state.now.time);
    const b = $("board");
    b.textContent = "";

    const msg = $("board-msg");
    const allPast = nowMin > CLOSE - STEP; // 마지막 칸(17:30)도 시작이 지남
    if (allPast) {
      msg.textContent = "오늘 예약 가능한 시간이 끝났습니다.";
      msg.className = "board-msg ended"; msg.hidden = false;
    } else if (!state.rsvs.length) {
      msg.textContent = "오늘 예약이 없습니다. 빈 칸을 눌러 예약하세요.";
      msg.className = "board-msg"; msg.hidden = false;
    } else {
      msg.hidden = true;
    }

    const grid = el("div", "grid");
    grid.style.gridTemplateColumns = "70px repeat(" + state.rooms.length + ", 1fr)";
    const corner = el("div", "head", "시간");
    corner.style.gridRow = 1; corner.style.gridColumn = 1;
    grid.appendChild(corner);
    state.rooms.forEach((r, ci) => {
      const h = el("div", "head", r.name + (r.capacity ? " (" + r.capacity + "명)" : ""));
      h.style.gridRow = 1; h.style.gridColumn = ci + 2;
      grid.appendChild(h);
    });

    for (let m = OPEN, ri = 0; m < CLOSE; m += STEP, ri++) {
      const t = el("div", "time", toStr(m));
      t.style.gridRow = ri + 2; t.style.gridColumn = 1;
      grid.appendChild(t);
    }

    state.rooms.forEach((room, ci) => {
      const mine = state.rsvs.filter((x) => x.room_id === room.id);
      const covered = new Set();
      mine.forEach((x) => {
        const s = toMin(x.start_time), e = toMin(x.end_time);
        for (let m = s; m < e; m += STEP) covered.add(m);
        const ended = e <= nowMin;
        const own = x.user_id === state.userId;
        const cell = el("button", "cell " + (own ? "mine" : "booked") + (ended ? " past" : ""));
        cell.type = "button";
        cell.style.gridColumn = ci + 2;
        cell.style.gridRow = (s - OPEN) / STEP + 2 + " / span " + (e - s) / STEP;
        cell.appendChild(el("span", "t", x.title));
        cell.appendChild(el("span", "n", x.user_name));
        cell.addEventListener("click", () => onReservationClick(x, room, ended, own));
        grid.appendChild(cell);
      });
      for (let m = OPEN, ri = 0; m < CLOSE; m += STEP, ri++) {
        if (covered.has(m)) continue;
        const past = m < nowMin;
        const cell = el("button", "cell " + (past ? "past" : "free"));
        cell.type = "button";
        cell.style.gridColumn = ci + 2; cell.style.gridRow = ri + 2;
        if (past) cell.disabled = true;
        else cell.addEventListener("click", () => onFreeClick(room, m));
        grid.appendChild(cell);
      }
    });
    b.appendChild(grid);
  }

  /* ---------- 모달 공통 ---------- */
  function openModal(title, bodyNode, buttons) {
    $("modal-title").textContent = title;
    const body = $("modal-body");
    body.textContent = "";
    body.appendChild(bodyNode);
    setModalError("");
    const bar = $("modal-buttons");
    bar.textContent = "";
    buttons.forEach((b) => bar.appendChild(b));
    $("modal").hidden = false;
  }
  function closeModal() { $("modal").hidden = true; }
  function setModalError(text) {
    const p = $("modal-error");
    p.textContent = text;
    p.hidden = !text;
  }
  function button(label, cls, handler) {
    const b = el("button", "btn " + (cls || ""), label);
    b.type = "button";
    b.addEventListener("click", handler);
    return b;
  }
  function detailList(rows) {
    const dl = el("dl");
    rows.forEach(([k, v]) => { dl.appendChild(el("dt", "", k)); dl.appendChild(el("dd", "", v)); });
    return dl;
  }

  /* ---------- 예약 창 ---------- */
  function onFreeClick(room, startMin) {
    if (!state.userId) return; // 안내 띠가 이미 보임
    const wrap = el("div");
    const roomIn = el("input"); roomIn.value = room.name; roomIn.readOnly = true;
    const startIn = el("input"); startIn.value = toStr(startMin); startIn.readOnly = true;
    const endSel = el("select");
    for (let m = startMin + STEP; m <= Math.min(startMin + MAX_LEN, CLOSE); m += STEP) {
      const o = el("option", "", toStr(m)); o.value = toStr(m); endSel.appendChild(o);
    }
    const titleIn = el("input"); titleIn.maxLength = 30; titleIn.placeholder = "회의 제목";
    const count = el("div", "count", "0/30");
    titleIn.addEventListener("input", () => { count.textContent = titleIn.value.length + "/30"; });
    [["회의실", roomIn], ["시작 시각", startIn], ["종료 시각", endSel], ["제목", titleIn]].forEach(([l, inp]) => {
      wrap.appendChild(el("label", "", l));
      wrap.appendChild(inp);
    });
    wrap.appendChild(count);

    const submit = button("예약", "primary", async () => {
      submit.disabled = true;
      setModalError("");
      try {
        await api("POST", "/api/reservations", {
          user_id: state.userId, room_id: room.id, rsv_date: state.now.date,
          start_time: toStr(startMin), end_time: endSel.value, title: titleIn.value,
        });
        closeModal();
        await refresh();
      } catch (e) {
        setModalError(e.message);
        if (e.status === 409 || e.status === 404) refresh();
        if (e.status === 403) { closeModal(); setUser(null); }
        submit.disabled = false;
      }
    });
    openModal("회의실 예약", wrap, [submit, button("닫기", "", closeModal)]);
    titleIn.focus();
  }

  /* ---------- 상세 / 취소 창 ---------- */
  function onReservationClick(x, room, ended, own) {
    const rows = [
      ["회의실", room.name],
      ["시간", x.start_time + " ~ " + x.end_time],
      ["제목", x.title],
    ];
    const close = button("닫기", "", closeModal);
    if (!own || ended) {
      rows.push(["예약자", x.user_name]);
      openModal("예약 상세", detailList(rows), [close]);
      return;
    }
    if (!state.userId) return;
    const wrap = el("div");
    wrap.appendChild(detailList(rows));
    wrap.appendChild(el("p", "", "이 예약을 취소할까요?"));
    const cancel = button("예약 취소", "danger", async () => {
      cancel.disabled = true;
      setModalError("");
      try {
        await api("POST", "/api/reservations/" + x.id + "/cancel", { user_id: state.userId });
        closeModal();
        await refresh();
      } catch (e) {
        setModalError(e.message);
        if ([403, 404, 409].includes(e.status)) refresh();
        cancel.disabled = false;
      }
    });
    openModal("예약 취소", wrap, [cancel, close]);
  }

  $("user-select").addEventListener("change", (e) => {
    const v = parseInt(e.target.value, 10);
    setUser(Number.isNaN(v) ? null : v);
  });
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) closeModal(); });

  load();
})();
