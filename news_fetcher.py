#!/usr/bin/env python3
"""
每日新闻抓取+中文总结，不依赖 Horizon/Reddit 受限来源。

当前来源：
- HackerNews
- BBC中文 RSS
- 纽约时报中文网 RSS
- GitHub releases
"""
import asyncio
import html
import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from feedparser import parse as parse_feed

sys.path.insert(0, str(Path(__file__).resolve().parent))

DATE_FMT = "%Y-%m-%d"
TZ8 = timezone(timedelta(hours=8))

logger = logging.getLogger(__name__)

SOURCES = [
    {"name": "HackerNews", "kind": "hn", "limit": 24},
    {"name": "BBC中文", "kind": "rss", "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "limit": 20},
    {"name": "纽约时报中文网", "kind": "rss", "url": "https://cn.nytimes.com/rss/homepage.xml", "limit": 20},
    {"name": "新浪科技", "kind": "rss", "url": "https://rss.sina.com.cn/news/allnews/tech.xml", "limit": 20},
    {"name": "新浪体育", "kind": "rss", "url": "https://rss.sina.com.cn/news/allnews/sports.xml", "limit": 20},
    {"name": "36氪", "kind": "rss", "url": "https://36kr.com/feed", "limit": 20},
    {"name": "澎湃新闻", "kind": "rss", "url": "https://feedx.net/rss/thepaper.xml", "limit": 20},
    {"name": "界面新闻", "kind": "rss", "url": "https://feedx.net/rss/jiemian.xml", "limit": 20},
    {"name": "虎嗅", "kind": "rss", "url": "https://feedx.net/rss/huxiu.xml", "limit": 20},
    {"name": "人民网国际", "kind": "rss", "url": "http://www.people.com.cn/rss/world.xml", "limit": 20},
]


def today() -> str:
    return datetime.now(TZ8).strftime(DATE_FMT)


def time_window() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _request_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; news-bot/1.0; +https://example.com/bot)",
            "Accept": "application/json,text/xml,application/xml,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


async def fetch_hn(limit: int) -> list[dict]:
    data = json.loads(_request_text("https://hacker-news.firebaseio.com/v0/topstories.json"))
    ids = data[:limit]
    items = []
    for item_id in ids:
        try:
            item = json.loads(_request_text(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"))
        except Exception as exc:
            logger.warning("HN fetch failed for %s: %s", item_id, exc)
            continue
        if not item:
            continue
        items.append({
            "title": item.get("title") or "",
            "url": item.get("url") or f"https://news.ycombinator.com/item?id={item_id}",
            "score": item.get("score") or 0,
            "source": "HackerNews",
            "published_at": datetime.fromtimestamp(item.get("time") or 0, tz=timezone.utc),
        })
    return items


async def fetch_rss(name: str, url: str, limit: int) -> list[dict]:
    try:
        text = _request_text(url)
        feed = parse_feed(text)
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", name, exc)
        return []
    items = []
    for entry in feed.entries[:limit]:
        published = None
        for field in ["published", "updated", "created"]:
            raw = entry.get(field)
            if not raw:
                continue
            try:
                from email.utils import parsedate_to_datetime
                published = parsedate_to_datetime(raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                break
            except Exception:
                continue
        if not published:
            published = datetime.now(timezone.utc)
        items.append({
            "title": entry.get("title") or "",
            "url": entry.get("link") or url,
            "score": None,
            "source": name,
            "published_at": published,
        })
    return items


async def fetch_github_releases(owner: str, repo: str, limit: int) -> list[dict]:
    url = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/releases?per_page={limit}&sort=updated&direction=desc"
    try:
        text = _request_text(url)
        releases = json.loads(text)
    except Exception as exc:
        logger.warning("GitHub fetch failed for %s/%s: %s", owner, repo, exc)
        return []
    items = []
    for release in releases[:limit]:
        published_at = datetime.fromisoformat((release.get("published_at") or "") .replace("Z", "+00:00"))
        items.append({
            "title": release.get("name") or release.get("tag_name") or f"{owner}/{repo} release",
            "url": release.get("html_url") or f"https://github.com/{owner}/{repo}/releases",
            "score": None,
            "source": f"GitHub:{owner}/{repo}",
            "published_at": published_at,
        })
    return items


async def fetch_all() -> list[dict]:
    since = time_window()
    raw = []
    for source in SOURCES:
        try:
            weight = 15 if source.get("name") == "HackerNews" else 5
            if source["kind"] == "hn":
                batch = await fetch_hn(source["limit"])
            elif source["kind"] == "rss":
                batch = await fetch_rss(source["name"], source["url"], source["limit"])
            elif source["kind"] == "github_releases":
                batch = await fetch_github_releases(source["owner"], source["repo"], source["limit"])
            else:
                continue
            for item in batch:
                if not item.get("published_at"):
                    continue
                if item["published_at"].astimezone(timezone.utc) < since:
                    continue
                item = dict(item)
                item["weight"] = weight
                raw.append(item)
        except Exception as exc:
            logger.warning("Source fetch failed for %s: %s", source.get("name"), exc)

    by_source = {}
    for item in raw:
        by_source.setdefault(item["source"], []).append(item)
    for k in by_source:
        by_source[k].sort(key=lambda x: x["published_at"], reverse=True)

    guaranteed = []
    used_ids = set()
    for src, items in by_source.items():
        quota = max(3, len(items) // 4)
        for item in items[:quota]:
            if item["title"] not in used_ids:
                guaranteed.append(item)
                used_ids.add(item["title"])

    remaining = sorted(
        [item for item in raw if item["title"] not in used_ids],
        key=lambda x: (x.get("published_at") or datetime.min, x.get("weight", 0)),
        reverse=True,
    )[:90]

    combined = guaranteed + remaining
    combined.sort(key=lambda x: x["published_at"], reverse=True)
    return combined[:100]


def format_items(items):
    lines = []
    for i, item in enumerate(items, 1):
        title = item.get("title") or "无标题"
        url = item.get("url") or ""
        source = item.get("source") or "unknown"
        score = item.get("score") or 0
        lines.append(f"{i}. [{source}] {title}")
        lines.append(f"   热度: {score} | {url}")
        lines.append("")
    return "\n".join(lines)


def call_llm(prompt: str, api_key: str, max_tokens: int = 4096) -> str:
    data = json.dumps({
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "你是一位专业、客观、中立的新闻分析师。请用中文整理新闻总结。只输出中文内容。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]


def generate_summary(news_text: str, count: int, api_key: str) -> str:
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


def main():
    api_key = os.environ.get("OPENROUTER_API_KEY") or ""
    if not api_key:
        env_path = Path("/root/.hermes/.env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    api_key = line[len("OPENROUTER_API_KEY="):].strip()
                    break
    if not api_key:
        print("❌ 未找到 OPENROUTER_API_KEY", file=sys.stderr)
        sys.exit(1)

    print("🔄 开始抓取新闻...", file=sys.stderr)
    items = asyncio.run(fetch_all())
    if not items:
        print("⚠️ 未抓取到任何新闻", file=sys.stderr)
        summary = "今日无新闻可总结。"
        print(summary)
        return summary

    news_text = format_items(items)
    print(f"📝 格式化: {len(news_text)} 字符", file=sys.stderr)
    print("🤖 生成新闻总结...", file=sys.stderr)
    summary = generate_summary(news_text, len(items), api_key)

    now = datetime.now(TZ8)
    date_str = now.strftime(DATE_FMT)
    output_dir = Path(__file__).resolve().parent / "files" / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"news_{date_str}.txt"
    output_path.write_text(summary, encoding="utf-8")
    print(f"💾 已保存: {output_path}", file=sys.stderr)
    print(summary)
    return summary


if __name__ == "__main__":
    main()
