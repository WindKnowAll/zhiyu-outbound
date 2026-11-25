#!/bin/bash
# 只恢复 patch-apply.sh 留下的程序备份。不碰 /etc/zhiyu/zhiyu.env、试听数据和 TLS。
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行。" >&2
  exit 1
fi
ROOT=/opt/zhiyu/releases/v1.8
STAMP_FILE=/var/lib/zhiyu/backups/code-before-latest.txt
if [[ ! -f "$STAMP_FILE" ]]; then
  echo "没有补丁前的程序备份。" >&2
  exit 1
fi
STAMP=$(head -n 1 "$STAMP_FILE")
if [[ ! "$STAMP" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]; then
  echo "备份编号不正确。" >&2
  exit 1
fi
ARCHIVE="/var/lib/zhiyu/backups/code-before-$STAMP.tgz"
if [[ ! -f "$ARCHIVE" ]]; then
  echo "找不到 $ARCHIVE" >&2
  exit 1
fi
tar -C "$ROOT" -xzf "$ARCHIVE"
find "$ROOT/zhiyu" "$ROOT/deploy" -type d -exec chmod 0755 {} +
find "$ROOT/zhiyu" "$ROOT/deploy" -type f -exec chmod 0644 {} +
systemctl restart zhiyu
sleep 2
if ! curl -fsS http://127.0.0.1:7860/api/build > /tmp/zhiyu-rollback-build.json; then
  echo "回滚后的进程没有起来。试听数据和环境文件没有删除。" >&2
  exit 1
fi
python3 - << 'PY'
import json
body = json.load(open("/tmp/zhiyu-rollback-build.json", encoding="utf-8"))
print("回滚后 page_version=" + str(body.get("page_version")) + " build_hash=" + str(body.get("build_hash")))
PY
rm -f /tmp/zhiyu-rollback-build.json
