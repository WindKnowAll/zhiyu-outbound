// 页面上和通话状态无关的纯函数。测试直接加载这个文件，不打开麦克风。
(function (root) {
  function pickScenario(ids, index) {
    if (!ids || !ids.length) return null;
    const safe = ((index % ids.length) + ids.length) % ids.length;
    return ids[safe];
  }

  function renderScenarioOptions(scenarios) {
    const groups = [];
    const index = new Map();
    for (const item of scenarios) {
      if (!index.has(item.menu)) {
        const group = { menu: item.menu, options: [] };
        index.set(item.menu, group);
        groups.push(group);
      }
      const method =
        item.close_method === "电话"
          ? "电话"
          : item.close_method === "京麦驳回"
            ? "京麦驳回，不在电话里编造话术"
            : item.close_method;
      const gap = item.script_complete ? "" : "，话术不完整只记后续处理";
      index.get(item.menu).options.push({
        id: String(item.row),
        label: item.category + " / " + item.reason + "（" + method + gap + "）",
        trace: item.trace,
      });
    }
    return groups;
  }

  function controls(state) {
    const busy = Boolean(state.inCall || state.starting);
    return {
      startDisabled: state.inCall ? false : Boolean(state.starting) || !state.ready,
      randomDisabled: busy || !state.ready || !state.count,
      scenarioDisabled: busy,
    };
  }

  function applyUserTranscript(lines, event) {
    const next = lines.map((line) => ({ ...line }));
    const id = event.utterance;
    const found = next.find((line) => line.role === "user" && line.utterance === id);
    if (found) {
      if (found.final && event.text === found.text) return next;
      if (found.final && !String(event.text || "").startsWith(found.text)) return next;
      found.text = event.text;
      found.final = Boolean(event.final) || found.final;
      return next;
    }
    let lastUser = -1;
    let assistantAfter = false;
    for (let i = 0; i < next.length; i += 1) {
      if (next[i].role === "user") {
        lastUser = i;
        assistantAfter = false;
      } else if (lastUser >= 0 && next[i].role === "assistant") {
        assistantAfter = true;
      }
    }
    if (lastUser >= 0 && !assistantAfter) {
      const prev = next[lastUser];
      const incoming = String(event.text || "");
      if (incoming.startsWith(prev.text) && incoming.length > prev.text.length) {
        prev.text = incoming;
        prev.final = Boolean(event.final);
        prev.utterance = id;
        return next;
      }
    }
    next.push({
      role: "user",
      utterance: id,
      text: event.text,
      final: Boolean(event.final),
    });
    return next;
  }

  function playbackAction(eventType) {
    return eventType === "barge_in" ? "flush" : "keep";
  }

  function mediaLinkText(connectionState, iceState) {
    const link = connectionState === "failed" ? "媒体连接失败" : "媒体连接断开";
    const ice = iceState ? "，ICE " + iceState : "";
    return link + ice + "。这不是识别或模型报错。通话记录仍为空时，表示声音还没进到服务。";
  }

  root.ZhiyuUI = {
    pickScenario,
    renderScenarioOptions,
    controls,
    applyUserTranscript,
    playbackAction,
    mediaLinkText,
  };
})(typeof globalThis === "undefined" ? this : globalThis);
