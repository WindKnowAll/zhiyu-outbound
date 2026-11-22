#!/bin/bash
# 在这台已经开通的 ECS 上安装并启用 coturn。不购买资源，不改百炼密钥和通话口令。
# 长期 TURN 密钥只写进 /etc/zhiyu/zhiyu.env 和 /etc/turnserver.conf，不打印。
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行。" >&2
  exit 1
fi
ENV_FILE=/etc/zhiyu/zhiyu.env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "找不到 $ENV_FILE。先完成智语安装，不要在这里新建密钥文件。" >&2
  exit 1
fi
PUBLIC_HOST="${ZHIYU_TURN_PUBLIC_HOST:-60.205.254.202}"
LISTEN_HOST="${ZHIYU_TURN_LISTEN_HOST:-172.31.77.255}"
TURN_PORT="${ZHIYU_TURN_PORT:-3478}"
MIN_PORT="${ZHIYU_TURN_MIN_PORT:-49152}"
MAX_PORT="${ZHIYU_TURN_MAX_PORT:-49251}"
TTL="${ZHIYU_TURN_TTL:-600}"
case "$PUBLIC_HOST$LISTEN_HOST" in
  *sk-*|*token*|*TOKEN*) echo "地址字段里出现了密钥样式，已停止。" >&2; exit 1 ;;
esac
install -d -m 0755 /var/lib/zhiyu/backups
if [[ -f /etc/turnserver.conf ]]; then
  cp -a /etc/turnserver.conf "/var/lib/zhiyu/backups/turnserver.conf.$(date -u +%Y%m%dT%H%M%SZ)"
fi
if [[ -f /etc/default/coturn ]]; then
  cp -a /etc/default/coturn /var/lib/zhiyu/backups/coturn.default.bak
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y coturn
python3 - "$ENV_FILE" "$PUBLIC_HOST" "$LISTEN_HOST" "$TURN_PORT" "$MIN_PORT" "$MAX_PORT" "$TTL" << 'PY'
import pathlib, secrets, sys
path, public, listen, port, min_port, max_port, ttl = sys.argv[1:]
file = pathlib.Path(path)
text = file.read_text(encoding="utf-8")
vals = {}
order = []
for line in text.splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key not in vals:
        order.append(key)
    vals[key] = value
secret = vals.get("ZHIYU_TURN_SECRET", "")
if len(secret) < 16:
    secret = secrets.token_urlsafe(32)
    vals["ZHIYU_TURN_SECRET"] = secret
vals["ZHIYU_TURN_PUBLIC_HOST"] = public
vals["ZHIYU_TURN_LISTEN_HOST"] = listen
vals["ZHIYU_TURN_PORT"] = port
vals["ZHIYU_TURN_MIN_PORT"] = min_port
vals["ZHIYU_TURN_MAX_PORT"] = max_port
vals["ZHIYU_TURN_TTL"] = ttl
wanted = [
    "ZHIYU_TURN_SECRET", "ZHIYU_TURN_PUBLIC_HOST", "ZHIYU_TURN_LISTEN_HOST",
    "ZHIYU_TURN_PORT", "ZHIYU_TURN_MIN_PORT", "ZHIYU_TURN_MAX_PORT", "ZHIYU_TURN_TTL",
]
for key in wanted:
    if key not in order:
        order.append(key)
kept = []
seen = set()
for line in text.splitlines():
    if not line or line.startswith("#") or "=" not in line:
        kept.append(line)
        continue
    key = line.split("=", 1)[0]
    if key in seen:
        continue
    seen.add(key)
    kept.append(f"{key}={vals.get(key, '')}")
for key in wanted:
    if key not in seen:
        kept.append(f"{key}={vals[key]}")
file.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
file.chmod(0o640)
conf = pathlib.Path("/etc/turnserver.conf")
conf.write_text(
    "\n".join([
        "listening-ip=" + listen,
        "listening-port=" + port,
        "relay-ip=" + listen,
        "external-ip=" + public + "/" + listen,
        "min-port=" + min_port,
        "max-port=" + max_port,
        "fingerprint",
        "lt-cred-mech",
        "use-auth-secret",
        "static-auth-secret=" + secret,
        "realm=zhiyu",
        "max-allocate-lifetime=" + ttl,
        "stale-nonce=" + ttl,
        "total-quota=40",
        "user-quota=4",
        "no-tcp-relay",
        "no-multicast-peers",
        "no-loopback-peers",
        "no-cli",
        "denied-peer-ip=0.0.0.0-0.255.255.255",
        "denied-peer-ip=10.0.0.0-10.255.255.255",
        "denied-peer-ip=127.0.0.0-127.255.255.255",
        "denied-peer-ip=169.254.0.0-169.254.255.255",
        "denied-peer-ip=172.16.0.0-172.31.255.255",
        "denied-peer-ip=192.168.0.0-192.168.255.255",
        "denied-peer-ip=240.0.0.0-255.255.255.255",
        "syslog",
        "",
    ]),
    encoding="utf-8",
)
conf.chmod(0o640)
print("turn-config-written")
PY
if id turnserver >/dev/null 2>&1; then
  chown root:turnserver /etc/turnserver.conf
fi
printf '%s\n' 'TURNSERVER_ENABLED=1' > /etc/default/coturn
chmod 0644 /etc/default/coturn
touch /var/lib/zhiyu/coturn-managed
chmod 0644 /var/lib/zhiyu/coturn-managed
systemctl enable coturn
systemctl restart coturn
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if systemctl is-active --quiet coturn && ss -lun | grep -Eq ":${TURN_PORT}([^0-9]|$)"; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" != 1 ]]; then
  echo "coturn 没有在 ${TURN_PORT}/udp 上就绪。密钥没有打印。可运行 deploy/coturn-rollback.sh。" >&2
  exit 1
fi
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "${TURN_PORT}/udp" comment "zhiyu-turn"
  ufw allow "${TURN_PORT}/tcp" comment "zhiyu-turn-tcp"
  ufw allow "${MIN_PORT}:${MAX_PORT}/udp" comment "zhiyu-turn-relay"
  echo "ufw 已放行上述端口。没有关闭防火墙，也没有放行其它端口。"
else
  echo "本机 ufw 未启用。阿里云安全组仍要单独放行，脚本没有改安全组。"
fi
systemctl restart zhiyu
zhiyu_ok=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -fsS http://127.0.0.1:7860/api/status > /tmp/zhiyu-turn-status.json; then
    zhiyu_ok=1
    break
  fi
  sleep 1
done
if [[ "$zhiyu_ok" != 1 ]]; then
  echo "智语没有重新起来。coturn 配置还在。密钥没有打印。" >&2
  exit 1
fi
python3 - "$PUBLIC_HOST" << 'PY'
import json, sys
body = json.load(open("/tmp/zhiyu-turn-status.json", encoding="utf-8"))
assert body.get("turn_enabled") is True, body.get("turn_enabled")
assert body.get("turn_public_host") == sys.argv[1]
text = open("/tmp/zhiyu-turn-status.json", encoding="utf-8").read()
assert "ZHIYU_TURN_SECRET" not in text
assert "credential" not in text
print("turn_enabled public_host=" + body["turn_public_host"])
PY
rm -f /tmp/zhiyu-turn-status.json
echo "coturn 已监听 ${LISTEN_HOST}:${TURN_PORT}，对外地址 ${PUBLIC_HOST}，中继 UDP ${MIN_PORT}-${MAX_PORT}。"
echo "安全组入方向只加这三项：UDP ${TURN_PORT}，TCP ${TURN_PORT}，UDP ${MIN_PORT}-${MAX_PORT}。来源是通话的手机网段；没有更小范围时用 0.0.0.0/0。"
echo "不要打开 22 以外的其它端口，不要关闭安全组。长期密钥留在服务器上，没有写入这个输出。"
