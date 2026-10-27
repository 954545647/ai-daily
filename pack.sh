#!/usr/bin/env bash
# 打包成一个可拷走的压缩包（不含 .env、数据、历史）
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="ai-daily-$(date +%Y%m%d).tar.gz"

tar czf "$NAME" \
  --exclude='.env' --exclude='logs' --exclude='__pycache__' \
  --exclude='data/*.json' --exclude='digests/*' \
  ai-daily

echo "✅ 打好了：$(pwd)/$NAME  ($(du -h "$NAME" | cut -f1))"
echo
echo "拷到新电脑后："
echo "  tar xzf $NAME && cd ai-daily"
echo "  cp .env.example .env && \$EDITOR .env    # 填 key 和 webhook"
echo "  chmod +x run.sh && python3 doctor.py"
