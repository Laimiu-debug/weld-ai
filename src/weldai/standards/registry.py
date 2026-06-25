"""标准注册表。

UI/服务层通过 ``get_standard(key)`` 获取当前选中的 StandardProfile。
切换标准 = 换一个 key，业务代码零改动。
"""
from __future__ import annotations

from .base import StandardProfile
from .nbt47014_2023 import NBT47014_2023Profile

# 注册表：key → Profile 工厂
_REGISTRY: dict[str, type[StandardProfile]] = {
    "NBT47014-2023": NBT47014_2023Profile,
    # "NBT47014-2011": NBT47014_2011Profile,  # 预留：旧版 PQR 迁移
    # "ASME-IX-2023": ASME_IX_2023Profile,    # 预留：二期
}

# 实例缓存（Profile 无状态，单例即可）
_INSTANCES: dict[str, StandardProfile] = {}


def list_standards() -> list[str]:
    """列出所有已注册标准的 key。"""
    return list(_REGISTRY.keys())


def get_standard(key: str) -> StandardProfile:
    """按 key 获取标准 Profile（单例）。"""
    if key not in _REGISTRY:
        raise KeyError(
            f"未注册的标准: {key}。已注册: {list(_REGISTRY.keys())}"
        )
    if key not in _INSTANCES:
        _INSTANCES[key] = _REGISTRY[key]()
    return _INSTANCES[key]


def default_standard_key() -> str:
    """默认标准（国内压力容器首选）。"""
    return "NBT47014-2023"


def get_default_standard() -> StandardProfile:
    return get_standard(default_standard_key())
