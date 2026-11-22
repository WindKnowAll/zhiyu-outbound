(function (root) {
  function mediaErrorText(error, secure) {
    if (!secure) {
      return "这个页面不是安全上下文。手机上的 127.0.0.1 指向手机自己；局域网 HTTP 通常不能申请麦克风。";
    }
    const name = error && error.name;
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      return "麦克风权限被拒绝。请在浏览器里允许后再开始。";
    }
    if (name === "NotFoundError") {
      return "没有找到麦克风。";
    }
    if (!error) return "";
    return "麦克风没有打开：" + (error.message || name || "未知原因");
  }

  function audioConstraints(echoCancellation, noiseSuppression) {
    return {
      echoCancellation: Boolean(echoCancellation),
      noiseSuppression: Boolean(noiseSuppression),
      channelCount: 1,
    };
  }

  function voiceChoices(configured) {
    const id = configured || "";
    return {
      voices: id ? [{ id: id, usable: true, engine: "cosyvoice" }] : [],
      unsupported: "Microsoft 浏览器语音不会送进 CosyVoice。",
    };
  }

  function buildReview(input) {
    const turns = (input.turns || []).map((turn) => ({
      role: turn.role,
      text: turn.text || "",
      false_barge_in: Boolean(turn.false_barge_in),
    }));
    return {
      schema: "zhiyu.teammate_review.v1",
      synthetic: true,
      raw_audio: false,
      consent: Boolean(input.consent),
      pseudonym: input.pseudonym || "",
      page_version: input.pageVersion || "",
      scenario: input.scenario || { row: 0 },
      session_id: input.sessionId || "",
      turns: turns,
      provider_traces: input.providerTraces || [],
      stage_timings: input.stageTimings || [],
      feedback: {
        expected: input.expected || "",
        actual: input.actual || "",
      },
      audio_constraints: audioConstraints(input.echoCancellation, input.noiseSuppression),
      vad: input.vad || {},
    };
  }

  root.ZhiyuReview = {
    mediaErrorText: mediaErrorText,
    audioConstraints: audioConstraints,
    voiceChoices: voiceChoices,
    buildReview: buildReview,
  };
})(typeof globalThis === "undefined" ? window : globalThis);
