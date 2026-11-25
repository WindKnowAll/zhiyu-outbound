#!/bin/bash
# 停用本项目启用的 coturn，并恢复安装前的配置。不删除 /etc/zhiyu/zhiyu.env 里的密钥和百炼配置。
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行。" >&2
  exit 1
fi
systemctl disable --now coturn || true
latest=$(ls -1t /var/lib/zhiyu/backups/turnserver.conf.* 2>/dev/null | head -n 1 || true)
if [[ -n "${latest}" ]]; then
  cp -a "$latest" /etc/turnserver.conf
  chmod 0640 /etc/turnserver.conf
  echo "已恢复 $latest"
else
  rm -f /etc/turnserver.conf
  echo "没有旧的 turnserver.conf，已删除本脚本写的配置。"
fi
if [[ -f /var/lib/zhiyu/backups/coturn.default.bak ]]; then
  cp -a /var/lib/zhiyu/backups/coturn.default.bak /etc/default/coturn
else
  printf '%s\n' 'TURNSERVER_ENABLED=0' > /etc/default/coturn
fi
rm -f /var/lib/zhiyu/coturn-managed
echo "coturn 已停用。/etc/zhiyu/zhiyu.env 里的 ZHIYU_TURN_SECRET 仍留在服务器上，没有打印，也没有改 API key。"
echo "智语进程还在。若要它停止分配中继，把 ZHIYU_TURN_PUBLIC_HOST 清空后 systemctl restart zhiyu。"
