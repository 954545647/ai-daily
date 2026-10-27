"""极简 .env 读取器（不依赖 python-dotenv）。

优先级：真实环境变量 > ai-daily/.env > 默认值
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"

DEFAULTS = {
    "LLM_PROVIDER": "deepseek",
    "LLM_BASE_URL": "https://api.deepseek.com",
    "LLM_MODEL": "deepseek-chat",
    "FEISHU_WEBHOOK": "",
    "FEISHU_WEBHOOK_SECRET": "",
    "READER_URL": "",
    "DIGEST_MODE": "single",
    "DEEPSEEK_API_KEY": "",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
}


def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def load_env() -> dict[str, str]:
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in _parse(ENV_FILE).items() if v})
    for k in list(cfg):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def api_key(cfg: dict[str, str] | None = None) -> str:
    cfg = cfg or load_env()
    provider = cfg.get("LLM_PROVIDER", "deepseek").lower()
    if provider == "anthropic":
        return cfg.get("ANTHROPIC_API_KEY", "")
    if provider == "openai":
        return cfg.get("OPENAI_API_KEY", "")
    return cfg.get("DEEPSEEK_API_KEY", "")


def write_env(**kv: str) -> None:
    """写回 .env（保留已有键，原子替换）。"""
    cur = _parse(ENV_FILE)
    cur.update({k: v for k, v in kv.items() if v})
    body = "\n".join(f"{k}={v}" for k, v in cur.items())
    tmp = ENV_FILE.with_suffix(".tmp")
    tmp.write_text(body + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(ENV_FILE)
