#!/usr/bin/env python3
"""AI 日报 · 总结端（不依赖 DSH，只需要一个模型 API key）

两遍法，防止模型编造：
  第一遍：从候选池里挑出 6 条（只决定「选哪些」）
  落地：  把每条的原网页正文抓下来
  第二遍：只根据抓到的正文重写 summary / so_what / how_to_use

用法：
    python3 summarize.py              # 生成今天
    python3 summarize.py --dry-run    # 只看 prompt，不调模型
    python3 summarize.py --count 8    # 改条数
    python3 summarize.py --no-ground  # 跳过第二遍（快，但可能编造）
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from env import api_key, load_env  # noqa: E402

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DIGESTS = ROOT / "digests"
DIGESTS.mkdir(exist_ok=True)

WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

SYSTEM = """你是一位 AI 领域的技术编辑，读者是中文的技术从业者和学习者。
你的任务是写中文日报：用事实说话，给判断，给可执行的动作。
绝不编造原文没有的数字、版本号、模型名、公司名、人名。"""

PICK_RULES = """挑选标准（按优先级）：
1. 模型/产品发布类 与 AI 工具实战类，两类大致均衡
2. 同一来源不超过 2 条
3. 纯论文除非有明显实践价值（能直接改变做法），否则不选
4. 优先「读者今天就能动手验证」的内容，而不是宏观评论"""

WRITE_RULES = """写作要求：
- 标题说清楚「是什么」，不要卖关子
- summary：2-3 句白话，只写原文里明确出现的事实
- so_what：给判断，说明这件事改变了什么认知或做法
- how_to_use：具体到能立刻执行的动作，不要写「多关注」这种空话
- **原文没提到的信息一律不写**，宁可少写，不许猜测补全
- 特别禁止：编造模型名称/版本号/价格/日期/人名，除非原文里逐字出现"""


# ---------------------------------------------------------------- 模型调用

def call_llm(messages: list[dict], cfg: dict[str, str], timeout: int = 180) -> str:
    provider = cfg.get("LLM_PROVIDER", "deepseek").lower()
    key = api_key(cfg)
    if not key:
        sys.exit("❌ 没有 API key。把 .env.example 复制成 .env 并填入 DEEPSEEK_API_KEY")

    if provider == "anthropic":
        url = (cfg.get("LLM_BASE_URL") or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        payload = {
            "model": cfg.get("LLM_MODEL") or "claude-sonnet-4-5",
            "max_tokens": 8000,
            "system": messages[0]["content"],
            "messages": messages[1:],
        }
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        url = (cfg.get("LLM_BASE_URL") or "https://api.deepseek.com").rstrip("/") + "/chat/completions"
        payload = {
            "model": cfg.get("LLM_MODEL") or "deepseek-chat",
            "messages": messages,
            "temperature": 0.3,          # 压低随机性，减少脑补
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {key}"}

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers})

    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            if provider == "anthropic":
                return "".join(b.get("text", "") for b in data.get("content", []))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (400, 401, 403):
                break
            time.sleep(3 * (attempt + 1))
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (attempt + 1))
    sys.exit(f"❌ 模型调用失败：{last}")


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError("模型没有返回合法 JSON")


# ---------------------------------------------------------------- 抓原文

def fetch_page_text(url: str, limit: int = 3000) -> str:
    """抓原文正文，失败返回空串（不抛异常）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(400_000).decode("utf-8", "ignore")
    except Exception:
        return ""
    raw = re.sub(r"<(script|style|nav|footer|header|svg)[^>]*>.*?</\1>", " ",
                 raw, flags=re.S | re.I)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    txt = re.sub(r"\s+", " ", txt).strip()
    # 砍掉页面通用的导航废话，从正文关键词附近开始
    for anchor in ("Related articles", "Skip to main content", "Notes", "Comments"):
        i = txt.find(anchor)
        if 0 < i < 600:
            txt = txt[i + len(anchor):]
            break
    return txt[:limit]


# ---------------------------------------------------------------- 阶段

def recent_urls(days: int = 3) -> set[str]:
    urls: set[str] = set()
    for p in sorted(DIGESTS.glob("*.json"))[-days:]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            urls |= {i.get("url", "") for i in d.get("items", [])}
        except Exception:
            continue
    return {u for u in urls if u}


def pick_messages(cands: list[dict], count: int, seen: set[str]) -> list[dict]:
    today = datetime.now()
    lines = []
    for i, c in enumerate(cands, 1):
        if c["url"] in seen:
            continue
        s = (c.get("summary") or "").replace("\n", " ")[:400]
        e = c.get("engagement") or {}
        extra = ""
        if e.get("points"):
            extra = f" HN{e['points']}分"
        elif e.get("stars_today"):
            extra = f" 今日+{e['stars_today']}star"
        elif e.get("upvotes"):
            extra = f" {e['upvotes']}赞"
        lines.append(
            f"[{i}] 源:{c['source']} | 标签:{','.join(c.get('tags', []))} | "
            f"分:{c.get('score')}{extra}\n  标题: {c['title']}\n"
            f"  摘要: {s or '(无)'}\n  链接: {c['url']}")

    user = f"""今天是 {today.year}年{today.month}月{today.day}日 {WEEKDAY[today.weekday()]}。

候选池（共 {len(lines)} 条，已按综合分排序）：

{chr(10).join(lines)}

{PICK_RULES}

只做一件事：挑出 {count} 条，输出 JSON：
{{"picks": [{{"url": "原样照抄候选里的链接", "title": "中文标题", "why": "为什么选它，一句话"}}]}}

picks 必须正好 {count} 条，url 必须从候选里原样复制。"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def write_messages(pages: list[dict], count: int) -> list[dict]:
    blocks = []
    for i, p in enumerate(pages, 1):
        body = p["text"] or p["fallback"]
        blocks.append(
            f"### 第 {i} 条（来源:{p['source']}，链接:{p['url']}）\n"
            f"抓到的原文（可能含页面杂讯，只取与主题相关的部分）：\n{body}\n")

    user = f"""下面是从原文抓到的内容，共 {len(blocks)} 条。

{chr(10).join(blocks)}

请基于上面的原文写日报，输出 JSON：
{{
  "intro": "一句话点出今天的主线（60 字内）",
  "items": [
    {{
      "title": "中文标题",
      "summary": "2-3 句事实",
      "so_what": "为什么值得看",
      "how_to_use": "可以怎么用",
      "url": "上面给出的链接，原样照抄",
      "source": "上面给出的来源名",
      "tags": ["模型发布"]
    }}
  ],
  "action": "今天花 10 分钟能做完的一件具体事",
  "watch": "值得持续关注的一条线索",
  "sources_note": "一句话说明信息来源范围"
}}

{WRITE_RULES}"""

    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


# ---------------------------------------------------------------- 校验

def validate(d: dict, count: int, valid_urls: set[str]) -> list[str]:
    errs = []
    items = d.get("items")
    if not isinstance(items, list):
        return ["items 不是数组"]
    if not (4 <= len(items) <= 8):
        errs.append(f"items 有 {len(items)} 条，应在 4-8 之间")
    for i, it in enumerate(items, 1):
        for f in ("title", "summary", "so_what", "how_to_use", "url"):
            if not str(it.get(f, "")).strip():
                errs.append(f"第 {i} 条缺 {f}")
        if it.get("url") and valid_urls and it["url"] not in valid_urls:
            errs.append(f"第 {i} 条 url 不在候选池里：{str(it['url'])[:70]}")
    if not d.get("intro"):
        errs.append("缺 intro")
    return errs


def validate_picks(d: dict, count: int, valid_urls: set[str]) -> list[str]:
    picks = d.get("picks")
    if not isinstance(picks, list):
        return ["picks 不是数组"]
    if len(picks) < max(4, count - 1):
        return [f"picks 只有 {len(picks)} 条，需要 {count} 条"]
    bad = [p.get("url", "")[:60] for p in picks if p.get("url") not in valid_urls]
    return [f"这些 url 不在候选池里：{bad[:3]}"] if bad else []


def call_with_repair(messages, cfg, validator, label):
    d = extract_json(call_llm(messages, cfg))
    errs = validator(d)
    if errs:
        print(f"⚠️  {label}输出不合格，回炉重试：{errs[:2]}")
        messages = messages + [
            {"role": "assistant", "content": json.dumps(d, ensure_ascii=False)[:2000]},
            {"role": "user", "content": "上面的输出有这些问题：" + "；".join(errs)
                                        + "。请修正后只输出完整 JSON，url 原样照抄。"},
        ]
        d = extract_json(call_llm(messages, cfg))
        errs = validator(d)
        if errs:
            sys.exit(f"❌ {label}两次都不合格：\n  - " + "\n  - ".join(errs))
    return d


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--count", type=int, default=config.DIGEST_TARGET_COUNT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-ground", action="store_true", help="跳过抓原文的第二遍")
    args = ap.parse_args()

    out_path = DIGESTS / f"{args.date}.json"
    if out_path.exists() and not args.force and not args.dry_run:
        print(f"⚠️  {out_path.name} 已存在，跳过（--force 覆盖）")
        return

    src = DATA / f"candidates-{args.date}.json"
    if not src.exists():
        sys.exit(f"❌ 找不到 {src}，先跑 python3 fetch.py")
    cands = json.loads(src.read_text(encoding="utf-8"))["candidates"]
    by_url = {c["url"]: c for c in cands}

    seen = recent_urls()
    msgs = pick_messages(cands, args.count, seen)

    if args.dry_run:
        print(f"候选 {len(cands)} 条，排除已推过 {len(seen)} 条")
        print(f"第一遍 prompt {len(msgs[1]['content'])} 字符（约 {len(msgs[1]['content']) // 3} token）\n")
        print(msgs[1]["content"][:2200])
        return

    cfg = load_env()
    print(f"🤖 第一遍：{cfg['LLM_MODEL']} 挑选…")
    raw = call_with_repair(
        msgs, cfg, lambda x: validate_picks(x, args.count, set(by_url)), "挑选")
    picked = [p for p in raw["picks"] if p.get("url") in by_url][: args.count]
    if len(picked) < 4:
        sys.exit(f"❌ 挑选结果不足（{len(picked)} 条），请重试")

    label = "读候选摘要（未抓原文）" if args.no_ground else "抓原文"
    print(f"📥 第二遍：{label} {len(picked)} 条…")
    pages = []
    for p in picked:
        c = by_url[p["url"]]
        text = "" if args.no_ground else fetch_page_text(p["url"])
        ok = "✅" if len(text) > 400 else "⚠️ "
        print(f"   {ok} {c['source']:<18} {len(text):>5} 字符  {p['title'][:36]}")
        pages.append({
            "url": p["url"],
            "source": c["source"],
            "text": text,
            "fallback": (c.get("summary") or "")[:1200],
        })

    grounded = sum(1 for p in pages if len(p["text"]) > 400)
    print(f"\n🤖 第三遍：基于 {grounded}/{len(pages)} 条真实原文重写…")
    urls = {p["url"] for p in pages}
    d = call_with_repair(
        write_messages(pages, len(pages)), cfg,
        lambda x: validate(x, len(pages), urls), "写作")

    d["date"] = args.date
    d.setdefault("sources_note", "来源：官方博客、Hacker News、GitHub 日榜、HuggingFace 论文、科技媒体。")
    d["grounded"] = not args.no_ground
    out_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ 已生成 {out_path.relative_to(ROOT)}（{len(d['items'])} 条）")
    for i, it in enumerate(d["items"], 1):
        print(f"   {i}. {it['title'][:52]}")


if __name__ == "__main__":
    main()
