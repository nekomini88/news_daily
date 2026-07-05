#!/usr/bin/env python3
"""
新闻日报文本 → Telegram 分段发送脚本
复用其他项目通用的发送逻辑
"""

import configparser
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.ini"

config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")

DEFAULT_CHAT = config.get("telegram", "chat_id", fallback="")
CHUNK_LIMIT = config.getint("telegram", "chunk_limit", fallback=3900)

HERMES_CMD = ["hermes", "send", "--to"]


def split_chunks(text: str):
    chunks = []
    pos = 0
    while pos < len(text):
        if len(text) - pos <= CHUNK_LIMIT:
            chunks.append(text[pos:])
            break
        cut = text[pos: pos + CHUNK_LIMIT]
        split = cut.rfind("\n\n")
        if split < 400:
            split = CHUNK_LIMIT
        chunks.append(text[pos: pos + split].strip())
        pos += split
    return chunks


def send_telegram(file_path: Path, chat_id: str):
    cmd = HERMES_CMD + [f"telegram:{chat_id}", "--file", str(file_path), "--json"]
    import subprocess
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        msg_id = "?"
        if result.stdout.strip():
            try:
                import json
                msg_id = json.loads(result.stdout).get("message_id", "?")
            except Exception:
                pass
        return True, msg_id
    except subprocess.CalledProcessError as e:
        return False, f"{e.returncode}: {e.stderr.strip()}"


def main():
    script_dir = SCRIPT_DIR

    text_file = sys.argv[1] if len(sys.argv) > 1 else ""
    chat_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CHAT

    if not text_file:
        import datetime
        today = datetime.date.today().isoformat()
        text_file = str(script_dir / "files" / today / f"news_{today}.txt")

    text_path = Path(text_file)
    if not text_path.is_file():
        print(f"❌ 找不到文本文件: {text_path}")
        sys.exit(1)

    if not chat_id:
        print("❌ 未配置 Telegram chat_id")
        sys.exit(1)

    base_dir = text_path.parent
    print(f"📄 文本文件: {text_path}")
    print(f"📺 目标频道: {chat_id}")
    print(f"📑 分段上限: {CHUNK_LIMIT} 字符")
    print()

    text = text_path.read_text(encoding="utf-8").strip()
    if not text:
        print("⚠️ 文本内容为空，不发送")
        sys.exit(0)

    chunks = split_chunks(text)
    print(f"✅ 分段完成: {len(chunks)} 段")
    for i, c in enumerate(chunks, 1):
        p = base_dir / f"chunk_{i}.txt"
        p.write_text(c, encoding="utf-8")
        print(f"   [{i}] {p.name} ({len(c)} chars)")

    print()
    print("📤 开始发送...")
    for attempt in range(1, 4):
        for i, chunk_file in enumerate(sorted(base_dir.glob("chunk_*.txt")), 1):
            ok, msg_id = send_telegram(chunk_file, chat_id)
            if ok:
                print(f"   [{i}] ✅ 已发送 (message_id={msg_id}) -> {chunk_file.name}")
            else:
                print(f"   [{i}] ❌ 发送失败: {msg_id}")
                if attempt < 3:
                    print(f"⚠️ 第 {attempt} 次重试中...")
                    break
                else:
                    sys.exit(1)
        else:
            print(f"🎉 全部完成！共发送 {len(chunks)} 条消息到 {chat_id}")
            return
    print()
    print(f"🎉 全部完成！共发送 {len(chunks)} 条消息到 {chat_id}")


if __name__ == "__main__":
    main()
