#!/usr/bin/env python3
"""
每日新闻总结 — Horizon抓取+OpenRouter总结 → Telegram
"""
import asyncio
import configparser
import json
import os
import subprocess
import sys
import tempfile
import types
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# 读取配置
cfg = configparser.ConfigParser()
cfg_path = BASE_DIR / "config.ini"
if not cfg_path.exists():
    raise RuntimeError(f"缺少配置文件: {cfg_path}")
cfg.read(cfg_path, encoding="utf-8")

TARGET_CHAT = cfg.get("telegram", "chat_id", fallback="")
TELEGRAM_BOT_TOKEN = cfg.get("telegram", "bot_token", fallback="")

# Horizon 路径
HORIZON_SRC = Path("/root/Horizon/src")
sys.path.insert(0, str(HORIZON_SRC))

src_pkg = types.ModuleType("src")
src_pkg.__path__ = [str(HORIZON_SRC)]
sys.modules["src"] = src_pkg

from dotenv import load_dotenv
load_dotenv("/root/.hermes/.env")


def get_api_key():
    env_path = Path("/root/.hermes/.env")
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    return line[len("OPENROUTER_API_KEY="):].strip()
    return os.environ.get("OPENROUTER_API_KEY", "")


def call_llm(prompt, api_key, max_tokens=4096):
    data = json.dumps({
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "你是一位专业、客观、中立的新闻分析师。请用中文整理新闻总结。只输出中文内容。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )

    resp = urllib.request.urlopen(req, timeout=180)
    result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]


async def fetch_with_horizon():
    from src.storage.manager import StorageManager
    from src.orchestrator import HorizonOrchestrator

    data_dir = Path("/root/Horizon/data")
    storage = StorageManager(str(data_dir))
    config = storage.load_config()

    orch = HorizonOrchestrator(config, storage)

    since = orch._determine_time_window(force_hours=24)
    all_items = await orch.fetch_all_sources(since)
    print(f"📥 Horizon 抓取: {len(all_items)} 条", file=sys.stderr)

    if not all_items:
        return []

    merged = orch.merge_cross_source_duplicates(all_items)
    print(f"🔗 跨源去重后: {len(merged)} 条", file=sys.stderr)

    for item in merged:
        hn_score = item.metadata.get('score', 0) if item.source_type.value == 'hackernews' else 0
        item.ai_score = float(hn_score) or 1.0
        item.ai_summary = item.title

    merged.sort(key=lambda x: x.ai_score, reverse=True)
    selected = merged[:20]
    print(f"⚖️ 取前 {len(selected)} 条", file=sys.stderr)

    return selected


def format_items(items):
    lines = []
    for i, item in enumerate(items, 1):
        title = item.title or "无标题"
        url = item.url or ""
        source = item.source_type or "unknown"
        score = item.ai_score or 0

        lines.append(f"{i}. [{source}] {title}")
        lines.append(f"   热度: {score} | {url}")

        if hasattr(item, 'comments') and item.comments:
            for c in item.comments[:3]:
                text = c.get('text', '')[:120].replace('\n', ' ')
                author = c.get('author', '')
                lines.append(f"   💬 {author}: {text}")
        lines.append("")

    return "\n".join(lines)


def generate_summary(news_text, count, api_key):
    prompt = f"""请根据以下新闻素材，整理为中文新闻总结。

## 新闻素材（共{count}条）
{news_text}

## 要求
1. 分类列出所有重要新闻（政治/经济/科技/国际/社会/体育）
2. 每条：标题 + 核心事实（1-2句）+ 来源类型
3. 最后：整体趋势分析（1-2段）
4. 只使用真实新闻，不编造
5. 语气客观专业
6. 如果新闻不足5条，如实报告

请开始总结：
"""
    return call_llm(prompt, api_key)


def send_via_hermes(chat_id, text):
    """通过 hermes send 发送文本"""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(text)
            tmp_path = f.name

        result = subprocess.run(
            ["hermes", "send", "--to", f"telegram:{chat_id}", "--file", tmp_path],
            capture_output=True, text=True, timeout=30
        )
        os.unlink(tmp_path)

        if result.returncode == 0:
            return True
        else:
            print(f"hermes send error: {result.stderr}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return False


def main():
    api_key = get_api_key()
    if not api_key:
        print("❌ 未找到 OPENROUTER_API_KEY", file=sys.stderr)
        sys.exit(1)

    print("🔄 开始抓取新闻...")
    items = asyncio.run(fetch_with_horizon())

    if not items:
        print("⚠️ 未抓取到任何新闻")
        summary = "今日无新闻可总结。"
    else:
        news_text = format_items(items)
        print(f"📝 格式化: {len(news_text)} 字符", file=sys.stderr)

        print("🤖 生成新闻总结...", file=sys.stderr)
        summary = generate_summary(news_text, len(items), api_key)

    # 保存到本地
    now = datetime.now(timezone(timedelta(hours=8)))
    date_str = now.strftime("%Y-%m-%d")
    output_dir = BASE_DIR / "files" / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"news_{date_str}.txt"
    output_path.write_text(summary, encoding="utf-8")
    print(f"💾 已保存: {output_path}", file=sys.stderr)

    # 返回文本供 cron 脚本发送
    print(summary)
    return summary


if __name__ == "__main__":
    main()
