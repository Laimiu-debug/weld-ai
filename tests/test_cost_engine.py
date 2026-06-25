"""成本计算引擎单测。"""
from __future__ import annotations

import pytest

from weldai.domain.cost import CostFactors, PassCostInput, WeldGeometry
from weldai.engine import CostEngine, CostSchemeComparison


@pytest.fixture
def engine() -> CostEngine:
    return CostEngine()


@pytest.fixture
def factors() -> CostFactors:
    return CostFactors()


# ---------------------------------------------------------------------------
# 单道焊缝成本
# ---------------------------------------------------------------------------

def test_single_pass_consumable_mass(engine, factors):
    """焊材消耗量应正确计算：体积×密度/效率。

    钢密度 7.85 g/cm³ = 7.85e-6 kg/mm³。
    50mm²×1000mm=50000mm³，×1.1余高=55000mm³ → 质量≈0.455kg。
    """
    geo = WeldGeometry(weld_length=1000, groove_area=50)  # V=50000mm³×1.1
    p = PassCostInput(deposition_efficiency=0.95)
    bd = engine.estimate_pass(geo, p, factors)
    expected_mass = 1000 * 50 * 1.1 * 7.85e-6 / 0.95  # ≈0.455kg
    assert bd.consumable_mass == pytest.approx(expected_mass, rel=0.01)
    assert bd.consumable_cost == pytest.approx(expected_mass * factors.consumable_price)


def test_heat_input_calculation(engine, factors):
    """热输入 = 60×I×U/(1000×v_cm_per_min) kJ/mm。"""
    geo = WeldGeometry(weld_length=100, groove_area=20)
    p = PassCostInput(
        current_avg=150, voltage_avg=24, travel_speed=30.0,  # cm/min
        deposition_rate=2.0,  # 给定熔敷速度以算时间
    )
    bd = engine.estimate_pass(geo, p, factors)
    expected_hi = 60 * 150 * 24 / (1000 * 30)  # =0.72 kJ/mm
    assert bd.heat_input == pytest.approx(expected_hi, rel=0.01)


def test_gas_cost_with_flow(engine, factors):
    """有气体流量时应计算气体成本。"""
    geo = WeldGeometry(weld_length=1000, groove_area=50)
    p = PassCostInput(
        deposition_efficiency=0.95,
        deposition_rate=2.0,   # kg/h
        gas_flow=10.0,         # L/min
    )
    bd = engine.estimate_pass(geo, p, factors)
    assert bd.gas_volume > 0
    assert bd.gas_cost == pytest.approx(
        bd.gas_volume / factors.gas_bottle_volume * factors.gas_price
    )


def test_arc_time_and_labor(engine, factors):
    """燃弧时间 = 焊材消耗/熔敷速度；总工时 = 燃弧/电弧系数。"""
    geo = WeldGeometry(weld_length=1000, groove_area=50)
    p = PassCostInput(deposition_efficiency=0.95, deposition_rate=2.0)
    bd = engine.estimate_pass(geo, p, factors)
    assert bd.arc_time > 0
    assert bd.total_time == pytest.approx(bd.arc_time / factors.arc_time_factor)
    assert bd.labor_cost == pytest.approx(bd.total_time * factors.labor_rate)


# ---------------------------------------------------------------------------
# 多方案对比
# ---------------------------------------------------------------------------

def test_scheme_comparison_best(engine, factors):
    """方案对比应找出成本最低者。"""
    geo = WeldGeometry(weld_length=1000, groove_area=50)
    # 方案A：SMAW低效率
    bd_a = engine.estimate_pass(geo, PassCostInput(deposition_efficiency=0.55,
                                                   deposition_rate=1.5), factors)
    # 方案B：GMAW高效率（省焊材）
    factors_b = CostFactors(consumable_price=35.0)  # 焊丝更贵但效率高
    bd_b = engine.estimate_pass(geo, PassCostInput(deposition_efficiency=0.95,
                                                   deposition_rate=3.0), factors_b)
    comp = CostSchemeComparison(schemes={"SMAW": bd_a, "GMAW": bd_b})
    best_name, best_bd = comp.best("total")
    assert best_name in ("SMAW", "GMAW")
    assert best_bd.total <= min(bd_a.total, bd_b.total)


def test_scheme_savings(engine, factors):
    """节省比例应为 0~100。"""
    geo = WeldGeometry(weld_length=100, groove_area=20)
    bd1 = engine.estimate_pass(geo, PassCostInput(deposition_efficiency=0.55), factors)
    bd2 = engine.estimate_pass(geo, PassCostInput(deposition_efficiency=0.95), factors)
    comp = CostSchemeComparison(schemes={"方案1": bd1, "方案2": bd2})
    savings = comp.savings("consumable_cost")
    for v in savings.values():
        assert 0 <= v <= 100
