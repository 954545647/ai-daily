#!/usr/bin/env python3
"""AI 日报 · 推送端（飞书群机器人 Webhook，纯 HTTPS，跨平台零依赖）

两种卡片形态：
  single  一张大卡片，末尾按钮进「逐条学习页」（默认，消息最少）
  split   每条一张小卡片，在飞书里像聊天一样一条一条往下看

用法：
    python3 notify.py                 # 按 .env 里的 DIGEST_MODE 发
    python3 notify.py --mode split    # 强制逐条
    python3 notify.py --ping          # 只测链路
    python3 notify.py --force         # 当天发过也重发
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import load_env  # noqa: E402

ROOT = Path(__file__).parent
DIGESTS = ROOT / "digests"
LOGS = ROOT / "logs"
WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def feishu_sign(secret: str, timestamp: str) -> str:
    """飞书自定义机器人签名：以 '<timestamp>\\n<secret>' 为密钥做 HMAC-SHA256。"""
    key = f"{timestamp}\n{secret}".encode()
    return base64.b64encode(hmac.new(key, b"", digestmod=hashlib.sha256).digest()).decode()


def post_webhook(payload: dict, cfg: dict[str, str], timeout: int = 30) -> dict:
    hook = cfg.get("FEISHU_WEBHOOK", "").strip()
    if not hook:
        sys.exit("❌ 没有配置 FEISHU_WEBHOOK。见 .env.example 里的获取步骤")

    secret = cfg.get("FEISHU_WEBHOOK_SECRET", "").strip()
    if secret:
        ts = str(int(time.time()))
        payload = {**payload, "timestamp": ts, "sign": feishu_sign(secret, ts)}

    req = urllib.request.Request(
        hook, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"❌ Webhook HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")

    code = res.get("code", res.get("StatusCode", 0))
    if code not in (0, None):
        sys.exit(f"❌ 飞书返回错误 {code}: {res.get('msg') or res.get('StatusMessage')}")
    return res


def _card(title: str, elements: list[dict], template: str = "blue") -> dict:
    return {"msg_type": "interactive", "card": {
        "config": {"wide_screen_mode": True},
        "header": {"template": template,
                   "title": {"tag": "plain_text", "content": title}},
        "elements": elements,
    }}


def _btn(text: str, url: str, kind: str = "primary") -> dict:
    return {"tag": "action", "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": text},
         "type": kind, "url": url}]}


def _link(url: str, source: str) -> str:
    return f"[读原文 →]({url})" + (f" · {source}" if source else "")


# ---------------------------------------------------------------- single：大卡

def build_card(d: dict, reader_url: str = "") -> dict:
    dt = datetime.strptime(d["date"], "%Y-%m-%d")
    els: list[dict] = []

    if d.get("intro"):
        els.append({"tag": "div", "text": {"tag": "lark_md", "content": f"*{d['intro']}*"}})

    items = d.get("items", [])

    # 有网址时：卡片只放第 1 条，底部一个「下一条」按钮接到网页第 2 条
    if reader_url and items:
        it = items[0]
        els.append({"tag": "hr"})
        tags = " ".join(f"<font color='grey'>#{t}</font>" for t in it.get("tags", [])[:2])
        md = [f"**01 / {len(items):02d} · {it['title']}** {tags}", "",
              f"**讲了什么** {it['summary']}"]
        if it.get("so_what"):
            md.append(f"**为什么值得看** {it['so_what']}")
        if it.get("how_to_use"):
            md.append(f"**可以怎么用** {it['how_to_use']}")
        md.append(_link(it["url"], it.get("source", "")))
        els.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(md)}})
        els.append(_btn("下一条 →", f"{reader_url}#s2"))
        els.append({"tag": "note", "elements": [
            {"tag": "plain_text",
             "content": f"点「下一条」逐条往下看，共 {len(items)} 条 · 进度自动保存"}]})
        return _card(f"🤖 AI 每天学一点 · {dt.month}月{dt.day}日 {WEEKDAY[dt.weekday()]}", els)

    # 没有网址时：退回完整长卡片（按钮没法跳，索性一次给全）
    for i, it in enumerate(items, 1):
        els.append({"tag": "hr"})
        tags = " ".join(f"<font color='grey'>#{t}</font>" for t in it.get("tags", [])[:2])
        md = [f"**{i:02d} · {it['title']}** {tags}", "",
              f"**讲了什么** {it['summary']}"]
        if it.get("so_what"):
            md.append(f"**为什么值得看** {it['so_what']}")
        if it.get("how_to_use"):
            md.append(f"**可以怎么用** {it['how_to_use']}")
        md.append(_link(it["url"], it.get("source", "")))
        els.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(md)}})

    tail = []
    if d.get("action"):
        tail.append(f"**📌 今天花 10 分钟** {d['action']}")
    if d.get("watch"):
        tail.append(f"**👀 值得盯的一条线** {d['watch']}")
    if tail:
        els += [{"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(tail)}}]

    if d.get("sources_note"):
        els.append({"tag": "note", "elements": [
            {"tag": "plain_text", "content": d["sources_note"][:180]}]})

    return _card(f"🤖 AI 每天学一点 · {dt.month}月{dt.day}日 {WEEKDAY[dt.weekday()]}", els)


# ---------------------------------------------------------------- split：逐条

def build_intro_card(d: dict, reader_url: str = "") -> dict:
    dt = datetime.strptime(d["date"], "%Y-%m-%d")
    toc = "\n".join(f"**{i:02d}** {it['title']}" for i, it in enumerate(d["items"], 1))
    els = [{"tag": "div", "text": {"tag": "lark_md", "content": f"*{d.get('intro', '')}*"}},
           {"tag": "hr"},
           {"tag": "div", "text": {"tag": "lark_md", "content": toc}}]
    if reader_url:
        els.append(_btn("📖 一次只学一条 →", f"{reader_url}#s0"))
    return _card(f"🤖 今天 {len(d['items'])} 条 · {dt.month}月{dt.day}日 {WEEKDAY[dt.weekday()]}", els)


def build_item_card(d: dict, idx: int, reader_url: str = "") -> dict:
    it = d["items"][idx]
    total = len(d["items"])
    tags = " · ".join(it.get("tags", [])[:2])
    md = [f"**{it['title']}**", "", f"**讲了什么** {it['summary']}"]
    if it.get("so_what"):
        md.append(f"**为什么值得看** {it['so_what']}")
    if it.get("how_to_use"):
        md.append(f"**可以怎么用** {it['how_to_use']}")
    md.append(_link(it["url"], it.get("source", "")))
    els = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(md)}}]

    if reader_url and idx + 1 < total:
        els.append(_btn("下一条 →", f"{reader_url}#s{idx + 2}"))
    elif idx + 1 == total and d.get("action"):
        els += [{"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md",
                                        "content": f"**📌 今天花 10 分钟** {d['action']}"}}]
    label = f"{idx + 1:02d} / {total:02d}" + (f" · {tags}" if tags else "")
    return _card(label, els)


def send_split(d: dict, cfg: dict, reader_url: str) -> int:
    post_webhook(build_intro_card(d, reader_url), cfg)
    time.sleep(1.2)                      # 飞书自定义机器人有频率限制
    for i in range(len(d["items"])):
        post_webhook(build_item_card(d, i, reader_url), cfg)
        time.sleep(1.2)
    return len(d["items"]) + 1


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--mode", choices=["single", "split"], default=None)
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--force", action="store_true", help="当天已推过也再推一次")
    args = ap.parse_args()

    cfg = load_env()
    if args.ping:
        post_webhook({"msg_type": "text",
                      "content": {"text": "✅ ai-daily 推送链路连通测试，忽略即可"}}, cfg)
        print("✅ 测试消息已送达")
        return

    p = DIGESTS / f"{args.date}.json"
    if not p.exists():
        sys.exit(f"❌ 找不到 {p}，先跑 python3 summarize.py")
    d = json.loads(p.read_text(encoding="utf-8"))

    LOGS.mkdir(exist_ok=True)
    sf = LOGS / "sent.json"
    sent = {}
    if sf.exists():
        try:
            sent = json.loads(sf.read_text())
        except Exception:
            sent = {}
    if args.date in sent and not args.force:
        print(f"⚠️  {args.date} 已经推送过（{sent[args.date]}），跳过。要重发加 --force")
        return

    mode = args.mode or cfg.get("DIGEST_MODE", "single")
    base = cfg.get("READER_URL", "").strip()
    if not base:
        page = ""
    elif base.endswith(".html"):
        page = base
    else:
        page = f"{base.rstrip('/')}/{args.date}.html"

    if mode == "split":
        n = send_split(d, cfg, page)
        print(f"✅ 已推送 {n} 张卡片（逐条模式）")
    else:
        post_webhook(build_card(d, page), cfg)
        print(f"✅ 已推送单张卡片（{len(d.get('items', []))} 条）"
              + (f"，下一条按钮指向 {page}" if page else "，未配置网址") )

    sent[args.date] = datetime.now().strftime("%F %T")
    sf.write_text(json.dumps(sent, indent=2))


if __name__ == "__main__":
    main()
