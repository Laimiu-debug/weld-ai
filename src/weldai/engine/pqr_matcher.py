"""PQR 匹配筛选器：给定焊缝需求 → 遍历所有 PQR 找出能覆盖它的。

这是规则引擎的正向实用应用，解决生产中最高频的问题：
"我这条焊缝（母材+厚度+位置+方法），现有哪些 PQR 能覆盖，无需重新评定？"

匹配维度（全部满足才算覆盖）：
  1. 焊接方法一致
  2. 母材类组被覆盖（高组别覆盖低组别 / 并列不互覆盖）
  3. 母材厚度在 PQR 覆盖范围内
  4. 管径在覆盖范围内（管焊缝时）
  5. 焊接位置被覆盖
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.enums import Position, WeldingProcess
from ..domain.procedure import Procedure
from ..persistence import ProcedureRepository
from ..standards.base import StandardProfile
from .coverage_engine import CoverageEngine


@dataclass
class WeldRequirement:
    """焊缝需求（待匹配的焊缝参数）。"""

    process: WeldingProcess               # 焊接方法
    material_grade: str = ""              # 母材牌号（自动查类组）
    material_group: str = ""              # 或直接给类组号（如 Fe-1-2）
    thickness: float = 0.0                # 母材厚度 mm
    outer_diameter: float | None = None   # 管外径 mm（板材留空）
    position: Position = Position.PLATE_1G
    impact_required: bool = False         # 是否有冲击要求（影响厚度上限）


@dataclass
class MatchDimension:
    """单维度匹配结果。"""

    name: str            # 维度名
    passed: bool         # 是否满足
    detail: str          # 说明（如 PQR 覆盖范围 vs 焊缝需求）


@dataclass
class PQRSuitability:
    """单个 PQR 对焊缝需求的适配度评估。"""

    pqr: Procedure
    fully_matched: bool = False          # 是否所有维度都满足
    dimensions: list[MatchDimension] = field(default_factory=list)
    miss_count: int = 0                  # 不满足的维度数

    @property
    def pqr_no(self) -> str:
        return self.pqr.doc_no

    @property
    def verdict_cn(self) -> str:
        if self.fully_matched:
            return "✓ 完全覆盖（无需重新评定）"
        if self.miss_count == 1:
            return "△ 仅1项不满足（补做冲击/改WPS可能解决）"
        return f"✗ {self.miss_count}项不满足（需重新评定或补做PQR）"


class PQRMatcher:
    """PQR 匹配筛选器。"""

    def __init__(self, repo: ProcedureRepository, standard: StandardProfile):
        self.repo = repo
        self.standard = standard
        self.coverage = CoverageEngine(standard)

    def match(self, req: WeldRequirement) -> list[PQRSuitability]:
        """遍历所有 PQR，评估每个对焊缝需求的适配度。

        返回所有 PQR 的评估结果（按 fully_matched 优先排序）。
        """
        # 确定母材类组号
        target_group = req.material_group
        if not target_group and req.material_grade:
            metal = self.standard.get_base_metal(req.material_grade)
            if metal:
                target_group = metal.group.group

        pqrs = self.repo.list_all()
        # 只看 PQR 类型
        from ..domain.enums import ProcedureType
        pqrs = [p for p in pqrs if p.type == ProcedureType.PQR]

        results = [self._evaluate(pqr, req, target_group) for pqr in pqrs]
        # 排序：完全匹配优先，然后按 miss_count 升序
        results.sort(key=lambda r: (not r.fully_matched, r.miss_count))
        return results

    def find_matched(self, req: WeldRequirement) -> list[Procedure]:
        """只返回完全匹配的 PQR 列表（便捷方法）。"""
        return [r.pqr for r in self.match(req) if r.fully_matched]

    def _evaluate(
        self, pqr: Procedure, req: WeldRequirement, target_group: str
    ) -> PQRSuitability:
        """评估单个 PQR 对需求的适配度。"""
        dims: list[MatchDimension] = []
        suit = PQRSuitability(pqr=pqr)

        # 1. 焊接方法
        method_ok = pqr.process == req.process
        dims.append(MatchDimension(
            name="焊接方法",
            passed=method_ok,
            detail=f"需求 {req.process.value} vs PQR {pqr.process.value}",
        ))

        # 2. 母材类组覆盖
        if target_group:
            pqr_groups = {bm.metal.group.group for bm in pqr.base_metals}
            covers = any(
                self.standard.base_metal_covers(pg, target_group)
                for pg in pqr_groups
            )
            dims.append(MatchDimension(
                name="母材类组",
                passed=covers,
                detail=f"需求 {target_group} vs PQR覆盖 {sorted(pqr_groups)}",
            ))
        else:
            dims.append(MatchDimension(
                name="母材类组", passed=False,
                detail="未指定母材（无法判定）",
            ))

        # 3. 母材厚度覆盖
        trange = self.coverage.thickness_coverage(pqr)
        if trange is not None and req.thickness > 0:
            t_ok = trange.contains(req.thickness)
            dims.append(MatchDimension(
                name="母材厚度",
                passed=t_ok,
                detail=f"需求 {req.thickness:g}mm vs PQR覆盖 {trange}",
            ))
        else:
            dims.append(MatchDimension(
                name="母材厚度", passed=False,
                detail="PQR 无有效厚度数据",
            ))

        # 4. 管径覆盖（仅管焊缝）
        if req.outer_diameter:
            prange = self.coverage.diameter_coverage(pqr)
            if prange is not None:
                d_ok = prange.contains(req.outer_diameter)
                dims.append(MatchDimension(
                    name="管径",
                    passed=d_ok,
                    detail=f"需求 φ{req.outer_diameter:g}mm vs PQR覆盖 {prange}",
                ))
            else:
                dims.append(MatchDimension(
                    name="管径", passed=False,
                    detail="PQR 为板材评定，未覆盖管径（板材PQR可覆盖φ≥76管）",
                ))

        # 5. 焊接位置覆盖
        covered_pos = {p.value for p in self.coverage.position_coverage(pqr)}
        pos_ok = req.position.value in covered_pos
        dims.append(MatchDimension(
            name="焊接位置",
            passed=pos_ok,
            detail=f"需求 {req.position.value} vs PQR覆盖 {sorted(covered_pos)}",
        ))

        suit.dimensions = dims
        suit.miss_count = sum(1 for d in dims if not d.passed)
        suit.fully_matched = (suit.miss_count == 0)
        return suit
