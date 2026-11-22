import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../zhiyu/static/review_ui.js", import.meta.url), "utf8");
const context = {};
vm.runInNewContext(source, context);
const ui = context.ZhiyuReview;

const secure = ui.mediaErrorText({ name: "NotAllowedError" }, true);
if (!secure.includes("权限")) throw new Error("permission");
const lan = ui.mediaErrorText(null, false);
if (!lan.includes("127.0.0.1") || !lan.includes("局域网")) throw new Error("lan");
const audio = ui.audioConstraints(true, false);
if (audio.echoCancellation !== true || audio.noiseSuppression !== false) throw new Error("constraints");
const voices = ui.voiceChoices("longxiaochun_v2");
if (voices.voices[0].id !== "longxiaochun_v2") throw new Error("voice");
if (!voices.unsupported.includes("Microsoft")) throw new Error("edge voice");
const review = ui.buildReview({
  consent: true,
  pseudonym: "甲",
  pageVersion: "v1.8",
  scenario: { row: 36 },
  turns: [{ role: "user", text: "是我们", false_barge_in: true }],
  echoCancellation: true,
  noiseSuppression: false,
});
if (review.raw_audio !== false || review.synthetic !== true) throw new Error("flags");
if (review.turns[0].false_barge_in !== true) throw new Error("barge");
console.log("review ui contract ok");
