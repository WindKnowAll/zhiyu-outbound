// 浏览器侧只做三件事：打开麦克风、和服务器交换 WebRTC 信令、把通话事件画出来。
// 识别、大模型和合成都在服务器上。

const statusEl = document.getElementById("status");
const bannerEl = document.getElementById("banner");
const buttonEl = document.getElementById("call");
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
let iceServers = [{ urls: "stun:stun.qq.com:3478" }];
let peer = null;
let pcId = null;
let cursor = 0;
let pollTimer = null;
let botLine = null;

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
    addLine("你", event.text, "user");
    return;
  }
  if (event.type === "assistant") {
    if (event.final) {
      if (!botLine) {
        botLine = addLine("小语", event.text || "……", "bot");
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
      botLine = addLine("小语", event.text, "bot");
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
    statusEl.textContent = "检测到你在说话，已停止播放";
    setOrb("listening");
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

function startPolling() {
  stopPolling();
  pollTimer = setInterval(poll, 400);
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
  buttonEl.disabled = !ready;
  statusEl.textContent = ready ? "可以开始" : "还不能通话";
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
      statusEl.textContent = "已接通，小语会先打招呼";
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
  startPolling();
}

function hangup() {
  stopPolling();
  if (peer) {
    peer.close();
    peer = null;
  }
  audioEl.srcObject = null;
  pcId = null;
  buttonEl.textContent = "开始通话";
  buttonEl.classList.remove("hangup");
  statusEl.textContent = "已挂断";
  setOrb("quiet");
}

buttonEl.addEventListener("click", async () => {
  if (peer) {
    hangup();
    return;
  }
  try {
    await connect();
  } catch (error) {
    console.error(error);
    setBanner(error.message || String(error), false);
    statusEl.textContent = "没有接通";
    hangup();
    buttonEl.disabled = !ready;
  }
});

loadStatus().catch((error) => {
  setBanner("服务没有响应：" + error.message, false);
});
