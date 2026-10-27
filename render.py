#!/usr/bin/env python3
"""AI 日报 · 渲染推送端

读 digests/YYYY-MM-DD.json（AI 精挑 + 写好的沉淀），渲染成飞书 markdown 并推送。

用法：
    python3 render.py --dry-run          # 只打印，不发送
    python3 render.py --send             # 推送到飞书
    python3 render.py --date 2026-10-28 --send
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

ROOT = Path(__file__).parent
DIGESTS = ROOT / "digests"
DIGESTS.mkdir(exist_ok=True)

WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DIVIDER = "────────────────"


def load(date: str) -> dict:
    p = DIGESTS / f"{date}.json"
    if not p.exists():
        sys.exit(f"❌ 找不到 {p}，先让 AI 生成当天的精选 JSON")
    d = json.loads(p.read_text(encoding="utf-8"))

    errs = []
    if not d.get("items"):
        errs.append("items 为空")
    if len(d.get("items", [])) > 8:
        errs.append(f"条目 {len(d['items'])} 条，超过 8 条上限")
    for i, it in enumerate(d.get("items", []), 1):
        for f in ("title", "summary", "url"):
            if not it.get(f):
                errs.append(f"第 {i} 条缺字段 {f}")
    if errs:
        sys.exit("❌ 日报数据不合格：\n  - " + "\n  - ".join(errs))
    return d


def render(d: dict) -> str:
    dt = datetime.strptime(d["date"], "%Y-%m-%d")
    head = f"**🤖 AI 每天学一点 · {dt.month}月{dt.day}日 {WEEKDAY[dt.weekday()]}**"

    parts = [head, ""]
    if d.get("intro"):
        parts += [f"*{d['intro']}*", ""]

    for i, it in enumerate(d["items"], 1):
        parts.append(DIVIDER)
        tags = "".join(f"`{t}`" for t in it.get("tags", [])[:2])
        parts.append(f"**{i:02d} · {it['title']}**{'  ' + tags if tags else ''}")
        parts.append("")
        parts.append(f"**讲了什么**　{it['summary']}")
        if it.get("so_what"):
            parts.append(f"**为什么值得看**　{it['so_what']}")
        if it.get("how_to_use"):
            parts.append(f"**可以怎么用**　{it['how_to_use']}")
        src = it.get("source", "")
        link = f"[读原文 →]({it['url']})"
        parts.append(f"{link}{'  ·  ' + src if src else ''}")
        parts.append("")

    if d.get("action"):
        parts += [DIVIDER, f"**📌 今天花 10 分钟**　{d['action']}", ""]
    if d.get("watch"):
        parts += [f"**👀 值得盯的一条线**　{d['watch']}", ""]
    if d.get("sources_note"):
        parts += [f"*{d['sources_note']}*"]

    return "\n".join(parts).rstrip()


def send(md: str, date: str) -> None:
    """优先走 Webhook（跨平台零依赖）；没配 webhook 时退回 lark-cli。"""
    from env import load_env

    cfg = load_env()
    if cfg.get("FEISHU_WEBHOOK"):
        import notify
        d = json.loads((DIGESTS / f"{date}.json").read_text(encoding="utf-8"))
        notify.post_webhook(notify.build_card(d), cfg)
        print("✅ 已通过 Webhook 推送到飞书")
        return

    target = (["--chat-id", config.FEISHU_CHAT_ID] if getattr(config, "FEISHU_CHAT_ID", "")
              else ["--user-id", config.FEISHU_BOT_USER_ID])
    cmd = [
        "lark-cli", "im", "+messages-send",
        "--as", "bot",
        *target,
        "--markdown", md,
        "--idempotency-key", f"aidaily-{date}",   # 同一天重复运行不会发两次
        "--format", "json",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        sys.exit(f"❌ 飞书推送失败：\n{r.stderr[:600]}")
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = {}
    if not out.get("ok"):
        sys.exit(f"❌ 飞书返回异常：{r.stdout[:600]}")
    print(f"✅ 已推送到飞书（message_id={out.get('data', {}).get('message_id')}）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = load(args.date)
    md = render(d)

    (DIGESTS / f"{args.date}.md").write_text(md, encoding="utf-8")
    print(f"📄 已归档 digests/{args.date}.md（{len(md)} 字符）")

    if args.dry_run or not args.send:
        print("\n" + "=" * 60 + "\n" + md + "\n" + "=" * 60)
        return

    send(md, args.date)


if __name__ == "__main__":
    main()
