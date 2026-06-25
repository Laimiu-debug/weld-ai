"""焊接成本计算引擎。

根据焊缝几何 + 焊接参数 + 价格，计算：
  - 熔敷金属体积与焊材消耗量（考虑熔敷效率）
  - 保护气体消耗量
  - 燃弧时间与总工时
  - 焊材/气体/人工/设备综合成本
  - 热输入（线能量）

支持多方案对比（同一焊缝用不同焊接方法/参数）。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.cost import (
    CostBreakdown,
    CostFactors,
    PassCostInput,
    WeldGeometry,
)


class CostEngine:
    """焊接成本计算引擎。"""

    def estimate_pass(
        self,
        geometry: WeldGeometry,
        p: PassCostInput,
        factors: CostFactors,
    ) -> CostBreakdown:
        """估算单道焊缝的成本。

        计算逻辑：
          1. 熔敷金属体积 = 截面积 × 长度 × 余高系数
          2. 焊材消耗 = 体积 × 密度 / 熔敷效率
          3. 燃弧时间 = 焊材消耗 / 熔敷速度（或 长度/焊接速度）
          4. 气体消耗 = 气体流量 × 燃弧时间
          5. 总工时 = 燃弧时间 / 电弧时间系数
          6. 各项成本 = 消耗量 × 单价
        """
        bd = CostBreakdown()

        # 1. 熔敷金属体积
        volume = geometry.groove_area * geometry.weld_length * geometry.reinforcement_factor  # mm³

        # 2. 焊材消耗量（kg）：体积×密度/熔敷效率
        bd.consumable_mass = volume * p.consumable_density / max(p.deposition_efficiency, 0.01)
        bd.consumable_cost = bd.consumable_mass * factors.consumable_price

        # 3. 热输入 kJ/mm = I×U/v（v单位cm/min→mm/s: /600）
        if p.travel_speed > 0 and p.current_avg > 0 and p.voltage_avg > 0:
            # v [cm/min] = 10 [mm/s]·... ; 热输入=600×I×U/(1000×v_cm_per_min) [kJ/mm]
            bd._heat_input = 60 * p.current_avg * p.voltage_avg / (1000 * p.travel_speed)

        # 4. 燃弧时间（h）：优先用熔敷速度，否则用焊接速度
        if p.deposition_rate > 0:
            bd.arc_time = bd.consumable_mass / p.deposition_rate
        elif p.travel_speed > 0:
            # 长度 mm / 速度 mm/min → min → h
            bd.arc_time = geometry.weld_length / (p.travel_speed * 10) / 60

        # 5. 气体消耗（L）= 流量 × 燃弧时间(min)
        if p.gas_flow > 0 and bd.arc_time > 0:
            bd.gas_volume = p.gas_flow * bd.arc_time * 60
            bd.gas_cost = bd.gas_volume / factors.gas_bottle_volume * factors.gas_price

        # 6. 总工时（含非燃弧时间）
        arc_factor = max(factors.arc_time_factor, 0.01)
        bd.total_time = bd.arc_time / arc_factor
        bd.labor_cost = bd.total_time * factors.labor_rate
        bd.equipment_cost = bd.total_time * factors.equipment_rate

        return bd

    def estimate_multi_pass(
        self,
        total_geometry: WeldGeometry,
        passes: list[tuple[PassCostInput, CostFactors]],
    ) -> CostBreakdown:
        """多道焊缝总成本（各道相加，几何按焊缝金属量分配）。

        passes: [(焊道输入, 价格参数), ...]。若焊缝分多道，总熔敷量按道数均分。
        """
        total = CostBreakdown()
        n = len(passes) or 1
        # 按道数均分几何（粗略；精确应按每道截面积）
        per_geometry = WeldGeometry(
            weld_length=total_geometry.weld_length,
            groove_area=total_geometry.groove_area / n,
            reinforcement_factor=total_geometry.reinforcement_factor,
        )
        for p_input, factors in passes:
            bd = self.estimate_pass(per_geometry, p_input, factors)
            total.consumable_mass += bd.consumable_mass
            total.consumable_cost += bd.consumable_cost
            total.gas_volume += bd.gas_volume
            total.gas_cost += bd.gas_cost
            total.arc_time += bd.arc_time
            total.total_time += bd.total_time
            total.labor_cost += bd.labor_cost
            total.equipment_cost += bd.equipment_cost
            total._heat_input = max(total._heat_input, bd._heat_input)
        return total


@dataclass
class CostSchemeComparison:
    """多方案成本对比结果。"""

    schemes: dict[str, CostBreakdown]

    def best(self, metric: str = "total") -> tuple[str, CostBreakdown]:
        """返回某指标最优的方案。metric: total/consumable_cost/gas_cost/labor_cost。"""
        best_name = ""
        best_val = float("inf")
        best_bd = None
        for name, bd in self.schemes.items():
            val = getattr(bd, metric)
            if val < best_val:
                best_val = val
                best_name = name
                best_bd = bd
        return best_name, best_bd

    def savings(self, metric: str = "total") -> dict[str, float]:
        """各方案相对最贵方案的节省比例。"""
        vals = {name: getattr(bd, metric) for name, bd in self.schemes.items()}
        max_val = max(vals.values()) if vals else 0
        return {
            name: (max_val - val) / max_val * 100 if max_val > 0 else 0
            for name, val in vals.items()
        }
