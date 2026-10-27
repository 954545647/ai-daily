#!/usr/bin/env bash
# 把逐条学习页发布到 docs/（GitHub Pages 的源目录），并更新首页为最新一天
set -euo pipefail
cd "$(dirname "$0")"

DATE="${1:-$(date +%F)}"
mkdir -p docs

python3 reader.py --date "$DATE"
cp "digests/$DATE.html" "docs/$DATE.html"
cp "digests/$DATE.html" "docs/index.html"     # 首页永远是最新一天

# 只保留最近 60 天，避免仓库越来越大
ls -1t docs/2*.html 2>/dev/null | tail -n +61 | xargs -r rm -f

echo "✅ 已生成 docs/$DATE.html（首页也指向它）"
echo
if git rev-parse --git-dir >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
  git add docs/ .github/ >/dev/null
  git diff --staged --quiet || git commit -q -m "digest: $DATE"
  git push -q && echo "🚀 已推送，线上地址："
  echo "   $(grep -E '^READER_URL=' .env 2>/dev/null | cut -d= -f2-)"
else
  echo "还没配置 git 仓库。配置后重跑这条命令即可自动发布："
  echo "   git init && git add -A && git commit -m init"
  echo "   git remote add origin git@github.com:<你>/<仓库>.git && git push -u origin main"
fi
