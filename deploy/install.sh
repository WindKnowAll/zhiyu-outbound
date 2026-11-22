#!/bin/bash
# 幂等安装。不要用 bash -x 运行，以免令牌出现在跟踪输出里。
# 本脚本不打印任何密钥。已有的 /etc/zhiyu/zhiyu.env 不会重写已有口令。
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行。" >&2
  exit 1
fi
SRC=$(cd "$(dirname "$0")/.." && pwd)
if [[ -f "$SRC/.env" ]]; then
  echo "源码目录里有 .env，拒绝安装。" >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.12 python3.12-venv python3-pip nginx
if ! id zhiyu >/dev/null 2>&1; then
  useradd --system --home /var/lib/zhiyu --create-home --shell /usr/sbin/nologin zhiyu
fi
mkdir -p /opt/zhiyu/releases /var/lib/zhiyu/teammate_reviews /var/lib/zhiyu/backups /etc/zhiyu
REL=/opt/zhiyu/releases/v1.8
if [[ -L /opt/zhiyu/current ]]; then
  old=$(readlink -f /opt/zhiyu/current || true)
  if [[ -n "$old" && "$old" != "$REL" ]]; then
    ln -sfn "$old" /opt/zhiyu/previous
  fi
fi
mkdir -p "$REL"
tar -C "$SRC" --exclude .git --exclude .venv --exclude var --exclude .env --exclude __pycache__ --exclude .pytest_cache -cf - . | tar -C "$REL" -xf -
ln -sfn "$REL" /opt/zhiyu/current
if [[ ! -x /opt/zhiyu/venv/bin/python ]]; then
  python3.12 -m venv /opt/zhiyu/venv
fi
/opt/zhiyu/venv/bin/pip install --upgrade pip
/opt/zhiyu/venv/bin/pip install -r /opt/zhiyu/current/requirements.txt
ENV_FILE=/etc/zhiyu/zhiyu.env
touch "$ENV_FILE"
chmod 640 "$ENV_FILE"
chown root:zhiyu "$ENV_FILE"
python3 - << 'PY'
import pathlib, secrets
path = pathlib.Path("/etc/zhiyu/zhiyu.env")
text = path.read_text(encoding="utf-8") if path.exists() else ""
vals = {}
for line in text.splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    vals[key] = value
def fill(key):
    current = vals.get(key, "")
    if len(current) >= 16:
        return
    vals[key] = secrets.token_urlsafe(24)
for key in ("ZHIYU_ADMIN_TOKEN", "ZHIYU_SUBMIT_TOKEN", "ZHIYU_CALL_TOKEN"):
    fill(key)
if vals.get("ZHIYU_ADMIN_TOKEN") == vals.get("ZHIYU_SUBMIT_TOKEN"):
    vals["ZHIYU_SUBMIT_TOKEN"] = secrets.token_urlsafe(24)
vals.setdefault("DASHSCOPE_API_KEY", "")
vals["HOST"] = "127.0.0.1"
vals["PORT"] = "7860"
vals["ZHIYU_COLLECT_ENABLED"] = "1"
vals["ZHIYU_REVIEW_DIR"] = "/var/lib/zhiyu/teammate_reviews"
order = [
    "HOST", "PORT", "ZHIYU_REVIEW_DIR", "ZHIYU_COLLECT_ENABLED",
    "ZHIYU_ADMIN_TOKEN", "ZHIYU_SUBMIT_TOKEN", "ZHIYU_CALL_TOKEN", "DASHSCOPE_API_KEY",
]
lines = ["# 在这台机器上填写 DASHSCOPE_API_KEY。不要把本文件复制到聊天或安装包。"]
for key in order:
    lines.append(f"{key}={vals.get(key, '')}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o640)
PY
chown -R zhiyu:zhiyu /var/lib/zhiyu /opt/zhiyu/releases /opt/zhiyu/venv
install -m 644 "$SRC/deploy/zhiyu.service" /etc/systemd/system/zhiyu.service
install -m 644 "$SRC/deploy/nginx-zhiyu.conf" /etc/nginx/sites-available/zhiyu.conf
ln -sfn /etc/nginx/sites-available/zhiyu.conf /etc/nginx/sites-enabled/zhiyu.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable zhiyu
systemctl restart zhiyu
systemctl reload nginx
sleep 2
if ! curl -fsS http://127.0.0.1:7860/api/build | python3 -c 'import json,sys; assert json.load(sys.stdin)["page_version"]=="v1.8"'; then
  echo "健康检查失败。若存在上一版，可运行 deploy/rollback.sh。数据目录未删除。" >&2
  exit 1
fi
install -m 755 "$SRC/deploy/backup.sh" /usr/local/sbin/zhiyu-backup
echo "安装完成。后端只监听 127.0.0.1:7860。口令已写入 /etc/zhiyu/zhiyu.env，本脚本不显示口令。"
echo "请在该文件里填写 DASHSCOPE_API_KEY 后执行 systemctl restart zhiyu。未填写时真实通话保持关闭。"
echo "nginx 目前只监听 80。没有域名，也没有启用 443。手机在明文 HTTP 上不能当安全上下文使用麦克风。"
