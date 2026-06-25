"""覆盖范围计算单测（NB/T 47014 表7）。

验证厚度/管径/位置覆盖规则的分段计算正确性。
"""
from __future__ import annotations

import pytest

from weldai.domain.enums import Position
from weldai.engine import CoverageEngine
from weldai.standards import get_default_standard

from .conftest import make_pqr_q345r_smaw, make_wps_from_pqr


@pytest.fixture
def engine() -> CoverageEngine:
    return CoverageEngine(get_default_standard())


# ---------------------------------------------------------------------------
# 厚度覆盖分段（表7）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("coupon_t, expect_min, expect_max", [
    (1.0, 1.0, 2.0),       # t<1.5 → [t, 2t]
    (1.5, 1.5, 3.0),       # 1.5≤t≤10 → [1.5, 2t]
    (10.0, 1.5, 20.0),     # 边界 t=10 → [1.5, 20]
    (20.0, 10.0, 40.0),    # 10<t<30 → [max(5,0.5t)=10, 2t]
    (30.0, 5.0, 60.0),     # t≥30 → [5, min(200,60)]
    (120.0, 5.0, 200.0),   # t≥30 且 2t=240>200 → [5, 200]
])
def test_thickness_coverage(engine, coupon_t, expect_min, expect_max):
    rng = engine.standard.coverage_thickness(coupon_t)
    assert rng.min_t == pytest.approx(expect_min, abs=0.5)
    assert rng.max_t == pytest.approx(expect_max, abs=0.5)


def test_thickness_coupon_20():
    """t=20 时 0.5t=10 > 5，故 min=10。单独验证 max 函数。"""
    rng = get_default_standard().coverage_thickness(20.0)
    assert rng.min_t == pytest.approx(10.0)  # max(5, 0.5*20)=10
    assert rng.max_t == pytest.approx(40.0)  # 2*20


# ---------------------------------------------------------------------------
# 表7 冲击试验约束（阶段2核实）：1.5≤t≤10 且有冲击时上限由2t收紧为t+1.5
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("coupon_t,no_impact_max,impact_max", [
    (6.0, 12.0, 7.5),    # 1.5≤6≤10：无冲击2t=12，有冲击t+1.5=7.5
    (3.0, 6.0, 4.5),     # 1.5≤3≤10：无冲击6，有冲击4.5
    (1.5, 3.0, 3.0),     # 边界t=1.5：无冲击3，有冲击3
])
def test_thickness_impact_constraint(coupon_t, no_impact_max, impact_max):
    std = get_default_standard()
    rng_no = std.coverage_thickness(coupon_t, impact_required=False)
    rng_imp = std.coverage_thickness(coupon_t, impact_required=True)
    assert rng_no.max_t == pytest.approx(no_impact_max)
    assert rng_imp.max_t == pytest.approx(impact_max)
    # 有冲击时上限应更紧（除边界外）
    if coupon_t > 1.5:
        assert rng_imp.max_t < rng_no.max_t


def test_thickness_no_impact_above_10_unaffected():
    """t>10 时冲击要求不影响上限（仍为2t）。"""
    std = get_default_standard()
    rng = std.coverage_thickness(16.0, impact_required=True)
    assert rng.max_t == pytest.approx(32.0)  # 2*16，未收紧


# ---------------------------------------------------------------------------
# 管径覆盖
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("coupon_d, expect_min", [
    (25.0, 25.0),    # D≤25 → [D, 不限]
    (60.0, 30.0),    # D>25 → [0.5D, 不限]
    (100.0, 50.0),
])
def test_diameter_coverage(coupon_d, expect_min):
    rng = get_default_standard().coverage_diameter(coupon_d)
    assert rng.min_d == pytest.approx(expect_min)
    assert rng.max_d is None  # 不限上限


# ---------------------------------------------------------------------------
# 位置覆盖：高难度覆盖低难度
# ---------------------------------------------------------------------------

def test_position_coverage_4g_covers_all_plate():
    std = get_default_standard()
    covered = std.coverage_positions(Position.PLATE_4G)
    covered_vals = {p.value for p in covered}
    # 仰焊(4G) 覆盖平/横/立/仰
    assert {"1G", "2G", "3G", "4G"}.issubset(covered_vals)


def test_position_coverage_6g_covers_most():
    std = get_default_standard()
    covered = std.coverage_positions(Position.PIPE_6G)
    covered_vals = {p.value for p in covered}
    # 6G 覆盖管各位置
    assert "6G" in covered_vals
    assert "5G" in covered_vals


# ---------------------------------------------------------------------------
# 整体覆盖校验：WPS 在范围内 → ok；超范围 → 不 ok
# ---------------------------------------------------------------------------

def test_wps_thickness_within_pqr_coverage(engine):
    """PQR 评定 16mm → 覆盖 [1.5, 32]；WPS 用 20mm → 在范围内。"""
    pqr = make_pqr_q345r_smaw(thickness=16.0)
    wps = make_wps_from_pqr(pqr)
    # 调整 WPS 母材厚度到 20mm（仍在 2t=32 覆盖内）
    wps.base_metals[0].thickness = 20.0
    wps.deposited_thickness = 20.0
    res = engine.check_coverage(pqr, wps)
    assert res.hard_ok


def test_wps_thickness_outside_pqr_coverage(engine):
    """PQR 评定 16mm → 覆盖上限 32mm；WPS 用 40mm → 超范围（硬失败）。"""
    pqr = make_pqr_q345r_smaw(thickness=16.0)
    wps = make_wps_from_pqr(pqr)
    wps.base_metals[0].thickness = 40.0  # 超 2t=32
    wps.deposited_thickness = 40.0
    res = engine.check_coverage(pqr, wps)
    assert not res.hard_ok
    assert any("超出" in n for n in res.notes)


def test_position_not_covered_is_soft_warning(engine):
    """位置未覆盖应为软提示（position_ok=False），但不应判硬失败。"""
    pqr = make_pqr_q345r_smaw(position=Position.PLATE_1G)
    wps = make_wps_from_pqr(pqr)
    wps.positions = [Position.PLATE_3G]  # 立焊，PQR 平焊未覆盖
    res = engine.check_coverage(pqr, wps)
    # 位置未覆盖 → position_ok=False，但厚度范围仍合格 → hard_ok=True
    assert res.hard_ok
    assert not res.position_ok
    assert any("△" in n for n in res.notes)  # 提示标记，非 ✗ 硬失败
