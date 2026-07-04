#!/bin/bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

today=$(date +%Y-%m-%d)
out_dir="$BASE_DIR/files/$today"
mkdir -p "$out_dir"

echo "📰 开始生成 ${today} 每日新闻总结..."

"/root/Horizon/.venv/bin/python3" "$BASE_DIR/horizon_news.py" > "$out_dir/news_${today}.txt"
text_file="$out_dir/news_${today}.txt"

echo "📺 发送 Telegram..."
export PATH="$HOME/.local/bin:$PATH"
hermes send --to "telegram:-1004493342362" --file "$text_file" || echo "❌ Telegram 发送失败"

echo "🎉 每日新闻总结完成！"
