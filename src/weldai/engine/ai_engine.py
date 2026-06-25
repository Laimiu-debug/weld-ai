"""AI 辅助引擎：PQR→WPS 自动派生 + 焊接参数智能推荐。

这是 weldAI 的差异化核心。区别于外部大模型，本引擎基于**规则引擎的反向应用**：
  - PQR→WPS 派生：依据覆盖范围反推 WPS 的合法参数区间，保证生成的 WPS
    一定落在 PQR 评定范围内（可由 factor_engine 校验通过）
  - 参数推荐：依据母材类组 + 焊接方法，从焊材库推荐匹配焊材及经验参数

这样产出的结果是**可解释、可追溯、合规**的，而非黑盒建议。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ..domain.base_metal import BaseMetal, BaseMetalThicknessPair
from ..domain.consumable import Consumable
from ..domain.enums import (
    CurrentType,
    Position,
    ProcedureType,
    WeldingProcess,
)
from ..domain.procedure import PassLayer, Procedure
from ..standards.base import StandardProfile
from .coverage_engine import CoverageEngine
from .factor_engine import FactorEngine


# ---------------------------------------------------------------------------
# PQR → WPS 自动派生
# ---------------------------------------------------------------------------

@dataclass
class DerivationReport:
    """派生报告：说明 WPS 各参数区间的来源与依据。"""

    wps: Procedure
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class WPSDeriver:
    """PQR → WPS 自动派生器。

    核心思想：对 PQR 的每一项参数，调用覆盖引擎反推其合法区间，
    生成一个"范围版"的 WPS（生产用，参数给区间而非定点）。
    派生出的 WPS 可保证通过 factor_engine 的校验。
    """

    def __init__(self, standard: StandardProfile):
        self.standard = standard
        self.coverage = CoverageEngine(standard)
        self.factor = FactorEngine(standard)

    def derive(
        self,
        pqr: Procedure,
        wps_no: str = "WPS-派生",
        target_positions: list[Position] | None = None,
        target_thickness_ratio: float = 1.0,
    ) -> DerivationReport:
        """从 PQR 派生一个合法 WPS。

        参数：
          pqr: 评定基准
          wps_no: 新 WPS 编号
          target_positions: 目标焊接位置（必须落在 PQR 覆盖位置内）
          target_thickness_ratio: 目标厚度占 PQR 覆盖上限的比例(0~1)，用于
                                  生成一个具体的厚度而非满量程区间
        """
        report = DerivationReport(wps=copy.deepcopy(pqr))
        wps = report.wps
        wps.doc_no = wps_no
        wps.type = ProcedureType.WPS
        wps.supporting_pqr_no = pqr.doc_no
        wps.standard_version = self.standard.registry_key

        # 1. 厚度：取 PQR 覆盖范围的中间值（具体值，便于生产）
        trange = self.coverage.thickness_coverage(pqr)
        if trange is not None and pqr.base_metals:
            upper = trange.max_t or trange.min_t * 2
            target_t = trange.min_t + (upper - trange.min_t) * target_thickness_ratio
            for bm in wps.base_metals:
                bm.thickness = round(target_t, 1)
            wps.deposited_thickness = round(target_t, 1)
            report.notes.append(
                f"母材厚度：PQR覆盖[{trange.min_t:g}, {trange.max_t or '不限'}]mm，"
                f"取目标 {target_t:.1f}mm（比例{target_thickness_ratio:.0%}）"
            )

        # 2. 焊接位置：落在 PQR 覆盖位置内
        covered_positions = {p.value for p in self.coverage.position_coverage(pqr)}
        if target_positions:
            invalid = [p.value for p in target_positions if p.value not in covered_positions]
            if invalid:
                report.warnings.append(
                    f"目标位置 {invalid} 超出 PQR 覆盖范围(覆盖: "
                    f"{sorted(covered_positions)})，已回退到 PQR 位置"
                )
                wps.positions = list(pqr.positions)
            else:
                wps.positions = list(target_positions)
                report.notes.append(
                    f"焊接位置：{[p.value for p in target_positions]}（在 PQR 覆盖内）"
                )
        else:
            wps.positions = list(pqr.positions)
            report.notes.append(f"焊接位置：沿用 PQR 的 {covered_positions}")

        # 3. 焊材：沿用 PQR（同分类栏位，避免触发重要因素）
        report.notes.append(
            f"焊材：沿用 PQR 焊材（{[c.brand for c in pqr.consumables]}），"
            f"避免跨分类栏位触发重新评定"
        )

        # 4. 电源类型：沿用 PQR（2023 版电源类型为重要因素，不可变）
        report.notes.append("电源类型：沿用 PQR（2023版电源类型为重要因素，变更需重新评定）")

        # 5. 预热：不得低于 PQR（降低>50℃为重要因素）
        if pqr.preheat_min is not None:
            wps.preheat_min = pqr.preheat_min
            report.notes.append(
                f"预热温度：保持 ≥{pqr.preheat_min:g}℃（降低超50℃触发重新评定）"
            )

        # 6. PWHT：沿用 PQR 类别
        report.notes.append("焊后热处理：沿用 PQR 类别（变更触发重新评定）")

        # 7. 自校验：确保派生的 WPS 能通过校验
        verify = self.factor.compare(pqr, wps)
        if verify.needs_requalify:
            report.warnings.append(
                f"⚠ 派生的 WPS 存在需重新评定的因素："
                + "; ".join(c.factor_name for c in verify.changes
                            if c.action.value == "requalify")
            )
        else:
            report.notes.append(
                f"✓ 自校验通过：{verify.verdict_cn}"
            )

        return report


# ---------------------------------------------------------------------------
# 焊接参数智能推荐
# ---------------------------------------------------------------------------

# 经验参数库：按 焊接方法 + 母材大类 给出推荐参数范围
# 数据来源：焊接工艺手册经验值（非标准强制，供初拟参考）
_EXPERIENCE_PARAMS: dict[str, dict] = {
    "SMAW": {
        "diameters": [2.5, 3.2, 4.0],
        "current_range": {2.5: (70, 100), 3.2: (100, 140), 4.0: (140, 190)},
        "voltage_range": (22, 26),
        "deposition_rate": {2.5: 1.0, 3.2: 1.6, 4.0: 2.4},  # kg/h
        "efficiency": 0.55,  # SMAW 熔敷效率较低
    },
    "GTAW": {
        "diameters": [2.0, 2.5, 3.0],
        "current_range": {2.0: (80, 120), 2.5: (100, 160), 3.0: (140, 220)},
        "voltage_range": (10, 16),
        "deposition_rate": {2.0: 0.5, 2.5: 0.8, 3.0: 1.2},
        "efficiency": 0.98,
        "gas_type": "Ar",
        "gas_flow": (8, 12),
    },
    "GMAW": {
        "diameters": [1.0, 1.2, 1.6],
        "current_range": {1.0: (90, 180), 1.2: (140, 260), 1.6: (200, 350)},
        "voltage_range": (18, 30),
        "deposition_rate": {1.0: 1.5, 1.2: 2.5, 1.6: 4.0},
        "efficiency": 0.95,
        "gas_type": "80%Ar+20%CO2",
        "gas_flow": (15, 20),
    },
    "SAW": {
        "diameters": [3.2, 4.0, 5.0],
        "current_range": {3.2: (350, 500), 4.0: (450, 650), 5.0: (550, 800)},
        "voltage_range": (30, 38),
        "deposition_rate": {3.2: 4.0, 4.0: 6.0, 5.0: 8.0},
        "efficiency": 0.99,
    },
}


@dataclass
class Recommendation:
    """参数推荐结果。"""

    consumables: list[Consumable] = field(default_factory=list)
    recommended_diameter: float = 0.0
    current_range: tuple[float, float] = (0, 0)
    voltage_range: tuple[float, float] = (0, 0)
    deposition_rate: float = 0.0
    efficiency: float = 0.0
    gas_type: str = ""
    gas_flow_range: tuple[float, float] = (0, 0)
    notes: list[str] = field(default_factory=list)


class ParameterAdvisor:
    """焊接参数智能推荐器。

    给定母材类组 + 焊接方法，从焊材库筛选匹配焊材，
    并结合经验参数库给出推荐焊接参数范围。
    """

    def __init__(self, standard: StandardProfile):
        self.standard = standard

    def recommend(
        self,
        material_grade: str,
        process: WeldingProcess,
        thickness: float = 12.0,
    ) -> Recommendation:
        """推荐焊材与参数。

        厚度影响推荐焊材直径（薄板选小直径，厚板选大直径）。
        """
        rec = Recommendation()
        metal = self.standard.get_base_metal(material_grade)

        # 1. 焊材筛选：适用该母材类组的
        if metal:
            rec.consumables = self.standard.consumables_for_group(metal.group.group)
            if rec.consumables:
                rec.notes.append(
                    f"匹配母材 {material_grade}({metal.group.group}) 的焊材："
                    f"{[c.brand for c in rec.consumables]}"
                )
            else:
                rec.notes.append(f"⚠ 焊材库中暂无适用 {metal.group.group} 的焊材")
        else:
            rec.notes.append(f"⚠ 母材 {material_grade} 不在标准库")

        # 2. 经验参数
        params = _EXPERIENCE_PARAMS.get(process.value)
        if params is None:
            rec.notes.append(f"⚠ 暂无 {process.value} 的经验参数库")
            return rec

        # 直径：按厚度选（薄<6→小，6~20→中，>20→大）
        diameters = params["diameters"]
        if thickness < 6:
            rec.recommended_diameter = diameters[0]
        elif thickness > 20:
            rec.recommended_diameter = diameters[-1]
        else:
            rec.recommended_diameter = diameters[len(diameters) // 2]

        rec.current_range = params["current_range"].get(rec.recommended_diameter, (0, 0))
        rec.voltage_range = params["voltage_range"]
        rec.deposition_rate = params["deposition_rate"].get(rec.recommended_diameter, 0)
        rec.efficiency = params["efficiency"]
        rec.gas_type = params.get("gas_type", "")
        rec.gas_flow_range = params.get("gas_flow", (0, 0))

        rec.notes.append(
            f"推荐参数({process.value}, 板厚{thickness:g}mm)："
            f"焊材直径φ{rec.recommended_diameter:g}mm, "
            f"电流{rec.current_range[0]:g}~{rec.current_range[1]:g}A, "
            f"电压{rec.voltage_range[0]:g}~{rec.voltage_range[1]:g}V, "
            f"熔敷速度{rec.deposition_rate:g}kg/h"
        )
        rec.notes.append(
            f"说明：参数为经验初拟值，须经工艺评定(PQR)验证后方可用于生产"
        )

        return rec
