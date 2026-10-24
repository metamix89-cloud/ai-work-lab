const app = document.getElementById("app");
let token = sessionStorage.getItem("token");

// 요소 생성 헬퍼: 텍스트는 textContent로만 넣어 XSS를 피한다.
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
function show(...nodes) { app.replaceChildren(...nodes); }

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/login") { logout(); throw new Error("세션이 만료되었습니다."); }
  if (!res.ok) throw new Error(data.detail || "오류가 발생했습니다.");
  return data;
}

function logout() {
  token = null; sessionStorage.removeItem("token");
  document.getElementById("who").hidden = true;
  renderLogin();
}
document.getElementById("logout").onclick = logout;

function setWho(u) {
  document.getElementById("who").hidden = false;
  document.getElementById("whoText").textContent = `${u.dept} ${u.name} (${u.emp_no})`;
}

// ------------------------------------------------------------ 로그인
function renderLogin() {
  const input = h("input", { type: "text", placeholder: "사번 (예: N2026005)", autofocus: true });
  const err = h("div", { class: "err" });
  const go = async () => {
    try {
      const r = await api("/login", { method: "POST", body: { emp_no: input.value } });
      token = r.token; sessionStorage.setItem("token", token);
      boot();
    } catch (e) { err.textContent = e.message; }
  };
  input.addEventListener("keydown", e => e.key === "Enter" && go());
  const demo = (label, no) => h("code", { onclick: () => { input.value = no; go(); } }, no);
  show(h("div", { class: "card" },
    h("h2", {}, "로그인"),
    h("p", { class: "muted" }, "사번으로 로그인하세요."),
    h("div", { class: "row" }, input, h("button", { onclick: go }, "시작하기")),
    err,
    h("div", { class: "demo" }, "데모 계정(클릭): 신입 ", demo("", "N2026005"), " ", demo("", "N2026007"),
      " ", demo("", "N2026012"), " · 인사팀 ", demo("", "H0001"))));
}

async function boot() {
  if (!token) return renderLogin();
  try {
    const me = await api("/me");
    setWho(me.user);
    me.user.role === "hr" ? renderHR() : renderHome(me);
  } catch { renderLogin(); }
}

// ------------------------------------------------------------ 교육생
function renderHome(me) {
  const st = me.status;
  const pct = Math.round(st.lessons_done * 100 / st.lessons_total);
  const banner = st.completed
    ? h("div", { class: "card" }, h("span", { class: "badge ok" }, "수료"), " 축하합니다! 온보딩 교육을 수료했습니다. (최고 점수 " + st.best_score + "점)")
    : null;
  const lessons = me.lessons.map(l => h("div", { class: "lesson" + (l.done ? " done" : "") + (l.locked ? " locked" : "") },
    h("div", { class: "no" }, l.done ? "✓" : String(l.seq)),
    h("div", { class: "t" }, h("b", {}, l.title), h("div", { class: "muted" }, `약 ${l.minutes}분`)),
    h("button", { disabled: l.locked, class: l.done ? "ghost" : "", onclick: () => renderLesson(l.seq) },
      l.done ? "다시 보기" : l.locked ? "잠김" : "학습하기")));
  const quizBtn = h("button", { disabled: !me.quiz_open, onclick: renderQuiz },
    st.attempts ? "퀴즈 다시 풀기" : "퀴즈 풀기");
  show(
    banner,
    h("div", { class: "card" },
      h("h2", {}, `${me.user.name}님, 환영합니다 👋`),
      h("div", { class: "muted" }, `레슨 ${st.lessons_done}/${st.lessons_total} 완료`),
      h("div", { class: "bar" }, h("div", { style: `width:${pct}%` }))),
    h("div", { class: "card" }, h("h3", {}, "레슨 (순서대로 학습)"), lessons),
    h("div", { class: "card" },
      h("h3", {}, "최종 퀴즈"),
      h("p", { class: "muted" }, `5문항, ${me.pass_score}점 이상이면 수료입니다. 모든 레슨을 완료하면 열립니다.` +
        (st.last_score != null ? ` (최근 점수 ${st.last_score}점, ${st.attempts}회 응시)` : "")),
      quizBtn));
}

async function renderLesson(seq) {
  try {
    const l = await api("/lessons/" + seq);
    const err = h("div", { class: "err" });
    const done = h("button", {
      onclick: async () => {
        try { await api(`/lessons/${seq}/complete`, { method: "POST" }); boot(); }
        catch (e) { err.textContent = e.message; }
      }
    }, l.done ? "확인 (이미 완료)" : "학습 완료");
    show(h("div", { class: "card" },
      h("div", { class: "muted" }, `레슨 ${l.seq}/4 · 약 ${l.minutes}분`),
      h("h2", {}, l.title),
      h("div", { class: "content" }, l.content),
      h("div", { class: "row", style: "margin-top:20px" },
        h("button", { class: "ghost", onclick: boot }, "← 목록"), done), err));
  } catch (e) { alert(e.message); boot(); }
}

async function renderQuiz() {
  try {
    const quiz = await api("/quiz");
    const picked = {};
    const err = h("div", { class: "err" });
    const qs = quiz.questions.map((q, i) => h("div", { class: "q" },
      h("b", {}, `${i + 1}. ${q.question}`),
      q.options.map((o, j) => h("label", {},
        h("input", { type: "radio", name: "q" + q.id, onchange: () => (picked[q.id] = j) }), " " + o))));
    const submit = h("button", {
      onclick: async () => {
        if (Object.keys(picked).length < quiz.questions.length) { err.textContent = "모든 문항에 답해 주세요."; return; }
        try { renderResult(await api("/quiz/submit", { method: "POST", body: { answers: picked } })); }
        catch (e) { err.textContent = e.message; }
      }
    }, "제출");
    show(h("div", { class: "card" }, h("h2", {}, "최종 퀴즈"), qs,
      h("div", { class: "row" }, h("button", { class: "ghost", onclick: boot }, "← 목록"), submit), err));
  } catch (e) { alert(e.message); boot(); }
}

function renderResult(r) {
  show(h("div", { class: "card result" },
    h("div", { class: "score", style: `color:var(--${r.passed ? "ok" : "bad"})` }, r.score + "점"),
    h("p", {}, `${r.total}문항 중 ${r.correct}문항 정답`),
    h("h2", {}, r.passed ? "🎉 수료했습니다!" : `기준 점수(${r.pass_score}점)에 미달입니다. 다시 도전해 보세요.`),
    h("button", { onclick: boot }, "처음으로")));
}

// ------------------------------------------------------------ 인사팀
async function renderHR() {
  const data = await api("/hr/overview");
  const s = data.summary;
  let onlyIncomplete = true;
  const tbody = h("tbody");
  const toggle = h("button", { class: "ghost" });
  const draw = () => {
    toggle.textContent = onlyIncomplete ? "전체 보기" : "미수료자만 보기";
    const rows = data.employees.filter(e => !onlyIncomplete || !e.completed)
      .sort((a, b) => b.days_since_start - a.days_since_start);
    tbody.replaceChildren(...rows.map(e => h("tr", {},
      h("td", {}, e.name), h("td", {}, e.emp_no), h("td", {}, e.dept),
      h("td", {}, `${e.start_date} (D+${e.days_since_start})`),
      h("td", {}, `${e.lessons_done}/${e.lessons_total}`),
      h("td", {}, e.last_score == null ? "-" : `${e.last_score}점 (${e.attempts}회)`),
      h("td", {}, h("span", { class: "badge " + (e.completed ? "ok" : e.state === "미시작" ? "bad" : "warn") }, e.state)))));
    if (!rows.length) tbody.append(h("tr", {}, h("td", { colspan: 7, class: "muted" }, "해당하는 직원이 없습니다.")));
  };
  toggle.onclick = () => { onlyIncomplete = !onlyIncomplete; draw(); };
  const stat = (n, label) => h("div", { class: "stat" }, h("b", {}, String(n)), h("span", { class: "muted" }, label));
  show(
    h("div", { class: "stats" }, stat(s.total, "전체 신입"), stat(s.completed, "수료"), stat(s.incomplete, "미수료"), stat(s.rate + "%", "수료율")),
    h("div", { class: "card" },
      h("div", { class: "row", style: "justify-content:space-between;margin-bottom:10px" },
        h("h3", { style: "margin:0" }, "교육 현황"), toggle),
      h("table", {}, h("thead", {}, h("tr", {}, ["이름", "사번", "부서", "입사일", "레슨", "최근 퀴즈", "상태"].map(t => h("th", {}, t)))), tbody)));
  draw();
}

boot();
