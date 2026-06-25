"""焊缝坡口矢量图绘制。

基于 GrooveDesign 参数（坡口形式/角度/钝边/根部间隙）用 matplotlib
按真实几何比例绘制坡口剖面图，支持 V/U/X/I 四种典型坡口。

输出 PNG（嵌入文档）和 SVG（矢量），均无 GUI 依赖（Agg 后端）。
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 无显示器后端，必须在使用 pyplot 前设置
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle

from ..domain.joint import GrooveDesign

_FONT_CONFIGURED = False


def _configure_font() -> None:
    """配置 matplotlib 中文字体（优先内嵌，回退系统）。"""
    global _FONT_CONFIGURED
    if _FONT_CONFIGURED:
        return
    from .font_provider import get_font_name
    name = get_font_name()
    plt.rcParams["font.sans-serif"] = [name]
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_CONFIGURED = True


def render_groove(
    groove: GrooveDesign,
    thickness: float,
    output_path: str | Path,
    fmt: str = "png",
    width_mm: float = 80,
    height_mm: float = 60,
    dpi: int = 150,
) -> Path:
    """绘制坡口剖面图并保存。

    参数：
      groove:    坡口设计（type/angle/root_face/root_gap/has_backing）
      thickness: 母材厚度 mm（决定图的纵向尺度）
      output_path: 输出文件路径
      fmt:       png 或 svg
      width_mm:  图宽 mm
      height_mm: 图高 mm

    坐标系约定（mm）：以焊缝中心线根部为原点，x=水平(间隙方向)，y=厚度方向。
    母材绘制为两侧矩形，坡口按参数切削。
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _configure_font()

    # 参数取值与容错
    t = max(thickness, 2.0)
    angle = groove.angle if groove.angle and groove.angle > 0 else 60.0  # 默认60°
    root_face = groove.root_face if groove.root_face and groove.root_face >= 0 else 2.0
    root_gap = groove.root_gap if groove.root_gap and groove.root_gap >= 0 else 2.0
    gtype = (groove.type or "V").upper().strip()

    fig, ax = plt.subplots(figsize=(width_mm / 25.4, height_mm / 25.4), dpi=dpi)
    ax.set_aspect("equal")
    ax.axis("off")

    # 母材宽度（单侧），确保坡口斜边有空间
    plate_half_w = max(t * 1.5, 15.0)
    half_gap = root_gap / 2

    # 绘制母材与坡口
    if gtype == "I":
        _draw_i(ax, t, plate_half_w, half_gap, root_face)
        title = f"I形坡口 间隙{root_gap:g}mm"
    elif gtype == "V":
        _draw_v(ax, t, plate_half_w, half_gap, angle, root_face)
        title = f"V形坡口 {angle:g}° 钝边{root_face:g} 间隙{root_gap:g}mm"
    elif gtype == "X":
        _draw_x(ax, t, plate_half_w, half_gap, angle, root_face)
        title = f"X形(双V)坡口 {angle:g}° 钝边{root_face:g} 间隙{root_gap:g}mm"
    elif gtype == "U":
        _draw_u(ax, t, plate_half_w, half_gap, angle, root_face)
        title = f"U形坡口 R半圆 钝边{root_face:g} 间隙{root_gap:g}mm"
    else:
        # 未知类型回退 V 形
        _draw_v(ax, t, plate_half_w, half_gap, angle, root_face)
        title = f"{gtype}形坡口(近似V) {angle:g}°"

    # 带衬垫：在根部下方绘制衬垫
    if groove.has_backing:
        backing_w = root_gap + 8
        backing = Rectangle(
            (-backing_w / 2, -3), backing_w, 2.5,
            facecolor="#888", edgecolor="k", linewidth=0.8, hatch="//",
        )
        ax.add_patch(backing)
        ax.text(0, -4.5, "衬垫", ha="center", fontsize=7)

    ax.set_title(title, fontsize=8)

    # 坐标范围
    margin = 4
    ax.set_xlim(-plate_half_w - margin, plate_half_w + margin)
    ylim_lo = -6 if groove.has_backing else -2
    ax.set_ylim(ylim_lo, t + 2)

    fig.savefig(out, format=fmt, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# 各坡口形式绘制（坐标单位 mm，以根部中心为原点）
# ---------------------------------------------------------------------------

def _draw_v(ax, t, half_w, half_gap, angle, root_face):
    """V形坡口：单侧斜边，从钝边顶部向外张开。

    斜边水平偏移 = (t - root_face) * tan(angle/2)
    """
    slope_offset = (t - root_face) * math.tan(math.radians(angle / 2))
    # 左母材多边形：外缘→顶部斜边→钝边→根部
    left = Polygon([
        (-half_w, 0), (-half_w, t),
        (-half_gap - slope_offset, t),       # 顶部斜边外端
        (-half_gap, root_face),               # 钝边顶
        (-half_gap, 0),                        # 根部
    ], closed=True, facecolor="#d0d0d0", edgecolor="k", linewidth=1.0)
    ax.add_patch(left)
    # 右母材（镜像）
    right = Polygon([
        (half_w, 0), (half_w, t),
        (half_gap + slope_offset, t),
        (half_gap, root_face),
        (half_gap, 0),
    ], closed=True, facecolor="#d0d0d0", edgecolor="k", linewidth=1.0)
    ax.add_patch(right)


def _draw_x(ax, t, half_w, half_gap, angle, root_face):
    """X形(双V)坡口：上下对称斜边，中间钝边。"""
    half_t = t / 2
    slope_offset = (half_t - root_face / 2) * math.tan(math.radians(angle / 2))
    # 左母材：外缘→上斜边→上钝边→下钝边→下斜边→根部
    left = Polygon([
        (-half_w, 0),
        (-half_w, t),
        (-half_gap - slope_offset, t),
        (-half_gap, half_t + root_face / 2),
        (-half_gap, half_t - root_face / 2),
        (-half_gap - slope_offset, 0),
    ], closed=True, facecolor="#d0d0d0", edgecolor="k", linewidth=1.0)
    ax.add_patch(left)
    right = Polygon([
        (half_w, 0),
        (half_w, t),
        (half_gap + slope_offset, t),
        (half_gap, half_t + root_face / 2),
        (half_gap, half_t - root_face / 2),
        (half_gap + slope_offset, 0),
    ], closed=True, facecolor="#d0d0d0", edgecolor="k", linewidth=1.0)
    ax.add_patch(right)
    # 对称轴
    ax.axhline(half_t, color="#aaa", linestyle=":", linewidth=0.5)


def _draw_u(ax, t, half_w, half_gap, angle, root_face):
    """U形坡口：底部半圆圆弧过渡，上部直边。

    简化为：钝边以上用半圆(R)过渡到一定高度，再直边到顶。
    """
    radius = max((t - root_face) * 0.3, 3.0)
    straight_h = t - root_face - radius
    # 用多段折线近似圆弧
    import numpy as np
    arc_pts_left = []
    cx = -(half_gap + radius)
    cy = root_face + radius
    n = 12
    for i in range(n + 1):
        theta = math.pi / 2 - (math.pi / 2) * (i / n)  # 90°→0°
        arc_pts_left.append((cx + radius * math.cos(theta), cy + radius * math.sin(theta)))
    # 左母材：根部→钝边→圆弧→直边→顶部→外缘→底部
    left_pts = [(-half_gap, 0), (-half_gap, root_face)] + arc_pts_left
    left_pts += [(-half_gap - radius, root_face + radius + straight_h),
                 (-half_w, t), (-half_w, 0)]
    left = Polygon(left_pts, closed=True, facecolor="#d0d0d0",
                   edgecolor="k", linewidth=1.0)
    ax.add_patch(left)
    # 右镜像
    arc_pts_right = [(x + 2 * (half_gap + radius), y) for (x, y) in arc_pts_left]
    right_pts = [(half_gap, 0), (half_gap, root_face)] + list(reversed(arc_pts_right))
    right_pts += [(half_gap + radius, root_face + radius + straight_h),
                  (half_w, t), (half_w, 0)]
    right = Polygon(right_pts, closed=True, facecolor="#d0d0d0",
                    edgecolor="k", linewidth=1.0)
    ax.add_patch(right)


def _draw_i(ax, t, half_w, half_gap, root_face):
    """I形坡口（直边）：两母材平行，仅根部间隙。"""
    left = Rectangle((-half_w - half_gap, 0), half_w, t,
                     facecolor="#d0d0d0", edgecolor="k", linewidth=1.0)
    ax.add_patch(left)
    right = Rectangle((half_gap, 0), half_w, t,
                      facecolor="#d0d0d0", edgecolor="k", linewidth=1.0)
    ax.add_patch(right)
