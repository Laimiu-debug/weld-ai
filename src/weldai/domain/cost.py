"""焊接成本计算领域模型。

对标 weldassistant 成本模块：根据焊缝几何与焊接参数，
计算焊材消耗、气体消耗、工时与综合成本。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WeldGeometry:
    """焊缝几何（用于计算熔敷金属体积）。"""

    weld_length: float          # 焊缝长度 mm
    groove_area: float          # 坡口截面积 mm²（含余高，估算）
    reinforcement_factor: float = 1.1  # 余高系数（实际熔敷量/理论截面积）


@dataclass
class PassCostInput:
    """单焊道成本计算输入。"""

    consumable_density: float = 7.85e-6   # 焊材密度 kg/mm³（钢 7.85 g/cm³ = 7.85e-6 kg/mm³）
    deposition_efficiency: float = 0.95    # 熔敷效率（损耗后，SMAW约0.55，GMAW约0.95）
    diameter: float = 3.2                  # 焊材直径 mm
    deposition_rate: float = 0.0           # 熔敷速度 kg/h（由电流/电压/焊材推算）
    wire_feed_speed: float = 0.0           # 送丝速度 m/min（熔化极）
    gas_type: str = ""                     # 保护气体
    gas_flow: float = 0.0                  # 气体流量 L/min
    travel_speed: float = 0.0             # 焊接速度 cm/min
    current_avg: float = 0.0              # 平均电流 A
    voltage_avg: float = 0.0             # 平均电压 V


@dataclass
class CostFactors:
    """价格参数。"""

    consumable_price: float = 30.0    # 焊材 元/kg
    gas_price: float = 50.0           # 气体 元/瓶（40L标准瓶≈6000L）
    gas_bottle_volume: float = 6000.0 # 每瓶气体体积 L
    labor_rate: float = 80.0          # 人工费 元/h（含管理费）
    arc_time_factor: float = 0.4      # 电弧时间系数（实际燃弧/总工时，含换条/清渣等）
    equipment_rate: float = 0.0       # 设备折旧 元/h


@dataclass
class CostBreakdown:
    """单项成本分解。"""

    consumable_mass: float = 0.0      # 焊材消耗量 kg
    consumable_cost: float = 0.0      # 焊材成本 元
    gas_volume: float = 0.0           # 气体消耗量 L
    gas_cost: float = 0.0             # 气体成本 元
    arc_time: float = 0.0             # 燃弧时间 h
    total_time: float = 0.0           # 总工时 h
    labor_cost: float = 0.0           # 人工成本 元
    equipment_cost: float = 0.0       # 设备成本 元

    @property
    def total(self) -> float:
        return self.consumable_cost + self.gas_cost + self.labor_cost + self.equipment_cost

    @property
    def heat_input(self) -> float:
        """热输入 kJ/mm（若可计算）。"""
        return self._heat_input

    _heat_input: float = field(default=0.0)
