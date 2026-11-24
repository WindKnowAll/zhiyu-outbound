const scenarioEl = document.getElementById("scenario");
const linesEl = document.getElementById("lines");
const bannerEl = document.getElementById("banner");
const waitEl = document.getElementById("wait");
const draftEl = document.getElementById("draft");
const sendEl = document.getElementById("send");
const beginEl = document.getElementById("begin");
const endEl = document.getElementById("end");
const randomEl = document.getElementById("random");
const endedEl = document.getElementById("ended-note");
const guideEl = document.getElementById("ended-guide");

let sessionId = "";
let linkedSession = "";
let callGate = false;
let composer = ZhiyuDebug.initial();

function applyComposer(next) {
  composer = next;
  draftEl.disabled = !composer.enabled;
  sendEl.disabled = !composer.enabled;
  const ended = composer.note === "电话已结束";
  endedEl.hidden = !ended;
  guideEl.hidden = !ended;
  if (ended) waitEl.textContent = "";
}

function setBanner(text, ok) {
  if (!text) {
    bannerEl.hidden = true;
    bannerEl.textContent = "";
    return;
  }
  bannerEl.hidden = false;
  bannerEl.textContent = text;
  bannerEl.classList.toggle("ok", Boolean(ok));
}

function addLine(role, text) {
  const item = document.createElement("li");
  item.className = role === "user" ? "user" : "assistant";
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = role === "user" ? "测试员" : "文字客服";
  item.append(who, document.createTextNode(text));
  linesEl.append(item);
  item.scrollIntoView({ block: "nearest" });
}

function headers() {
  const result = { "Content-Type": "application/json" };
  const token = document.getElementById("call-token").value.trim();
  if (token) result["X-Zhiyu-Call-Token"] = token;
  return result;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}

async function loadScenarios() {
  const response = await fetch("/api/scenarios");
  const body = await readJson(response);
  scenarioEl.replaceChildren();
  for (const item of body.scenarios || []) {
    const option = document.createElement("option");
    option.value = String(item.row);
    option.textContent = item.menu + " / " + item.category + " / " + item.reason;
    scenarioEl.append(option);
  }
}

document.getElementById("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  sendDraft();
});

beginEl.addEventListener("click", () => startSession(false));
randomEl.addEventListener("click", () => startSession(true));
endEl.addEventListener("click", finishSession);

async function startSession(randomPick) {
  if (composer.sending) return;
  if (callGate && !document.getElementById("call-token").value.trim()) {
    setBanner("需要通话口令。口令不写在网页里。没有口令不会连接模型。", false);
    return;
  }
  applyComposer(Object.assign({}, composer, { sending: true }));
  waitEl.textContent = "正在准备文字对话。";
  const payload = randomPick
    ? { random: true }
    : { scenario_id: scenarioEl.value };
  let response;
  try {
    response = await fetch("/api/debug/session", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(payload),
    });
  } catch (error) {
    applyComposer(Object.assign({}, composer, { sending: false }));
    waitEl.textContent = "";
    setBanner("没有连上服务器。可以再试。", false);
    return;
  }
  const body = await readJson(response);
  if (!response.ok) {
    applyComposer(Object.assign({}, composer, { sending: false }));
    waitEl.textContent = "";
    setBanner(body.message || "文字对话没有开始。", false);
    return;
  }
  applyComposer(ZhiyuDebug.reduce(composer, { type: "start-ok" }));
  sessionId = body.session_id;
  linkedSession = body.session_id;
  scenarioEl.value = String(body.row);
  linesEl.replaceChildren();
  addLine("assistant", body.opening || "");
  endEl.disabled = false;
  draftEl.focus();
  setBanner("文字对话已开始。这一页没有声音。", true);
}

async function sendDraft() {
  const text = draftEl.value.trim();
  const proposed = ZhiyuDebug.reduce(composer, { type: "send" });
  if (proposed.ignored || !sessionId) return;
  if (!text) {
    waitEl.textContent = "请先打字。";
    return;
  }
  const epochAtSend = composer.epoch;
  const sentSession = sessionId;
  applyComposer(proposed);
  waitEl.textContent = "正在等模型。这一页不采集声音。";
  let response;
  try {
    response = await fetch("/api/debug/session/" + encodeURIComponent(sentSession) + "/say", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ text: text }),
    });
  } catch (error) {
    applyComposer(ZhiyuDebug.reduce(composer, { type: "fail", epoch: epochAtSend }));
    if (composer.enabled) waitEl.textContent = "发送失败：没有连上服务器。输入还在，可以再试。";
    return;
  }
  const body = await readJson(response);
  if (!response.ok) {
    applyComposer(ZhiyuDebug.reduce(composer, { type: "fail", epoch: epochAtSend }));
    if (composer.enabled) {
      waitEl.textContent = "发送失败：" + (body.message || "模型没有返回。") + "输入还在，可以再试。";
    }
    return;
  }
  const closed = body.stage === "closed";
  applyComposer(ZhiyuDebug.reduce(composer, { type: "ok", epoch: epochAtSend, closed: closed }));
  if (composer.epoch !== epochAtSend || sessionId !== sentSession) return;
  addLine("user", text);
  addLine("assistant", body.speak || "");
  draftEl.value = "";
  if (!composer.ended) waitEl.textContent = body.ticket_written ? "这通文字已经写了模拟工单。" : "";
  if (composer.ended) endEl.disabled = true;
}

async function finishSession() {
  if (!sessionId || composer.ended) return;
  const endingId = sessionId;
  applyComposer(ZhiyuDebug.reduce(composer, { type: "end" }));
  sessionId = "";
  endEl.disabled = true;
  let response;
  try {
    response = await fetch("/api/debug/session/" + encodeURIComponent(endingId) + "/end", {
      method: "POST",
      headers: headers(),
      body: "{}",
    });
  } catch (error) {
    sessionId = endingId;
    applyComposer(ZhiyuDebug.reduce(composer, { type: "end-fail", epoch: composer.epoch, wasEnded: false }));
    endEl.disabled = false;
    setBanner("没有连上服务器。可以再试结束。", false);
    return;
  }
  const body = await readJson(response);
  if (!response.ok) {
    sessionId = endingId;
    applyComposer(ZhiyuDebug.reduce(composer, { type: "end-fail", epoch: composer.epoch, wasEnded: false }));
    endEl.disabled = false;
    setBanner(body.message || "工单没有写上。", false);
    return;
  }
  setBanner(body.ticket_written ? "模拟工单已写。异常记录会使用这次的编号。" : "这通文字已结束。", true);
}

document.getElementById("incident-record").addEventListener("click", () => {
  document.getElementById("debug-incident").hidden = false;
});

document.getElementById("incident-image").addEventListener("change", () => {
  const file = document.getElementById("incident-image").files[0];
  const note = document.getElementById("incident-file");
  note.textContent = file ? file.name + "，" + Math.ceil(file.size / 1024) + " KB" : "还没有选择图片。";
});

document.getElementById("debug-incident").addEventListener("submit", (event) => {
  event.preventDefault();
  sendIncident();
});

function showIncidentResult(ok, text) {
  const result = document.getElementById("incident-result");
  result.className = ok ? "ok" : "bad";
  result.textContent = text;
}

async function sendIncident() {
  const what = document.getElementById("incident-what").value.trim();
  if (!linkedSession) {
    showIncidentResult(false, "提交失败：请先开始文字对话。已填内容还在。");
    return;
  }
  if (!what) {
    showIncidentResult(false, "提交失败：请先写一段具体情况。已填内容还在。");
    return;
  }
  if (callGate && !document.getElementById("call-token").value.trim()) {
    showIncidentResult(false, "提交失败：需要通话口令。已填内容还在。");
    return;
  }
  const body = new FormData();
  body.set("text", what);
  body.set("call_session_id", linkedSession);
  const file = document.getElementById("incident-image").files[0];
  if (file) body.set("image", file, file.name);
  const button = document.getElementById("incident-send");
  button.disabled = true;
  let response;
  try {
    const token = document.getElementById("call-token").value.trim();
    const requestHeaders = {};
    if (token) requestHeaders["X-Zhiyu-Call-Token"] = token;
    response = await fetch("/api/incidents", { method: "POST", headers: requestHeaders, body: body });
  } catch (error) {
    button.disabled = false;
    showIncidentResult(false, "提交失败：没有连上服务器。已填内容还在，可以再试。");
    return;
  }
  const payload = await readJson(response);
  button.disabled = false;
  if (!response.ok || !payload.ok) {
    showIncidentResult(false, "提交失败：" + (payload.message || "服务器没有保存。") + "已填内容还在，可以再试。");
    return;
  }
  const where = payload.ticket_attached ? "已写进本次模拟工单。" : "已保存在服务器。结束并写工单后会按这次编号关联。";
  showIncidentResult(true, "提交成功。" + where);
}

fetch("/api/collection")
  .then((response) => response.json())
  .then((body) => {
    callGate = Boolean(body.call_gate);
    if (callGate) document.getElementById("call-token-label").hidden = false;
  })
  .catch(() => {});

loadScenarios().catch((error) => setBanner(error.message || "场景没有加载。", false));
