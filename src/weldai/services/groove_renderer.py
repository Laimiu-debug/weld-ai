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
    elif gtype == "Y":
        _draw_y(ax, t, plate_half_w, half_gap, angle, root_face)
        title = f"Y形坡口 {angle:g}° 钝边{root_face:g} 间隙{root_gap:g}mm"
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
# 坡口截面积（供成本计算，与上述绘图几何保持一致）
# ---------------------------------------------------------------------------

def groove_cross_area(groove: GrooveDesign, thickness: float) -> float:
    """计算焊缝坡口截面积（mm²），用于焊材消耗量估算。

    截面积 = 坡口填充金属的横截面积。各坡口形式解析公式：

    - I形：间隙 × 板厚 + 余高（顶部凸起，按经验 t*2 估）
    - V/Y形：根部间隙矩形 + 两三角斜边区域
            ≈ gap*t + (t-root_face)² * tan(angle/2)
    - X形：上下对称两个 V：≈ gap*t + 2*((t/2-root_face/2)² * tan(angle/2))
    - U形：用近似（半圆 + 直边）：≈ gap*t + (t-root_face)² * tan(angle/2) * 0.7

    返回值含一定余量（与成本计算的 1.1 余高系数配合）。
    """
    t = max(thickness, 2.0)
    angle = groove.angle if groove.angle and groove.angle > 0 else 60.0
    root_face = groove.root_face if groove.root_face and groove.root_face >= 0 else 2.0
    root_gap = groove.root_gap if groove.root_gap and groove.root_gap >= 0 else 2.0
    gtype = (groove.type or "V").upper().strip()

    half_angle = math.radians(angle / 2)

    if gtype == "I":
        # I形：间隙×板厚
        return root_gap * t
    if gtype in ("V", "Y"):
        # V/Y形：间隙矩形 + 两三角（单侧 (t-p)²*tan(a/2)，两侧 ×2）
        bevel = max(t - root_face, 0)
        return root_gap * t + bevel * bevel * math.tan(half_angle)
    if gtype == "X":
        # X形：间隙矩形 + 上下各两三角（共4个，单侧高度 (t/2 - p/2)）
        half_bevel = max(t / 2 - root_face / 2, 0)
        return root_gap * t + 2 * (half_bevel * half_bevel * math.tan(half_angle))
    if gtype == "U":
        # U形：近似为 V 的 0.7 倍（圆弧比直边省材）
        bevel = max(t - root_face, 0)
        return root_gap * t + 0.7 * bevel * bevel * math.tan(half_angle)
    # 回退 V 形
    bevel = max(t - root_face, 0)
    return root_gap * t + bevel * bevel * math.tan(half_angle)


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


def _draw_y(ax, t, half_w, half_gap, angle, root_face):
    """Y形坡口：上部斜边坡口 + 较高直边钝边（斜边从板厚中部开始）。

    与 V 形区别：斜边只占上部约一半板厚，下半为垂直直边钝边，
    适用于较厚板（减少填充金属量）。斜边段高度 = (t - root_face)。
    """
    # 斜边坡口段高度（占钝边以上的部分）
    bevel_h = t - root_face
    slope_offset = bevel_h * math.tan(math.radians(angle / 2))
    # 左母材：外缘→顶部斜边→斜边底(转折点)→直边钝边→根部
    left = Polygon([
        (-half_w, 0), (-half_w, t),
        (-half_gap - slope_offset, t),       # 顶部斜边外端
        (-half_gap, root_face),               # 斜边转折到直边(钝边顶)
        (-half_gap, 0),                        # 垂直钝边到根部
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
    # 标注钝边位置
    ax.plot([-half_gap - slope_offset, half_gap + slope_offset],
            [root_face, root_face], color="#aaa", linestyle=":", linewidth=0.5)


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
