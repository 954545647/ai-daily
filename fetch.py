#!/usr/bin/env python3
"""AI 日报 · 抓取端

职责：从多个免费公开源抓最近 36 小时的 AI 内容，去重、打分、排序，
      输出候选池 JSON。不含任何 AI 判断，纯确定性逻辑，方便每天对比调试。

用法：
    python3 fetch.py                 # 抓今天的
    python3 fetch.py --hours 48      # 改时间窗口
    python3 fetch.py --verbose       # 打印每个源的状态和结果
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------- HTTP

def http_get(url: str, timeout: int = 15, retries: int = 2) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "close",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                if not raw.strip():
                    raise ValueError("empty response")
                return raw
        except Exception as e:  # 网络抖动/SSL 截断，重试一次通常就好
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def clean_text(s: str | None, limit: int = 600) -> str:
    """去 HTML 标签、反转义、压空白。"""
    if not s:
        return ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


# ---------------------------------------------------------------- RSS / Atom

def parse_feed(raw: bytes) -> list[dict]:
    """兼容 RSS2.0 / Atom / RDF。返回 [{title, link, summary, published_ts}]"""
    out: list[dict] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out

    def tag(el) -> str:
        return el.tag.split("}")[-1].lower() if isinstance(el.tag, str) else ""

    # RSS: rss/channel/item ；Atom: feed/entry ；RDF: rdf/item
    nodes = [e for e in root.iter() if tag(e) in ("item", "entry")]
    for n in nodes:
        title = link = summary = published = ""
        for c in n:
            t = tag(c)
            if t == "title":
                title = clean_text(c.text, 300)
            elif t == "link":
                href = c.get("href")
                if href:
                    if not link or c.get("rel") in (None, "alternate"):
                        link = href
                elif c.text:
                    link = c.text.strip()
            elif t in ("description", "summary", "content", "encoded"):
                if not summary:
                    summary = clean_text(c.text, 900)
            elif t in ("pubdate", "published", "updated", "date"):
                if not published:
                    published = (c.text or "").strip()
        out.append({
            "title": title,
            "link": link,
            "summary": summary,
            "published_ts": parse_ts(published),
        })
    return out


def parse_ts(s: str) -> float:
    if not s:
        return 0.0
    s = s.strip()
    try:  # ISO 8601
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            continue
    return 0.0


# ---------------------------------------------------------------- 各数据源

def fetch_rss(spec: dict) -> list[dict]:
    items = parse_feed(http_get(spec["url"]))
    return [{
        "source": spec["name"],
        "title": it["title"],
        "url": it["link"],
        "summary": it["summary"],
        "ts": it["published_ts"] or time.time(),
    } for it in items if it["title"] and it["link"]]


def fetch_hn(spec: dict) -> list[dict]:
    """Hacker News（Algolia API）：按关键词多路合并。"""
    cutoff = int(NOW.timestamp() - config.LOOKBACK_HOURS * 3600)
    seen, items = set(), []
    for q in spec.get("queries", ["AI"]):
        url = ("https://hn.algolia.com/api/v1/search?"
               + urllib.parse.urlencode({
                   "query": q, "tags": "story", "hitsPerPage": 40,
                   "numericFilters": f"created_at_i>{cutoff},points>25",
               }))
        try:
            data = json.loads(http_get(url))
        except Exception:
            continue
        for h in data.get("hits", []):
            oid = h.get("objectID")
            if oid in seen:
                continue
            seen.add(oid)
            items.append({
                "source": spec["name"],
                "title": clean_text(h.get("title"), 300),
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                "summary": clean_text(h.get("story_text") or "", 500),
                "ts": h.get("created_at_i", 0),
                "engagement": {"points": h.get("points", 0),
                               "comments": h.get("num_comments", 0)},
                "discuss": f"https://news.ycombinator.com/item?id={oid}",
            })
    return items


def fetch_hf_papers(spec: dict) -> list[dict]:
    """HuggingFace 每日论文（社区点赞版，相当于arxiv的精选）。"""
    data = json.loads(http_get("https://huggingface.co/api/daily_papers?limit=50"))
    items = []
    for d in data:
        p = d.get("paper") or {}
        pid = p.get("id")
        if not pid:
            continue
        ts = parse_ts(p.get("submittedOnDailyAt") or p.get("publishedAt") or "")
        items.append({
            "source": spec["name"],
            "title": clean_text(p.get("title"), 300),
            "url": f"https://huggingface.co/papers/{pid}",
            "summary": clean_text(p.get("summary"), 700),
            "ts": ts or time.time(),
            "engagement": {"upvotes": p.get("upvotes", 0)},
        })
    return items


def fetch_gh_trending(spec: dict) -> list[dict]:
    """GitHub 日榜里跟 AI 相关的仓库。"""
    raw = http_get("https://github.com/trending?since=daily").decode("utf-8", "ignore")
    items = []
    for b in re.split(r"<article\b", raw)[1:]:
        m = re.search(r'href="/([^"/]+/[^"/]+)/stargazers"', b)
        if not m:
            continue
        repo = m.group(1)
        desc = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', b, re.S)
        stars = re.search(r'([\d,]+)\s*stars today', b)
        items.append({
            "source": spec["name"],
            "title": repo,
            "url": f"https://github.com/{repo}",
            "summary": clean_text(desc.group(1) if desc else "", 400),
            "ts": time.time(),
            "engagement": {"stars_today": int(stars.group(1).replace(",", "")) if stars else 0},
        })
    return items


def fetch_anthropic(spec: dict) -> list[dict]:
    """Anthropic 没有 RSS，直接解析官网新闻页。"""
    raw = http_get("https://www.anthropic.com/news").decode("utf-8", "ignore")
    items, seen = [], set()
    for m in re.finditer(r'href="(/news/[a-z0-9\-]+)"', raw):
        path = m.group(1)
        if path in seen or path == "/news":
            continue
        seen.add(path)
        slug = path.rsplit("/", 1)[-1]
        title = re.sub(r"-+", " ", slug).strip().title()
        items.append({
            "source": spec["name"],
            "title": title,
            "url": f"https://www.anthropic.com{path}",
            "summary": "",
            "ts": time.time(),
        })
    return items


FETCHERS = {
    "rss": fetch_rss,
    "hn": fetch_hn,
    "hf_papers": fetch_hf_papers,
    "gh_trending": fetch_gh_trending,
    "anthropic": fetch_anthropic,
}

SOURCES = [
    # ---- 官方发布（你关心的「模型/产品发布」主力）
    {"name": "OpenAI", "kind": "rss", "url": "https://openai.com/news/rss.xml"},
    {"name": "Anthropic", "kind": "anthropic"},
    {"name": "Google AI", "kind": "rss", "url": "https://blog.google/technology/ai/rss/"},
    {"name": "DeepMind", "kind": "rss", "url": "https://deepmind.google/blog/rss.xml"},
    # ---- 实战 / 解读（你关心的「工具实战」主力）
    {"name": "Simon Willison", "kind": "rss", "url": "https://simonwillison.net/atom/everything/"},
    {"name": "The Decoder", "kind": "rss", "url": "https://the-decoder.com/feed/"},
    {"name": "TechCrunch AI", "kind": "rss", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    # ---- 社区热度（发现漏网之鱼）
    {"name": "Hacker News", "kind": "hn",
     "queries": ["AI", "LLM", "agent", "OpenAI", "Claude"]},
    {"name": "GitHub Trending", "kind": "gh_trending"},
    # ---- 论文精选
    {"name": "HuggingFace Papers", "kind": "hf_papers"},
]

# GitHub 刷屏的仓库太多，只留真跟 AI 沾边的
GH_AI_HINTS = [
    "llm", "ai", "agent", "gpt", "claude", "model", "rag", "prompt", "ml",
    "deep", "neural", "transformer", "diffusion", "voice", "vision", "ocr",
    "embedding", "vector", "mcp", "inference", "openai", "langchain", "llama",
]


# ---------------------------------------------------------------- 打分

_KW_CACHE: dict[str, re.Pattern] = {}


def _kw_hits(text: str, kw: str) -> int:
    """整词匹配，避免 'ai' 命中 'said'、'ga' 命中 'garage' 这类误伤。"""
    pat = _KW_CACHE.get(kw)
    if pat is None:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])")
        _KW_CACHE[kw] = pat
    return len(pat.findall(text))


def interest_score(title: str, summary: str) -> tuple[float, list[str]]:
    """按兴趣组命中情况打分，标题的命中权重是正文的 2.5 倍。"""
    t_low, s_low = title.lower(), summary.lower()
    total, tags = 0.0, []
    for gname, g in config.INTERESTS.items():
        hits = 0.0
        for kw in g["keywords"]:
            if kw.lower() in t_low or kw.lower() in s_low:      # 廉价预筛
                hits += _kw_hits(t_low, kw) * 2.5 + _kw_hits(s_low, kw)
        if hits:
            total += g["weight"] * min(hits, 8) / 8.0
            tags.append(gname)
    penalty = sum(1 for kw in config.NEGATIVE_KEYWORDS
                  if kw.lower() in t_low or kw.lower() in s_low)
    return total - penalty * 1.5, tags


def engagement_bonus(it: dict) -> float:
    e = it.get("engagement") or {}
    b = 0.0
    if e.get("points"):
        b += min(math.log10(max(e["points"], 1)) / 3.0, 1.2) * 1.6
    if e.get("upvotes"):
        b += min(e["upvotes"] / 60.0, 0.8)
    if e.get("stars_today"):
        b += min(e["stars_today"] / 400.0, 0.8)
    return b


def recency_factor(ts: float) -> float:
    hours = max((NOW.timestamp() - ts) / 3600.0, 0)
    if hours <= 6:
        return 1.15
    if hours <= 18:
        return 1.0
    if hours <= 30:
        return 0.88
    return 0.72


def score_item(it: dict) -> tuple[float, list[str]]:
    ist, tags = interest_score(it["title"], it.get("summary", ""))
    base = config.SOURCE_WEIGHT.get(it["source"], 1.0)
    total = base * (1.0 + ist) * recency_factor(it["ts"]) + engagement_bonus(it)
    return round(total, 3), tags


def apply_caps(items: list[dict]) -> list[dict]:
    """按源配额截断，保证候选池的多样性。"""
    counts: dict[str, int] = {}
    kept = []
    for it in items:
        src = it["source"]
        cap = config.SOURCE_CAP.get(src, 99)
        if counts.get(src, 0) >= cap:
            continue
        counts[src] = counts.get(src, 0) + 1
        kept.append(it)
    return kept


# ---------------------------------------------------------------- 去重

def norm_url(u: str) -> str:
    p = urllib.parse.urlparse(u)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
         if not k.startswith("utm_") and k not in ("ref", "source")]
    return urllib.parse.urlunparse(
        (p.scheme, p.netloc.replace("www.", ""), p.path.rstrip("/"),
         "", urllib.parse.urlencode(q), ""))


def title_key(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", t.lower())[:90]


def dedupe(items: list[dict]) -> list[dict]:
    kept, seen_urls, seen_title = [], set(), {}
    for it in sorted(items, key=lambda x: -x["score"]):
        u = norm_url(it["url"])
        if u in seen_urls:
            continue
        tk = title_key(it["title"])
        dup = False
        for prev_tk in seen_title:
            if not tk or not prev_tk:
                continue
            if tk == prev_tk or SequenceMatcher(None, tk, prev_tk).ratio() > 0.86:
                dup = True
                break
        if dup:
            continue
        seen_urls.add(u)
        seen_title[tk] = it["url"]
        kept.append(it)
    return kept


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=config.LOOKBACK_HOURS)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    config.LOOKBACK_HOURS = args.hours
    cutoff = NOW.timestamp() - args.hours * 3600
    all_items, status = [], {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(FETCHERS[s["kind"]], s): s for s in SOURCES}
        for f in as_completed(futs):
            s = futs[f]
            try:
                got = f.result()
                fresh = [i for i in got if i["ts"] >= cutoff]
                if s["name"] == "GitHub Trending":
                    fresh = [i for i in fresh
                             if any(h in (i["title"] + i["summary"]).lower()
                                    for h in GH_AI_HINTS)]
                all_items.extend(fresh)
                status[s["name"]] = f"ok {len(fresh)}"
            except Exception as e:
                status[s["name"]] = f"FAIL {type(e).__name__}: {str(e)[:70]}"

    if args.verbose:
        print("── 源状态 ──")
        for k, v in sorted(status.items()):
            print(f"  {k:<22} {v}")

    # 打分
    for it in all_items:
        it["score"], it["tags"] = score_item(it)
        it["id"] = f"{title_key(it['title'])[:16] or 'x'}-{abs(hash(it['url'])) % 10**6:06d}"

    ranked = apply_caps(dedupe(all_items))[: config.MAX_CANDIDATES]

    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "lookback_hours": args.hours,
        "source_status": status,
        "total_scraped": len(all_items),
        "candidates": ranked,
    }
    path = Path(args.out) if args.out else DATA / f"candidates-{time.strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n✅ 抓到 {len(all_items)} 条，去重打分后留 {len(ranked)} 条候选")
    print(f"📄 {path}\n")
    print(f"{'分':>5}  {'源':<18} {'标题':<62} {'标签'}")
    print("─" * 118)
    for it in ranked[:25]:
        t = it["title"][:60]
        print(f"{it['score']:>5.1f}  {it['source'][:17]:<18} {t:<62} {','.join(it['tags'])[:28]}")


if __name__ == "__main__":
    main()
