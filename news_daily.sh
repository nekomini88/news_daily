#!/bin/bash
set -uo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

today=$(date +%Y-%m-%d)
out_dir="$BASE_DIR/files/$today"
mkdir -p "$out_dir"

echo "📰 开始生成 ${today} 每日新闻总结..."

"/root/Horizon/.venv/bin/python3" "$BASE_DIR/news_fetcher.py" > "$out_dir/news_${today}.txt"
text_file="$out_dir/news_${today}.txt"

# 发送 Telegram，使用本项目的专用发送器
"$BASE_DIR/send_tg_report.py" "$text_file"

echo "🎉 每日新闻总结完成！"