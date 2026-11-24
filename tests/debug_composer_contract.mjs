import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../zhiyu/static/debug_state.js", import.meta.url), "utf8");
const context = {};
vm.runInNewContext(source, context);
const ui = context.ZhiyuDebug;
const page = fs.readFileSync(new URL("../zhiyu/static/debug.html", import.meta.url), "utf8");
const script = fs.readFileSync(new URL("../zhiyu/static/debug.js", import.meta.url), "utf8");

if (!page.includes(">电话已结束<")) throw new Error("ended text missing");
if (!page.includes(">开始文字对话<")) throw new Error("restart button missing");
if (!page.includes(">异常情况记录<")) throw new Error("incident button missing");
if (script.includes('getElementById("incident-record").disabled') || script.includes("incident-record\").disabled")) {
  throw new Error("incident button must stay usable");
}
if (!script.includes('note === "电话已结束"')) throw new Error("composer does not show the ended note");

function walk(events) {
  return events.reduce((state, event) => ui.reduce(state, event), ui.initial());
}

const started = walk([{ type: "start-ok" }]);
if (!started.enabled || started.ended || started.note) throw new Error("start should enable input");

const inflight = ui.reduce(started, { type: "send" });
if (inflight.sending !== true || inflight.enabled !== false) throw new Error("send in flight must lock input");
const second = ui.reduce(inflight, { type: "send" });
if (!second.ignored) throw new Error("second send must be ignored");

const failed = ui.reduce(inflight, { type: "fail", epoch: started.epoch });
if (!failed.enabled || failed.ended) throw new Error("failed send must restore input");

const endedByUser = ui.reduce(inflight, { type: "end" });
if (endedByUser.note !== "电话已结束" || endedByUser.enabled || !endedByUser.ended) {
  throw new Error("user end must disable input");
}
const late = ui.reduce(endedByUser, { type: "ok", epoch: started.epoch, closed: false });
if (late.enabled || late.note !== "电话已结束") throw new Error("late response resurrected input");

const auto = ui.reduce(inflight, { type: "ok", epoch: started.epoch, closed: true });
if (auto.note !== "电话已结束" || auto.enabled) throw new Error("server close must disable input");

const restarted = ui.reduce(auto, { type: "start-ok" });
if (!restarted.enabled || restarted.ended || restarted.note) throw new Error("new conversation must restore input");

const endFail = ui.reduce(ui.reduce(started, { type: "end" }), {
  type: "end-fail",
  epoch: started.epoch + 1,
  wasEnded: false,
});
if (!endFail.enabled || endFail.note) throw new Error("failed end must allow retry");
const staleAfterFailedEnd = ui.reduce(endFail, { type: "ok", epoch: started.epoch, closed: false });
if (!staleAfterFailedEnd.enabled) throw new Error("stale ok must not be required to re-enable");
if (staleAfterFailedEnd.note === "电话已结束") throw new Error("stale ok marked the call ended");
