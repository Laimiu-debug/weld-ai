"""资源路径解析：兼容开发模式与打包模式（PyInstaller）。

打包后 exe 解压到临时目录(sys._MEIPASS)，__file__ 路径会变。
本模块统一处理：开发时定位到 src/weldai 下，打包后定位到 _MEIPASS。
"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境。"""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    """打包资源的根目录。

    - 打包模式：sys._MEIPASS（exe 解压的临时目录）
    - 开发模式：src/weldai 包目录
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # 开发模式：本文件在 src/weldai/utils/paths.py，包根在上级
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """获取打包资源的绝对路径。

    用法：resource_path("standards", "data", "nbt47014_2023", "base_metals.yaml")
    开发模式定位到 src/weldai/standards/data/...
    打包模式定位到 _MEIPASS/standards/data/...
    """
    return bundle_root().joinpath(*parts)
