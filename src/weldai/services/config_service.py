"""用户配置管理（LLM API key 等）。

配置存储在 ~/.weldai/config.json。API key 做简单混淆存储（base64），
避免明文直接可见（非加密，单机桌面应用场景）。
"""
from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".weldai"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class LLMConfig:
    """LLM 服务商配置。"""

    provider: str = "custom"        # glm / deepseek / kimi / custom
    api_key: str = ""
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4-flash"
    temperature: float = 0.3
    max_tokens: int = 2000


@dataclass
class AppConfig:
    """应用全局配置。"""

    llm: LLMConfig = field(default_factory=LLMConfig)
    db_path: str = ""               # 空则用默认
    last_standard: str = "NBT47014-2023"

    def to_dict(self) -> dict:
        d = asdict(self)
        # api key 混淆
        if d["llm"]["api_key"]:
            d["llm"]["api_key"] = _obfuscate(d["llm"]["api_key"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        llm_d = d.get("llm", {})
        if llm_d.get("api_key"):
            llm_d["api_key"] = _deobfuscate(llm_d["api_key"])
        return cls(
            llm=LLMConfig(**llm_d),
            db_path=d.get("db_path", ""),
            last_standard=d.get("last_standard", "NBT47014-2023"),
        )


def _obfuscate(text: str) -> str:
    """简单 base64 混淆（★非加密，仅避免明文直接可见）。

    安全说明：base64 可被任何有文件系统访问权限的人还原。
    对本地单机桌面应用，这提供"防偷瞄"级别的保护；
    若需更强保护应集成 OS keychain（keyring 包）。
    请勿在共享主机上依赖此机制保护敏感 key。
    """
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _deobfuscate(text: str) -> str:
    try:
        return base64.b64decode(text.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def load_config() -> AppConfig:
    """加载配置，不存在则返回默认。"""
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return AppConfig.from_dict(json.load(f))
    except Exception:
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """保存配置。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)


# 预设服务商选项（供 UI 下拉）
PROVIDER_PRESETS: dict[str, dict] = {
    "glm": {
        "label": "智谱 GLM (https://open.bigmodel.cn)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "deepseek": {
        "label": "DeepSeek (https://platform.deepseek.com)",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "kimi": {
        "label": "Moonshot Kimi (https://platform.moonshot.cn)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "custom": {
        "label": "自定义 OpenAI 兼容端点",
        "base_url": "",
        "model": "",
    },
}
