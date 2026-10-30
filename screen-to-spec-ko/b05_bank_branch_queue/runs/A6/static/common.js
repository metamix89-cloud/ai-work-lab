// Shared helpers. All dynamic text is inserted with textContent (never innerHTML).
async function api(path, opts = {}, pin = "") {
  const headers = { "Content-Type": "application/json" };
  if (pin) headers["X-Pin"] = pin;
  const res = await fetch(path, { ...opts, headers });
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map(x => (x.msg || "").replace(/^Value error, /, "")).join(" / ");
    const err = new Error(d || "요청 실패 (" + res.status + ")");
    err.status = res.status;
    throw err;
  }
  return data;
}

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function showMsg(box, text, ok) {
  box.textContent = text;
  box.className = "msg " + (ok ? "ok" : "err");
}

const KIND = { reservation: "예약", walkin: "현장" };
const STATUS = { reserved: "예약(미도착)", waiting: "대기", called: "호출됨", serving: "상담중", done: "완료", noshow: "노쇼" };
const hhmm = s => (s ? s.slice(11, 16) : "-");

function kindBadge(kind) {
  return el("span", KIND[kind], "badge" + (kind === "reservation" ? " resv" : ""));
}
