"""YAML 规则包加载器。

所有标准规则以数据驱动方式存储在 standards/data/<standard>/*.yaml。
本模块负责定位并加载这些文件，使标准升级时"只换数据包不改代码"。
兼容 PyInstaller 打包模式（数据文件随包发布）。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from ..utils.paths import bundle_root


def data_root() -> Path:
    """规则数据根目录。

    开发模式：src/weldai/standards/data
    打包模式：_MEIPASS/standards/data（PyInstaller 将 data 目录打包到 standards 下）
    """
    # 打包模式：PyInstaller 按包结构释放，standards/data 仍在 standards 下
    root = bundle_root() / "standards" / "data"
    if root.exists():
        return root
    # 开发模式回退：本文件在 standards/loader.py，data 在同级
    return Path(__file__).resolve().parent / "data"


def standard_dir(registry_key: str) -> Path:
    """某标准的数据目录，如 .../data/nbt47014_2023/。"""
    return data_root() / registry_key


@lru_cache(maxsize=None)
def load_yaml(path: Path) -> dict:
    """加载并缓存 YAML 文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_standard_data(registry_key: str, filename: str) -> dict:
    """加载某标准下的某个 yaml 文件。

    registry_key 如 'nbt47014_2023'，filename 如 'base_metals.yaml'。
    """
    path = standard_dir(registry_key) / filename
    if not path.exists():
        raise FileNotFoundError(f"规则数据文件不存在: {path}")
    return load_yaml(path)


def clear_caches() -> None:
    """清除 YAML 加载缓存（开发/测试用）。

    规则数据用 @lru_cache 缓存，编辑 YAML 后需调用此方法使改动生效。
    生产环境标准数据不变，无需调用。
    """
    load_yaml.cache_clear()


def clear_standard_profile_cache() -> None:
    """清除 StandardProfile 实例缓存（开发/测试用）。

    使下次 get_standard() 重新加载数据。
    """
    from .registry import _INSTANCES
    _INSTANCES.clear()
    clear_caches()
