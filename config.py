"""AI 日报 - 配置。想调口味改这里就行，不用动代码。"""

# ---------- 你关心什么 ----------
# 兴趣分组：每条内容会按命中关键词打分，命中越多分越高
INTERESTS = {
    "模型发布": {
        "weight": 3.0,
        "keywords": [
            "release", "released", "launch", "launched", "announces", "announced",
            "announcing", "introducing", "now available", "rollout", "rolls out",
            "preview", "open source", "open-source", "open weights", "open-weight",
            "benchmark", "SOTA", "state of the art", "generally available",
            "gpt", "claude", "gemini", "llama", "qwen", "deepseek", "mistral",
            "grok", "sonnet", "opus", "haiku", "kimi", "glm", "nova", "phi",
        ],
    },
    "工具实战": {
        "weight": 3.0,
        "keywords": [
            "how to", "tutorial", "guide", "workflow", "prompt", "prompting",
            "agent", "agents", "agentic", "rag", "mcp", "tool use", "tool calling",
            "context engineering", "fine-tun", "fine tun", "lora", "eval",
            "practical", "hands-on", "recipe", "pattern", "best practice",
            "vs code", "cursor", "copilot", "claude code", "ide", "cli",
        ],
    },
    "论文研究": {
        "weight": 0.7,
        "keywords": [
            "paper", "arxiv", "we propose", "we present",
            "novel", "scaling law",
        ],
    },
    "行业动态": {
        "weight": 1.0,
        "keywords": [
            "funding", "raises", "valuation", "acquire", "acquisition",
            "partnership", "regulation", "lawsuit", "policy", "ipo", "hiring",
        ],
    },
}

# 命中这些词直接减分（你不关心的噪音）
NEGATIVE_KEYWORDS = [
    "giveaway", "sponsored", "webinar", "coupon", "crypto token",
    "stock price", "earnings call", "celebrity",
]

# ---------- 源的可信度权重 ----------
SOURCE_WEIGHT = {
    "OpenAI": 1.45,
    "Anthropic": 1.45,
    "Google AI": 1.40,
    "DeepMind": 1.40,
    "Simon Willison": 1.30,
    "HuggingFace Blog": 1.20,
    "HuggingFace Papers": 0.85,
    "The Decoder": 1.05,
    "TechCrunch AI": 0.95,
    "Hacker News": 1.10,
    "GitHub Trending": 1.15,
}

# 每个源最多进候选池多少条（防止某一家刷屏）
SOURCE_CAP = {
    "HuggingFace Papers": 8,
    "GitHub Trending": 5,
    "Hacker News": 8,
    "Anthropic": 4,
    "OpenAI": 5,
    "TechCrunch AI": 5,
    "The Decoder": 5,
    "Simon Willison": 5,
}

# ---------- 抓取窗口 ----------
LOOKBACK_HOURS = 36          # 只看最近这么久的内容
MAX_CANDIDATES = 45          # 给 AI 精挑的候选池大小

# ---------- 推送 ----------
FEISHU_BOT_USER_ID = "ou_d6b8462bae67fda3f83c6e175ee6aa9f"
# 「AI 日报」群（机器人自建，已把主人拉进去）。走 lark-cli 时发到这里。
FEISHU_CHAT_ID = "oc_f114254208c778f9199c244b14fe25cc"
DIGEST_TARGET_COUNT = 6      # 每日精选条数（5-8 之间）

# X / 推特：没有官方 API，靠公开渠道 + 联网搜索兜底
X_KOLS = [
    "karpathy", "sama", "AnthropicAI", "OpenAI", "GoogleDeepMind",
    "simonw", "ylecun", "demishassabis", "EMostaque", "DrJimFan",
]
