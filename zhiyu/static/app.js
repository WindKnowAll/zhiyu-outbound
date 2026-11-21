// 浏览器侧只做三件事：打开麦克风、和服务器交换 WebRTC 信令、把通话事件画出来。
// 识别、大模型和合成都在服务器上。

const statusEl = document.getElementById("status");
const ticketEl = document.getElementById("ticket");
const bannerEl = document.getElementById("banner");
const buttonEl = document.getElementById("call");
const randomEl = document.getElementById("random");
const scenarioEl = document.getElementById("scenario");
const scenarioNoteEl = document.getElementById("scenario-note");
const linesEl = document.getElementById("lines");
const orbEl = document.getElementById("orb");
const audioEl = document.getElementById("remote");

const latencyEls = {
  asr_final_ms: document.getElementById("m-asr"),
  llm_first_token_ms: document.getElementById("m-llm"),
  tts_first_audio_ms: document.getElementById("m-tts"),
  first_audio_e2e_ms: document.getElementById("m-e2e"),
};

const statusText = {
  connected: "已接通",
  listening: "正在听",
  thinking: "正在想",
  speaking: "正在说",
  ended: "通话已结束",
};

let ready = false;
let starting = false;
let iceServers = [{ urls: "stun:stun.qq.com:3478" }];
let peer = null;
let pcId = null;
let cursor = 0;
let pollTimer = null;
let botLine = null;
let userLines = [];
let ticketSeen = false;
let scenarios = [];

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

function refreshControls() {
  const state = ZhiyuUI.controls({
    inCall: Boolean(peer),
    starting,
    ready,
    count: scenarios.length,
  });
  if (!peer) buttonEl.disabled = state.startDisabled;
  randomEl.disabled = state.randomDisabled;
  scenarioEl.disabled = state.scenarioDisabled;
}

function showChosen() {
  const selected = scenarios.find((item) => String(item.row) === scenarioEl.value);
  if (!selected) {
    scenarioNoteEl.textContent = "还没有选中场景。";
    return;
  }
  const method = selected.phone_flow ? "电话说明" : "非电话流程，不编造电话话术";
  const gap = selected.script_complete ? "话术来自主表该行" : "话术不完整，只记后续处理";
  scenarioNoteEl.textContent =
    selected.trace + " " + selected.menu + " / " + selected.category + " / " + selected.reason + "。" + method + "。" + gap + "。本通接通后锁定。";
}

function fillScenarios(items) {
  scenarios = items;
  scenarioEl.replaceChildren();
  for (const group of ZhiyuUI.renderScenarioOptions(items)) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.menu;
    for (const option of group.options) {
      const node = document.createElement("option");
      node.value = option.id;
      node.textContent = option.label;
      optgroup.append(node);
    }
    scenarioEl.append(optgroup);
  }
  const preferred = items.find((item) => item.row === 36) || items[0];
  if (preferred) scenarioEl.value = String(preferred.row);
  showChosen();
  refreshControls();
}

function setOrb(name) {
  orbEl.className = "orb " + (name || "quiet");
}

function addLine(who, text, kind) {
  const item = document.createElement("li");
  item.className = kind;
  const label = document.createElement("span");
  label.className = "who";
  label.textContent = who;
  const body = document.createElement("span");
  body.textContent = text;
  item.append(label, body);
  linesEl.append(item);
  linesEl.scrollTop = linesEl.scrollHeight;
  return body;
}

function showLatency(timings) {
  for (const [key, el] of Object.entries(latencyEls)) {
    const value = timings ? timings[key] : null;
    el.textContent = value == null ? "—" : Math.round(value) + " ms";
  }
}

function handleEvent(event) {
  if (event.type === "status") {
    statusEl.textContent = statusText[event.value] || event.value;
    setOrb(event.value === "ended" ? "quiet" : event.value);
    return;
  }
  if (event.type === "user") {
    botLine = null;
    const prev = userLines;
    const next = ZhiyuUI.applyUserTranscript(prev, event);
    if (next.length === prev.length) {
      for (let i = 0; i < next.length; i += 1) {
        if (next[i].text !== prev[i].text && prev[i].el) {
          prev[i].el.textContent = next[i].text;
        }
        prev[i].text = next[i].text;
        prev[i].final = next[i].final;
        prev[i].utterance = next[i].utterance;
      }
    } else {
      const added = next[next.length - 1];
      added.el = addLine("你", added.text, "user");
      userLines = prev.concat(added);
    }
    return;
  }
  if (event.type === "assistant") {
    const last = userLines[userLines.length - 1];
    if (!last || last.role !== "assistant") {
      userLines.push({ role: "assistant", text: "", final: true, utterance: "sep" });
    }
    if (event.final) {
      if (!botLine) {
        botLine = addLine("客服", event.text || "……", "bot");
      } else if (event.text) {
        botLine.textContent = event.text;
      }
      if (event.interrupted) {
        botLine.textContent += "（被打断）";
      }
      botLine = null;
      return;
    }
    if (!botLine) {
      botLine = addLine("客服", event.text, "bot");
    } else {
      botLine.textContent += event.text;
    }
    return;
  }
  if (event.type === "latency") {
    showLatency(event.timings);
    if (event.interrupted) {
      statusEl.textContent = "你插话了，上一句已停";
    }
    return;
  }
  if (event.type === "barge_in") {
    if (ZhiyuUI.playbackAction(event.type) === "flush") flushRemoteAudio();
    statusEl.textContent = "检测到你在说话，已停止播放";
    setOrb("listening");
    return;
  }
  if (event.type === "mock_ticket") {
    const ticket = event.ticket || {};
    if (ticket.write_error) {
      ticketEl.textContent = "模拟工单没有写入，不能当成已经成功：" + ticket.write_error;
      return;
    }
    const lines = [
      ticket.system || "本地模拟工单",
      "结果：" + (ticket.result || "—"),
      "原因：" + (ticket.reason_text || "未向对方披露"),
      "整改：" + (ticket.action_text || "未向对方披露"),
      "后续处理：" + (ticket.transfer_human ? "已记下，稍后由审核同事确认" : "无"),
      "预约：" + (ticket.appointment || "无"),
    ];
    ticketEl.textContent = lines.join(" ");
    ticketSeen = true;
    return;
  }
  if (event.type === "error") {
    setBanner(event.message, false);
    statusEl.textContent = "出错了";
  }
}

async function poll() {
  if (!pcId) return;
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(pcId)}?cursor=${cursor}`);
    if (response.status === 404) return;
    if (!response.ok) return;
    const body = await response.json();
    cursor = body.next;
    for (const event of body.events) handleEvent(event);
  } catch (error) {
    console.warn(error);
  }
}

function flushRemoteAudio() {
  const stream = audioEl.srcObject;
  if (!stream) return;
  audioEl.pause();
  audioEl.srcObject = null;
  audioEl.srcObject = stream;
  audioEl.play().catch(() => {});
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(poll, 120);
  poll();
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const body = await response.json();
  if (Array.isArray(body.ice_servers) && body.ice_servers.length) {
    iceServers = body.ice_servers.map((url) => ({ urls: url }));
  }
  setBanner(body.message, body.ok);
  ready = Boolean(body.ok);
  statusEl.textContent = ready ? "可以开始" : "还不能通话";
  refreshControls();
}

async function loadScenarios() {
  const response = await fetch("/api/scenarios");
  if (!response.ok) throw new Error("场景列表接口没有返回。页面里已经有的选项仍可使用。");
  const body = await response.json();
  if (!Array.isArray(body.scenarios) || body.scenarios.length === 0) {
    throw new Error("场景列表是空的。");
  }
  fillScenarios(body.scenarios);
}

function waitForIce(pc) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, 1200);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(timer);
        resolve();
      }
    });
  });
}

async function sendCandidate(candidate) {
  if (!pcId) return;
  await fetch("/api/offer", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pc_id: pcId,
      candidates: [
        {
          candidate: candidate.candidate,
          sdp_mid: candidate.sdpMid,
          sdp_mline_index: candidate.sdpMLineIndex,
        },
      ],
    }),
  });
}

async function connect() {
  if (starting || peer) return;
  starting = true;
  ticketSeen = false;
  userLines = [];
  refreshControls();
  statusEl.textContent = "正在接通";
  buttonEl.disabled = true;
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    },
    video: false,
  });

  const pc = new RTCPeerConnection({ iceServers });
  peer = pc;
  const pending = [];
  pc.ontrack = (event) => {
    audioEl.srcObject = event.streams[0];
    audioEl.play().catch(() => {});
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === "connected") {
      statusEl.textContent = "已接通，先确认公司和店铺";
      setOrb("speaking");
    }
    if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
      statusEl.textContent = "连接中断";
    }
  };
  pc.onicecandidate = (event) => {
    if (!event.candidate) return;
    if (pcId) {
      sendCandidate(event.candidate).catch((error) => console.warn(error));
    } else {
      pending.push(event.candidate);
    }
  };

  // 官方 SmallWebRTC 示例会同时准备音频和视频两路，服务端按这个顺序找轨道。
  pc.addTransceiver(stream.getAudioTracks()[0], { direction: "sendrecv" });
  pc.addTransceiver("video", { direction: "sendrecv" });
  await pc.setLocalDescription(await pc.createOffer());
  await waitForIce(pc);

  const response = await fetch("/api/offer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
      scenario_id: scenarioEl.value,
    }),
  });
  const answer = await response.json();
  if (!response.ok) {
    throw new Error(answer.message || answer.detail || "接通失败");
  }
  pcId = answer.pc_id;
  cursor = 0;
  await pc.setRemoteDescription(answer);
  for (const candidate of pending) {
    await sendCandidate(candidate);
  }
  buttonEl.disabled = false;
  buttonEl.textContent = "挂断";
  buttonEl.classList.add("hangup");
  starting = false;
  refreshControls();
  showChosen();
  startPolling();
}

async function hangup() {
  const id = pcId;
  buttonEl.disabled = true;
  randomEl.disabled = true;
  if (peer) {
    peer.close();
    peer = null;
  }
  audioEl.srcObject = null;
  if (id) {
    const deadline = Date.now() + 2000;
    do {
      await poll();
      if (ticketSeen) break;
      await new Promise((resolve) => setTimeout(resolve, 200));
    } while (Date.now() < deadline);
  }
  stopPolling();
  pcId = null;
  starting = false;
  buttonEl.textContent = "开始通话";
  buttonEl.classList.remove("hangup");
  statusEl.textContent = "已挂断";
  setOrb("quiet");
  refreshControls();
}

document.getElementById("pick").addEventListener("click", () => {
  scenarioEl.focus();
  if (typeof scenarioEl.showPicker === "function") {
    try {
      scenarioEl.showPicker();
    } catch (error) {
      console.warn(error);
    }
  }
});

scenarioEl.addEventListener("change", () => {
  if (peer || starting) return;
  showChosen();
});

buttonEl.addEventListener("click", async () => {
  if (peer) {
    await hangup();
    return;
  }
  if (starting) return;
  try {
    await connect();
  } catch (error) {
    console.error(error);
    setBanner(error.message || String(error), false);
    statusEl.textContent = "没有接通";
    await hangup();
    buttonEl.disabled = !ready;
  }
});

randomEl.addEventListener("click", async () => {
  if (peer || starting) return;
  const ids = scenarios.map((item) => item.row);
  const picked = ZhiyuUI.pickScenario(ids, Math.floor(Math.random() * ids.length));
  if (picked == null) {
    setBanner("没有可选的驳回场景。", false);
    return;
  }
  scenarioEl.value = String(picked);
  showChosen();
  try {
    await connect();
  } catch (error) {
    console.error(error);
    setBanner(error.message || String(error), false);
    statusEl.textContent = "没有接通";
    await hangup();
  }
});

if (typeof ZhiyuUI === "undefined") {
  zhiyuPageFailed("页面脚本没有执行。页脚必须是 zhiyu-20261121e，否则不是这次的服务。");
}

loadStatus()
  .then(loadScenarios)
  .catch((error) => {
    const message = error.message || String(error);
    setBanner(message, false);
    if (scenarioNoteEl && scenarioEl.options.length === 0) {
      scenarioNoteEl.textContent = message;
    }
  });
