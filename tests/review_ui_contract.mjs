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
if (review.call_link !== "unspecified") throw new Error("default link");
if (review.feedback.incident !== "" || review.idempotency_key !== "") throw new Error("default incident");
if ("token" in review || "authorization" in review) throw new Error("token field");
const bound = ui.incidentBinding("", "pc-earlier");
if (bound.callLink !== "recent" || bound.sessionId !== "pc-earlier") throw new Error("recent");
const live = ui.incidentBinding("pc-now", "pc-earlier");
if (live.callLink !== "current" || live.sessionId !== "pc-now") throw new Error("current");
const none = ui.incidentBinding("", "");
if (none.callLink !== "no_call" || none.sessionId !== "") throw new Error("none");
const kept = ui.incidentKey("same-key", false, () => "other");
if (kept !== "same-key") throw new Error("dedupe");
const renewed = ui.incidentKey("same-key", true, () => "fresh");
if (renewed !== "fresh") throw new Error("renew");
const incident = ui.buildReview({
  consent: true,
  pseudonym: "甲",
  pageVersion: "v1.8",
  scenario: { row: 36 },
  sessionId: "pc-now",
  callLink: "current",
  idempotencyKey: "11111111-1111-1111-1111-111111111111",
  incident: "播到一半停了",
  suggestion: "先停再说明原因",
});
if (incident.feedback.incident !== "播到一半停了") throw new Error("incident");
if (incident.call_link !== "current") throw new Error("link");
console.log("review ui contract ok");
