"""小屏幕适配辅助。

QDialog / QMainWindow 的内容若超出屏幕高度（典型 1366×768 笔记本，
去掉任务栏可用约 728px），底部按钮会被遮挡。本模块提供两个工具：

- ``fit_to_screen(widget)``：把窗口尺寸限制在可用屏幕区内。
- ``make_scroll_content(widget)``：把内容组件包进 QScrollArea，返回可加入
  外层布局的滚动容器（按钮栏保持在外层，始终可见）。
"""
from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QWidget


def fit_to_screen(widget: QWidget, margin: int = 40) -> None:
    """把窗口尺寸限制在可用屏幕区内（留 margin 像素，避免被任务栏遮挡）。

    仅在窗口超出可用区时缩小；不放大。必须在窗口已 show 或有 screen 关联后调用。
    """
    screen = widget.screen() if hasattr(widget, "screen") else None
    avail = screen.availableGeometry() if screen is not None else None
    if avail is None:
        return
    w, h = widget.width(), widget.height()
    max_h = avail.height() - margin
    max_w = avail.width() - margin
    new_w = min(w, max_w)
    new_h = min(h, max_h)
    if (new_w, new_h) != (w, h):
        widget.resize(new_w, new_h)


def make_scroll_content(content: QWidget) -> QScrollArea:
    """把内容组件包进无边框、自适应的 QScrollArea，返回滚动容器。

    用法：把返回值 addWidget 到外层布局，按钮栏单独 addWidget 留在外层，
    这样小屏幕上内容可滚动、按钮始终可见。
    """
    scroll = QScrollArea()
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    return scroll
