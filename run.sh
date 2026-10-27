#!/usr/bin/env bash
# AI 日报 · 一条命令跑完：抓取 → 精挑写作 → 推送
# 用法： ./run.sh            （正常跑）
#        ./run.sh --ping     （只测推送）
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs
LOG="logs/run-$(date +%Y-%m-%d).log"

{
  echo "===== $(date '+%F %T') 开始 ====="
  python3 fetch.py --verbose
  python3 summarize.py
  python3 reader.py
  python3 notify.py
  bash publish.sh || echo '⚠️ 发布失败（不影响已推送的日报）'
  echo "===== $(date '+%F %T') 完成 ====="
} 2>&1 | tee -a "$LOG"

# 只保留最近 30 天的日志
find logs -name 'run-*.log' -mtime +30 -delete 2>/dev/null || true
