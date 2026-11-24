(function (root) {
  function initial() {
    return { epoch: 0, sending: false, ended: false, enabled: false, note: "" };
  }

  function reduce(state, event) {
    if (event.type === "start-ok") {
      return { epoch: state.epoch + 1, sending: false, ended: false, enabled: true, note: "" };
    }
    if (event.type === "send") {
      if (!state.enabled || state.sending || state.ended) {
        return Object.assign({}, state, { ignored: true });
      }
      return { epoch: state.epoch, sending: true, ended: false, enabled: false, note: "" };
    }
    if (event.type === "fail") {
      if (event.epoch !== state.epoch || state.ended) {
        return {
          epoch: state.epoch,
          sending: false,
          ended: state.ended,
          enabled: state.enabled,
          note: state.note,
        };
      }
      return { epoch: state.epoch, sending: false, ended: false, enabled: true, note: "" };
    }
    if (event.type === "ok") {
      if (event.epoch !== state.epoch || state.ended) {
        return {
          epoch: state.epoch,
          sending: false,
          ended: state.ended,
          enabled: state.enabled,
          note: state.note,
        };
      }
      if (event.closed) {
        return { epoch: state.epoch, sending: false, ended: true, enabled: false, note: "电话已结束" };
      }
      return { epoch: state.epoch, sending: false, ended: false, enabled: true, note: "" };
    }
    if (event.type === "end") {
      return { epoch: state.epoch + 1, sending: false, ended: true, enabled: false, note: "电话已结束" };
    }
    if (event.type === "end-fail") {
      if (event.epoch !== state.epoch || event.wasEnded) {
        return state;
      }
      return { epoch: state.epoch, sending: false, ended: false, enabled: true, note: "" };
    }
    return state;
  }

  root.ZhiyuDebug = { initial: initial, reduce: reduce };
})(typeof globalThis !== "undefined" ? globalThis : this);
