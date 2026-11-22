#!/bin/bash
# 只备份这台机器上的试听 JSON。不是异地备份。
set -euo pipefail
DATA=/var/lib/zhiyu/teammate_reviews
DEST=/var/lib/zhiyu/backups
mkdir -p "$DEST"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
tar -C /var/lib/zhiyu -czf "$DEST/reviews-$STAMP.tgz" teammate_reviews
find "$DEST" -name 'reviews-*.tgz' -type f -printf '%T@ %p\n' | sort -nr | awk 'NR>7 {print $2}' | xargs -r rm -f
echo "已在本机保留最近的试听备份：$DEST"
