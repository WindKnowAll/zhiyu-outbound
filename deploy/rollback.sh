#!/bin/bash
# 只切回上一份程序。不删除 /var/lib/zhiyu 里的记录。
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行。" >&2
  exit 1
fi
if [[ ! -d /opt/zhiyu/previous ]]; then
  echo "没有上一版目录，不能回滚。" >&2
  exit 1
fi
target=$(readlink -f /opt/zhiyu/previous)
ln -sfn "$target" /opt/zhiyu/current
systemctl restart zhiyu
sleep 2
if ! curl -fsS http://127.0.0.1:7860/api/build >/tmp/zhiyu-rollback-build.json; then
  echo "回滚后的进程没有起来。数据目录未删除。" >&2
  exit 1
fi
python3 - << 'PY'
import json
body = json.load(open("/tmp/zhiyu-rollback-build.json", encoding="utf-8"))
print("回滚后 page_version=" + str(body.get("page_version")))
PY
rm -f /tmp/zhiyu-rollback-build.json
