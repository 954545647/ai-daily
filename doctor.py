#!/usr/bin/env python3
"""AI 日报 · 自检。换新电脑第一件事跑这个。

    python3 doctor.py           # 全项检查（会真的调一次模型，花一点点钱）
    python3 doctor.py --no-llm  # 跳过模型调用
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch  # noqa: E402
from env import api_key, load_env  # noqa: E402

ROOT = Path(__file__).parent
OK, BAD, WARN = "✅", "❌", "⚠️ "


def mask(s: str) -> str:
    return f"{s[:6]}…{s[-4:]}" if len(s) > 12 else "(太短)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    print(f"\n{OK} Python {platform.python_version()}  ·  {platform.system()} {platform.machine()}\n")

    cfg = load_env()
    problems = 0

    # 1. .env
    envf = ROOT / ".env"
    if envf.exists():
        mode = oct(envf.stat().st_mode)[-3:]
        flag = OK if mode in ("600", "400") else WARN
        print(f"{flag} .env 存在（权限 {mode}{'，建议 chmod 600' if mode not in ('600','400') else ''}）")
    else:
        print(f"{BAD} 没有 .env —— 复制 .env.example 并填写")
        problems += 1

    # 2. API key
    key = api_key(cfg)
    if key:
        print(f"{OK} {cfg['LLM_PROVIDER']} key: {mask(key)}")
    else:
        print(f"{BAD} 没找到 {cfg['LLM_PROVIDER']} 的 API key")
        problems += 1

    # 3. Webhook
    hook = cfg.get("FEISHU_WEBHOOK", "")
    print(f"{OK} 飞书 Webhook: {mask(hook)}" if hook else f"{BAD} 没配置 FEISHU_WEBHOOK")
    if not hook:
        problems += 1

    # 4. 数据源
    print("\n── 数据源连通性 ──")
    down = []
    for s in fetch.SOURCES:
        url = s.get("url") or {
            "hn": "https://hn.algolia.com/api/v1/search?query=ai&tags=story&hitsPerPage=1",
            "hf_papers": "https://huggingface.co/api/daily_papers?limit=1",
            "gh_trending": "https://github.com/trending?since=daily",
            "anthropic": "https://www.anthropic.com/news",
        }.get(s["kind"], "")
        try:
            urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": fetch.UA}), timeout=15).read(64)
            print(f"  {OK} {s['name']}")
        except Exception as e:
            print(f"  {BAD} {s['name']}: {type(e).__name__}")
            down.append(s["name"])
    if down:
        print(f"\n{WARN} {len(down)} 个源不通，不影响运行（会自动跳过）")

    # 5. 模型
    if not args.no_llm and key:
        print("\n── 模型调用 ──")
        try:
            import summarize
            r = summarize.call_llm(
                [{"role": "user", "content": '只回复这个 JSON：{"ok": true}'}], cfg, timeout=60)
            print(f"  {OK} 返回：{r[:80]}")
        except SystemExit as e:
            print(f"  {BAD} {e}")
            problems += 1

    print()
    if problems:
        print(f"{BAD} 有 {problems} 个问题需要先解决")
        sys.exit(1)
    print(f"{OK} 全部就绪，可以跑 ./run.sh 了\n")


if __name__ == "__main__":
    main()
