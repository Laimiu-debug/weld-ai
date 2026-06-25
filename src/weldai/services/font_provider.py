"""统一中文字体提供者。

双策略：优先内嵌开源字体，回退系统字体(SimSun/SimHei/微软雅黑)，
确保任何 Windows 机器 PDF/坡口图中文都能正常显示。

内嵌字体放在 assets/fonts/，随 exe 打包。
"""
from __future__ import annotations

from pathlib import Path

from ..utils.paths import resource_path

# 内嵌字体候选（assets/fonts/ 下，随包发布）
_EMBEDDED_FONT_NAMES = [
    "NotoSansSC-Regular.otf",
    "SourceHanSansSC-Regular.otf",
    "NotoSansSC-Regular.ttf",
]

# 系统字体候选（Windows 常见中文字体）
_SYSTEM_FONT_PATHS = [
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyhbd.ttc",
]

_cached_font: Path | None = None
_cached_checked = False


def get_font_path() -> Path | None:
    """获取可用的中文字体路径。

    优先级：内嵌字体 > 系统字体 > None（调用方回退默认字体）。
    结果缓存，避免重复磁盘检测。
    """
    global _cached_font, _cached_checked
    if _cached_checked:
        return _cached_font
    _cached_checked = True

    # 1. 内嵌字体
    for name in _EMBEDDED_FONT_NAMES:
        p = resource_path("assets", "fonts", name)
        if p.exists():
            _cached_font = p
            return p

    # 2. 系统字体
    for p in _SYSTEM_FONT_PATHS:
        if Path(p).exists():
            _cached_font = Path(p)
            return Path(p)

    # 3. 无可用字体（调用方应回退默认，中文可能乱码但不崩溃）
    _cached_font = None
    return None


def get_font_name() -> str:
    """获取字体显示名（用于 matplotlib 设置）。

    若无中文字体，返回 matplotlib 默认字体名。
    """
    import matplotlib
    fp = get_font_path()
    if fp is None:
        return "DejaVu Sans"
    try:
        matplotlib.font_manager.fontManager.addfont(str(fp))
        return matplotlib.font_manager.FontProperties(fname=str(fp)).get_name()
    except Exception:
        return "DejaVu Sans"


def reset_cache() -> None:
    """重置字体缓存（测试/开发用）。"""
    global _cached_font, _cached_checked
    _cached_font = None
    _cached_checked = False
