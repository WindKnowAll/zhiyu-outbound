#!/bin/bash
# 从已部署的 v1.8 构建 572c17421cf4 更新到深色青绿首页。
# 先核对基线，再备份程序，然后覆盖文件。不读取、不修改 /etc/zhiyu/zhiyu.env，
# 不删除试听数据、工单和 TLS，不改 nginx、证书和 TURN，不安装依赖。
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行。" >&2
  exit 1
fi
ROOT=/opt/zhiyu/releases/v1.8
PATCH_ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [[ ! -d "$ROOT/zhiyu" ]]; then
  echo "找不到 $ROOT。这个脚本只更新已经装好的 v1.8。" >&2
  exit 1
fi
case "$ROOT" in
  /etc|/etc/*) echo "拒绝写入 /etc" >&2; exit 1 ;;
esac
if ! curl -fsS http://127.0.0.1:7860/api/build > /tmp/zhiyu-patch-before.json; then
  echo "读不到当前构建。没有改任何文件。" >&2
  exit 1
fi
MODE=$(python3 - << 'PY'
import json
body = json.load(open("/tmp/zhiyu-patch-before.json", encoding="utf-8"))
current = str(body.get("build_hash") or "")
if current == "05e64542da37":
    print("already")
elif current == "572c17421cf4":
    print("ok")
else:
    print("refuse")
PY
)
rm -f /tmp/zhiyu-patch-before.json
if [[ "$MODE" == "already" ]]; then
  echo "当前已是 05e64542da37，不再覆盖。"
  exit 0
fi
if [[ "$MODE" != "ok" ]]; then
  echo "拒绝：这个补丁只从已部署的构建 572c17421cf4 升级。环境、数据和证书没有改。" >&2
  exit 1
fi
echo "基线核对通过：572c17421cf4"
FILES=(
  zhiyu/static/index.html
  zhiyu/static/app.js
  zhiyu/static/style.css
  deploy/patch-apply.sh
)
for rel in "${FILES[@]}"; do
  if [[ "$rel" == *.env || "$rel" == *zhiyu.env ]]; then
    echo "补丁里出现了环境文件，已停止。" >&2
    exit 1
  fi
  if [[ ! -f "$PATCH_ROOT/$rel" ]]; then
    echo "补丁缺少 $rel" >&2
    exit 1
  fi
done
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0755 /var/lib/zhiyu/backups
tar -C "$ROOT" -czf "/var/lib/zhiyu/backups/code-before-$STAMP.tgz" \
  --exclude var --exclude .venv \
  zhiyu deploy
printf '%s\n' "$STAMP" > /var/lib/zhiyu/backups/code-before-latest.txt
chmod 0644 "/var/lib/zhiyu/backups/code-before-$STAMP.tgz" /var/lib/zhiyu/backups/code-before-latest.txt
for rel in "${FILES[@]}"; do
  install -d -m 0755 "$ROOT/$(dirname "$rel")"
  install -m 0644 "$PATCH_ROOT/$rel" "$ROOT/$rel"
done
systemctl restart zhiyu
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -fsS http://127.0.0.1:7860/api/build > /tmp/zhiyu-patch-build.json; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" != 1 ]]; then
  echo "新进程没有起来。环境、数据和证书没有改。可运行 deploy/patch-rollback.sh。" >&2
  exit 1
fi
python3 - << 'PY'
import json
body = json.load(open("/tmp/zhiyu-patch-build.json", encoding="utf-8"))
assert body.get("page_version") == "v1.8", body.get("page_version")
assert body.get("build_hash") == "05e64542da37", body.get("build_hash")
print("page_version=v1.8 build_hash=" + str(body.get("build_hash")))
PY
rm -f /tmp/zhiyu-patch-build.json
echo "补丁已放上。没有改 /etc/zhiyu/zhiyu.env、试听数据、nginx 和 TLS。"
