"""覆盖范围计算与校验引擎。

依据 NB/T 47014 表7：给定 PQR 评定试件尺寸 → 计算 WPS 可用范围；
再校验目标 WPS 的实际尺寸是否落在该范围内。

设计要点（职责划分）：
  - 厚度/管径是数值范围，超出即「硬失败」→ 必须重新找支撑 PQR
  - 焊接位置由因素引擎按变更等级判定（次要/补加/重要），
    覆盖引擎只记录位置情况作为「提示」，不直接判为硬失败
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.enums import Position
from ..domain.procedure import Procedure
from ..standards.base import StandardProfile


@dataclass
class CoverageResult:
    """覆盖校验结构化结果。

    - ``hard_ok``：厚度/管径数值范围是否全部合格（硬失败判定）
    - ``position_ok``：焊接位置是否在覆盖范围内（仅提示，交给因素引擎定级）
    - ``notes``：逐项说明（✓/✗/△ 三类标记）
    """

    hard_ok: bool = True
    position_ok: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """向后兼容：整体是否合格（含位置，用于纯数值覆盖场景的旧调用）。"""
        return self.hard_ok and self.position_ok

    def as_tuple(self) -> tuple[bool, list[str]]:
        """兼容旧的 (ok, notes) 调用形式，ok 仅取硬失败判定。"""
        return self.hard_ok, self.notes


class CoverageEngine:
    """覆盖范围引擎。"""

    def __init__(self, standard: StandardProfile):
        self.standard = standard

    # ------------------------------------------------------------------
    # 范围计算（PQR → 覆盖范围）
    # ------------------------------------------------------------------

    def thickness_coverage(
        self, pqr: Procedure
    ):
        """PQR 母材厚度覆盖范围。"""
        coupon_t = pqr.max_base_thickness
        if coupon_t <= 0:
            return None
        return self.standard.coverage_thickness(
            coupon_t, impact_required=pqr.impact_required
        )

    def deposited_thickness_coverage(self, pqr: Procedure):
        """PQR 焊缝金属厚度覆盖范围。"""
        t = pqr.deposited_thickness or pqr.max_base_thickness
        if t <= 0:
            return None
        return self.standard.coverage_deposited_thickness(
            t, impact_required=pqr.impact_required
        )

    def diameter_coverage(self, pqr: Procedure):
        """PQR 管径覆盖范围（管对接）。"""
        d = None
        for j in pqr.joints:
            if j.outer_diameter:
                d = j.outer_diameter
                break
        if d is None:
            return None
        return self.standard.coverage_diameter(d)

    def position_coverage(self, pqr: Procedure) -> list[Position]:
        """PQR 焊接位置覆盖列表。"""
        covered: list[Position] = []
        for pos in pqr.positions:
            covered.extend(self.standard.coverage_positions(pos))
        seen: set[str] = set()
        result: list[Position] = []
        for p in covered:
            if p.value not in seen:
                seen.add(p.value)
                result.append(p)
        return result

    # ------------------------------------------------------------------
    # 校验：WPS 是否落在 PQR 覆盖范围
    # ------------------------------------------------------------------

    def check_coverage(
        self, pqr: Procedure, wps: Procedure
    ) -> CoverageResult:
        """校验 WPS 厚度/管径/位置是否在 PQR 覆盖范围内。"""
        res = CoverageResult()

        # 母材厚度（硬失败）
        trange = self.thickness_coverage(pqr)
        if trange is not None:
            wps_t = wps.max_base_thickness
            if wps_t > 0:
                if trange.contains(wps_t):
                    res.notes.append(
                        f"✓ 母材厚度 {wps_t:g}mm 在 PQR 覆盖范围 {trange} 内"
                    )
                else:
                    res.hard_ok = False
                    res.notes.append(
                        f"✗ 母材厚度 {wps_t:g}mm 超出 PQR 覆盖范围 {trange}"
                    )

        # 焊缝金属厚度（硬失败）
        drange = self.deposited_thickness_coverage(pqr)
        if drange is not None and wps.deposited_thickness:
            if drange.contains(wps.deposited_thickness):
                res.notes.append(
                    f"✓ 焊缝金属厚度 {wps.deposited_thickness:g}mm "
                    f"在覆盖范围 {drange} 内"
                )
            else:
                res.hard_ok = False
                res.notes.append(
                    f"✗ 焊缝金属厚度 {wps.deposited_thickness:g}mm "
                    f"超出覆盖范围 {drange}"
                )

        # 管径（硬失败）
        prange = self.diameter_coverage(pqr)
        if prange is not None:
            for j in wps.joints:
                if j.outer_diameter:
                    if prange.contains(j.outer_diameter):
                        res.notes.append(
                            f"✓ 管径 {j.outer_diameter:g}mm "
                            f"在覆盖范围 {prange} 内"
                        )
                    else:
                        res.hard_ok = False
                        res.notes.append(
                            f"✗ 管径 {j.outer_diameter:g}mm "
                            f"超出覆盖范围 {prange}"
                        )

        # 焊接位置（软提示：交给因素引擎按变更等级定级）
        covered_pos = {p.value for p in self.position_coverage(pqr)}
        for pos in wps.positions:
            if pos.value not in covered_pos:
                res.position_ok = False
                res.notes.append(
                    f"△ 焊接位置 {pos.value} 不在 PQR 覆盖位置内"
                    f"（PQR覆盖: {sorted(covered_pos)}），按因素等级判定"
                )
            else:
                res.notes.append(f"✓ 焊接位置 {pos.value} 在覆盖范围内")

        return res
