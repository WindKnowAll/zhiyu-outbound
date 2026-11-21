import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../zhiyu/static/call_ui.js", import.meta.url), "utf8");
const context = {};
vm.runInNewContext(source, context);
const ui = context.ZhiyuUI;

const ids = [13, 15, 28, 36, 80];
if (ui.pickScenario([], 0) !== null) throw new Error("empty pool");
if (ui.pickScenario([36], 4) !== 36) throw new Error("single pool");
const picked = new Set(ids.map((_, index) => ui.pickScenario(ids, index)));
if (picked.size !== ids.length) throw new Error("pool does not cover every id");

const groups = ui.renderScenarioOptions([
  { row: 13, menu: "品牌", category: "商标注册证", reason: "商标状态不符合要求", close_method: "电话", script_complete: true, trace: "场景汇总!R13" },
  { row: 17, menu: "品牌", category: "授权书-文审", reason: "授权书内容不完整", close_method: "电话", script_complete: true, trace: "场景汇总!R17" },
  { row: 29, menu: "品牌", category: "授权范围审核", reason: "品牌类目不符", close_method: "电话", script_complete: true, trace: "场景汇总!R29" },
  { row: 33, menu: "品牌", category: "新增产品线", reason: "产品线不匹配", close_method: "电话", script_complete: true, trace: "场景汇总!R33" },
  { row: 15, menu: "品牌", category: "商标注册证", reason: "资质造假", close_method: "京麦驳回", script_complete: true, trace: "场景汇总!R15" },
  { row: 28, menu: "品牌", category: "授权书-验真", reason: "品牌方不认可授权", close_method: "电话", script_complete: false, trace: "场景汇总!R28" },
  { row: 75, menu: "公司资质", category: "公司主体资质审核", reason: "法人证件信息错误", close_method: "电话", script_complete: true, trace: "场景汇总!R75" },
]);
const labels = groups.flatMap((group) => group.options.map((option) => option.label + group.menu));
for (const word of ["商标注册证", "授权书-文审", "授权范围审核", "新增产品线", "公司资质", "京麦驳回，不在电话里编造话术", "话术不完整"]) {
  if (!labels.some((label) => label.includes(word))) throw new Error("missing " + word);
}

const idle = ui.controls({ inCall: false, starting: false, ready: true, count: 68 });
if (idle.randomDisabled || idle.scenarioDisabled || idle.startDisabled) throw new Error("idle controls");
const busy = ui.controls({ inCall: true, starting: false, ready: true, count: 68 });
if (!busy.randomDisabled || !busy.scenarioDisabled || busy.startDisabled) throw new Error("in-call controls");
const starting = ui.controls({ inCall: false, starting: true, ready: true, count: 68 });
if (!starting.randomDisabled || !starting.startDisabled) throw new Error("starting controls");

let lines = [];
lines = ui.applyUserTranscript(lines, { utterance: 0, text: "为", final: false });
lines = ui.applyUserTranscript(lines, { utterance: 0, text: "为什么驳回", final: false });
lines = ui.applyUserTranscript(lines, { utterance: 0, text: "为什么驳回", final: true });
if (lines.length !== 1 || lines[0].text !== "为什么驳回" || !lines[0].final) throw new Error("user line duplicated");
lines = ui.applyUserTranscript(lines, { utterance: 1, text: "下一句", final: false });
if (lines.length !== 2) throw new Error("next utterance missing");
const frozen = ui.applyUserTranscript(lines, { utterance: 0, text: "被改写", final: false });
if (frozen[0].text !== "为什么驳回") throw new Error("final line was rewritten");

console.log("call ui contract ok");
