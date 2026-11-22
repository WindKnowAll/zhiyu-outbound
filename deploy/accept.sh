#!/bin/bash
# 在服务器本机验收。读取 /etc/zhiyu/zhiyu.env，不把令牌打到终端。
set -euo pipefail
ENV_FILE=/etc/zhiyu/zhiyu.env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "缺少 $ENV_FILE" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
BASE=http://127.0.0.1:7860
python3 - "$BASE" << 'PY'
import json, os, sys, urllib.error, urllib.request
base = sys.argv[1]
def get(path, token=""):
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()
status, body = get("/api/status")
data = json.loads(body)
assert status == 200, status
assert data.get("page_version") == "v1.8"
assert "sk-" not in body
code, _ = get("/api/build")
assert code == 200
build = json.loads(_)
assert build.get("page_version") == "v1.8"
code, text = get("/api/collect")
assert code == 401, code
assert "sk-" not in text
submit = os.environ.get("ZHIYU_SUBMIT_TOKEN", "")
admin = os.environ.get("ZHIYU_ADMIN_TOKEN", "")
assert submit and admin and submit != admin
code, text = get("/api/collect", submit)
assert code == 401, code
code, text = get("/api/reviews")
assert code == 403, code
payload = json.dumps({
    "schema": "zhiyu.teammate_review.v1",
    "synthetic": True,
    "raw_audio": False,
    "consent": True,
    "pseudonym": "验收",
    "page_version": "v1.8",
    "scenario": {"row": 36, "menu": "品牌", "category": "商标", "reason": "图形", "close_method": "电话", "script_complete": True},
    "turns": [],
    "provider_traces": [],
    "stage_timings": [],
    "feedback": {"expected": "", "actual": ""},
}).encode()
req = urllib.request.Request(base + "/api/collect", data=payload, method="POST")
req.add_header("Authorization", "Bearer " + submit)
req.add_header("Content-Type", "application/json")
with urllib.request.urlopen(req) as resp:
    saved = json.loads(resp.read().decode())
assert saved.get("pseudonym") == "验收"
assert saved.get("raw_audio") is False
code, _ = get("/api/collect?pseudonym=" + "甲", submit)
assert code == 401
req = urllib.request.Request(base + "/api/collect?pseudonym=" + "验收")
req.add_header("Authorization", "Bearer " + admin)
with urllib.request.urlopen(req) as resp:
    listed = json.loads(resp.read().decode())
names = [item.get("pseudonym") for item in listed.get("reviews", [])]
assert names == ["验收"] or "验收" in names
print("accept-ok page_version=v1.8 collect-isolated")
PY
