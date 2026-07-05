# news_daily - 每日新闻总结

独立 Telegram 项目，基于 Horizon 抓取 + OpenRouter 中文总结后推送。

## 目录

- `horizon_news.py`：抓取、LLM 总结、输出文本
- `news_daily.sh`：cron 入口，生成文本后由 `hermes send` 推送
- `config.ini`：私密配置，写入 `.gitignore`，不提交

## 本地运行

```bash
bash news_daily.sh
```

## 调度

使用系统 crontab，每天 8:00 执行：

```bash
0 8 * * * cd /root/news_daily && bash news_daily.sh >> /root/news_daily/cron.log 2>&1
```

## 隐私

`config.ini` 已写入 `.gitignore`，实际凭据不提交到 GitHub。
