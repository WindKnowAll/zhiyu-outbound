const pipelineEl = document.getElementById("pipeline");
const countsEl = document.getElementById("counts");
const effectiveEl = document.getElementById("effective");
const bannerEl = document.getElementById("banner");
const detailEl = document.getElementById("detail");
const detailNoteEl = document.getElementById("detail-note");

function text(parent, tag, value) {
  const node = document.createElement(tag);
  node.textContent = value;
  parent.append(node);
  return node;
}

function showBanner(message) {
  bannerEl.hidden = false;
  bannerEl.textContent = message;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}

function renderOverview(body) {
  pipelineEl.replaceChildren();
  for (const step of body.pipeline || []) {
    const item = document.createElement("li");
    const mark = step.counts_as_evolution ? "算已生效" : "不算进化成果";
    item.textContent = step.step + "：" + String(step.count) + "（" + mark + "）";
    pipelineEl.append(item);
  }
  effectiveEl.textContent = "已生效的话术修正：" + String(body.effective_count ?? 0) + "。待审未启用，不算进化成果。这不是基础模型自训练。";
  countsEl.replaceChildren();
  const learning = body.learning || {};
  const rows = [
    ["异常反馈", (body.incidents || {}).count],
    ["其中已关联模拟工单", (body.incidents || {}).linked_tickets],
    ["人工试听记录", (body.reviews || {}).count],
    ["试听里写了异常说明", (body.reviews || {}).with_incident_note],
    ["候选待审", learning.pending],
    ["审核后启用", learning.approved_enabled],
    ["停用或未启用的已审", learning.disabled],
    ["已拒绝", learning.rejected],
    ["未解决跟进", body.followup_count],
  ];
  for (const [name, count] of rows) {
    const wrap = document.createElement("div");
    text(wrap, "dt", name);
    text(wrap, "dd", String(count ?? 0));
    countsEl.append(wrap);
  }
}

function renderList(title, rows, line) {
  const block = document.createElement("section");
  text(block, "h3", title);
  if (!rows.length) {
    text(block, "p", "没有记录。");
    detailEl.append(block);
    return;
  }
  const list = document.createElement("ul");
  for (const row of rows) {
    text(list, "li", line(row));
  }
  block.append(list);
  detailEl.append(block);
}

function renderDetail(body) {
  detailEl.replaceChildren();
  renderList("话术候选", body.learning || [], (row) => {
    const actions = (row.history || []).map((step) => step.action + " " + step.at).join("；");
    return (
      "场景行 " + String(row.source_row) +
      " · " + row.intent +
      " · " + row.status +
      " · 启用 " + (row.enabled ? "是" : "否") +
      " · 版本 " + String(row.version) +
      " · " + row.created_at +
      (actions ? " · " + actions : "")
    );
  });
  renderList("异常", body.incidents || [], (row) => {
    return (
      row.saved_at +
      " · 场景行 " + String(row.source_row ?? "未关联") +
      " · 工单 " + (row.ticket_attached ? "已关联" : "未关联") +
      " · 图片 " + (row.has_image ? "有" : "无")
    );
  });
  renderList("试听记录", body.reviews || [], (row) => {
    return (
      row.saved_at +
      " · 场景行 " + String(row.scenario_row ?? "未写") +
      " · 异常说明 " + (row.has_incident_note ? "有" : "无")
    );
  });
}

async function loadOverview() {
  let response;
  try {
    response = await fetch("/api/rsi/overview");
  } catch (error) {
    showBanner("没有连上服务器。");
    return;
  }
  const body = await readJson(response);
  if (!response.ok) {
    showBanner(body.message || "概览没有读到。");
    return;
  }
  renderOverview(body);
}

document.getElementById("gate").addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = document.getElementById("admin-token").value.trim();
  if (!token) {
    detailNoteEl.textContent = "请先填写管理员令牌。";
    return;
  }
  let response;
  try {
    response = await fetch("/api/rsi/detail", { headers: { Authorization: "Bearer " + token } });
  } catch (error) {
    detailNoteEl.textContent = "没有连上服务器。";
    return;
  }
  const body = await readJson(response);
  if (response.status === 401) {
    detailEl.replaceChildren();
    detailNoteEl.textContent = "需要管理员令牌。通话口令不能查看明细。";
    return;
  }
  if (!response.ok) {
    detailNoteEl.textContent = body.message || "明细没有读到。";
    return;
  }
  detailNoteEl.textContent = "明细只显示状态、时间和场景行。没有原文、手机号和图片。";
  renderDetail(body);
});

loadOverview();
