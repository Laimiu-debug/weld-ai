"""坡口矢量图绘制单测。"""
from __future__ import annotations

import pytest

from weldai.domain.joint import GrooveDesign
from weldai.services.groove_renderer import render_groove


@pytest.mark.parametrize("gtype", ["V", "Y", "X", "U", "I"])
def test_render_all_groove_types(tmp_path, gtype):
    """五种典型坡口应能生成有效 PNG 文件（含 Y 形）。"""
    groove = GrooveDesign(type=gtype, angle=60, root_face=2, root_gap=2)
    out = render_groove(groove, thickness=16, output_path=tmp_path / f"test_{gtype}.png")
    assert out.exists()
    assert out.stat().st_size > 500  # 非空图片


def test_render_svg_format(tmp_path):
    """应支持 SVG 矢量格式输出。"""
    groove = GrooveDesign(type="V", angle=60, root_face=2, root_gap=3)
    out = render_groove(groove, 16, tmp_path / "test.svg", fmt="svg")
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "<svg" in content or "<?xml" in content


def test_backing_marked(tmp_path):
    """带衬垫时应正确绘制（不报错，文件有效）。"""
    groove = GrooveDesign(type="V", angle=60, root_face=2, root_gap=2, has_backing=True)
    out = render_groove(groove, 16, tmp_path / "backing.png")
    assert out.exists()


def test_unknown_type_fallback(tmp_path):
    """未知坡口类型应回退为 V 形（不崩溃）。"""
    groove = GrooveDesign(type="CUSTOM", angle=45, root_face=1, root_gap=2)
    out = render_groove(groove, 12, tmp_path / "fallback.png")
    assert out.exists()


def test_thin_plate_no_crash(tmp_path):
    """薄板(2mm)应能正常绘制。"""
    groove = GrooveDesign(type="I", root_gap=1)
    out = render_groove(groove, 2, tmp_path / "thin.png")
    assert out.exists()


def test_custom_dimensions(tmp_path):
    """自定义图幅尺寸应生效。"""
    groove = GrooveDesign(type="V", angle=60, root_face=2, root_gap=2)
    out = render_groove(groove, 20, tmp_path / "custom.png",
                        width_mm=120, height_mm=90, dpi=200)
    assert out.exists()
    assert out.stat().st_size > 1000


# ---------------------------------------------------------------------------
# 坡口截面积计算（供成本计算）
# ---------------------------------------------------------------------------

from weldai.services.groove_renderer import groove_cross_area


def test_cross_area_positive_all_types():
    """各坡口形式截面积应为正数。"""
    for gtype in ["V", "Y", "X", "U", "I"]:
        g = GrooveDesign(type=gtype, angle=60, root_face=2, root_gap=2)
        area = groove_cross_area(g, 16)
        assert area > 0, f"{gtype}形截面积应>0，实际{area}"


def test_cross_area_x_smaller_than_v():
    """X形（双面）坡口面积应小于同参数V形（单面）——省材。"""
    v = GrooveDesign(type="V", angle=60, root_face=2, root_gap=2)
    x = GrooveDesign(type="X", angle=60, root_face=2, root_gap=2)
    assert groove_cross_area(x, 16) < groove_cross_area(v, 16)


def test_cross_area_u_smaller_than_v():
    """U形坡口面积应小于V形（圆弧比直边省材）。"""
    v = GrooveDesign(type="V", angle=60, root_face=2, root_gap=2)
    u = GrooveDesign(type="U", angle=60, root_face=2, root_gap=2)
    assert groove_cross_area(u, 16) < groove_cross_area(v, 16)


def test_cross_area_i_is_gap_times_thickness():
    """I形坡口面积 = 间隙 × 板厚。"""
    g = GrooveDesign(type="I", root_gap=3)
    assert groove_cross_area(g, 16) == pytest.approx(3 * 16)


def test_cross_area_scales_with_thickness():
    """V形截面积应随板厚增大（斜边区域正比厚度平方）。"""
    g = GrooveDesign(type="V", angle=60, root_face=2, root_gap=2)
    a8 = groove_cross_area(g, 8)
    a16 = groove_cross_area(g, 16)
    assert a16 > a8
