#!/bin/bash
# 把解压后的补丁覆盖到已安装的 v1.8 程序目录。
# 不读取、不修改 /etc/zhiyu/zhiyu.env，不删除试听数据、工单和 TLS，不安装依赖。
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
FILES=(
  zhiyu/server.py
  zhiyu/static/app.js
  zhiyu/static/call_ui.js
  deploy/patch-apply.sh
  deploy/patch-rollback.sh
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
sleep 2
if ! curl -fsS http://127.0.0.1:7860/api/build > /tmp/zhiyu-patch-build.json; then
  echo "新进程没有起来。环境、数据和证书没有改。可运行 deploy/patch-rollback.sh。" >&2
  exit 1
fi
python3 - << 'PY'
import json
body = json.load(open("/tmp/zhiyu-patch-build.json", encoding="utf-8"))
assert body.get("page_version") == "v1.8", body.get("page_version")
assert body.get("build_hash") == "4eaa83cd1a58", body.get("build_hash")
print("page_version=v1.8 build_hash=" + str(body.get("build_hash")))
PY
rm -f /tmp/zhiyu-patch-build.json
echo "补丁已放上。没有改 /etc/zhiyu/zhiyu.env、试听数据和 TLS。"
