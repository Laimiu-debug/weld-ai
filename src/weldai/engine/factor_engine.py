"""焊接工艺评定因素变更判定引擎。

核心职责：对比一个 PQR（评定基准）与一个 WPS（生产规程），
识别所有参数变更，并标注每项变更对应的因素等级与处置动作。

判定逻辑是"规则驱动"的：具体的因素定义来自 StandardProfile 的 YAML 数据，
本引擎只编排比对流程，不硬编码任何标准规则 → 多标准通用。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import FactorLevel, WeldingProcess
from ..domain.procedure import Procedure
from ..standards.base import StandardProfile
from .actions import Action, FactorChange, decide_action


@dataclass
class QualificationResult:
    """一份 WPS 相对其支撑 PQR 的完整校验结果。"""

    wps_no: str
    pqr_no: str
    standard: str
    changes: list[FactorChange]
    hard_coverage_ok: bool                # WPS 厚度/管径是否在 PQR 覆盖范围内（硬失败）
    coverage_ok: bool                     # 整体覆盖（含位置），向后兼容
    coverage_notes: list[str]

    @property
    def needs_requalify(self) -> bool:
        """是否存在需要重新评定的重要因素变更。"""
        return any(c.action == Action.REQUALIFY for c in self.changes)

    @property
    def needs_supplement_impact(self) -> bool:
        return any(c.action == Action.SUPPLEMENT_IMPACT for c in self.changes)

    @property
    def worst_action(self) -> Action:
        """最严重的处置动作（用于整体判定）。"""
        if self.needs_requalify:
            return Action.REQUALIFY
        if self.needs_supplement_impact:
            return Action.SUPPLEMENT_IMPACT
        if any(c.action == Action.REVISE_WPS for c in self.changes):
            return Action.REVISE_WPS
        return Action.NONE

    @property
    def verdict_cn(self) -> str:
        """整体判定结论（中文）。

        判定优先级：
          1. 厚度/管径硬失败（超出数值范围）→ 需重新评定
          2. 重要因素变更 → 需重新评定
          3. 补加因素变更 → 补做冲击试验
          4. 次要/失效因素 → 仅改WPS
          5. 全部合格

        注：焊接位置未覆盖不单独致命，由因素引擎按位置变更等级判定
        （如向上立焊为补加因素，会被记入 changes 并按上述优先级处理）。
        """
        if not self.hard_coverage_ok:
            return "✗ 超出评定范围（厚度/管径），需重新评定"
        wa = self.worst_action
        if wa == Action.REQUALIFY:
            return "✗ 存在重要因素变更，需重新评定"
        if wa == Action.SUPPLEMENT_IMPACT:
            return "△ 存在补加因素变更，需补做冲击试验"
        if wa == Action.REVISE_WPS:
            return "○ 仅次要/失效因素变更，修改WPS即可"
        return "✓ 合格，WPS 在 PQR 评定范围内"


class FactorEngine:
    """因素变更判定引擎。

    与具体标准解耦：通过注入的 StandardProfile 获取因素定义。
    """

    def __init__(self, standard: StandardProfile):
        self.standard = standard
        from .coverage_engine import CoverageEngine
        self._coverage = CoverageEngine(standard)

    # ------------------------------------------------------------------
    # 主入口：完整比对 PQR vs WPS
    # ------------------------------------------------------------------

    def compare(self, pqr: Procedure, wps: Procedure) -> QualificationResult:
        """对比 PQR（基准）与 WPS，输出完整校验结果。"""
        changes: list[FactorChange] = []

        # 1. 焊接方法
        changes.extend(self._check_process(pqr, wps))
        # 2. 母材类组号
        changes.extend(self._check_base_metals(pqr, wps))
        # 3. 焊材分类栏位
        changes.extend(self._check_consumables(pqr, wps))
        # 4. 电源类型（2023 版重要因素）
        changes.extend(self._check_current_type(pqr, wps))
        # 5. 预热
        changes.extend(self._check_preheat(pqr, wps))
        # 6. PWHT
        changes.extend(self._check_pwht(pqr, wps))
        # 7. 焊接位置（向上立焊补加因素）
        changes.extend(self._check_positions(pqr, wps))
        # 8. 焊材直径（补加因素）
        changes.extend(self._check_diameter(pqr, wps))
        # 9. 坡口形式（次要因素）
        changes.extend(self._check_groove(pqr, wps))

        # 覆盖范围校验（结构化：区分硬失败与位置提示）
        cov = self._check_coverage(pqr, wps)

        return QualificationResult(
            wps_no=wps.doc_no,
            pqr_no=pqr.doc_no,
            standard=self.standard.standard_code,
            changes=changes,
            hard_coverage_ok=cov.hard_ok,
            coverage_ok=cov.ok,
            coverage_notes=cov.notes,
        )

    # ------------------------------------------------------------------
    # 上下文：补加因素失效条件求值
    # ------------------------------------------------------------------

    def _invalidate_context(self, pqr: Procedure) -> dict[str, bool]:
        """从 PQR 提取补加因素失效条件的取值。"""
        pwht = pqr.pwht
        return {
            "PWHT_is_upper_transformation": pwht.upper_transformation,
            "austenitic_solution_treated": pwht.austenitic_solution_treated,
        }

    def _meets_invalidate(
        self, conditions: list[str], ctx: dict[str, bool]
    ) -> bool:
        """是否满足任一失效条件。"""
        return any(ctx.get(c, False) for c in conditions)

    def _make_change(
        self,
        pqr: Procedure,
        category: str,
        desc: str,
        process: WeldingProcess,
    ) -> FactorChange | None:
        """构造一个变更记录（按语义键category查因素定义 + 决策动作）。

        ★H1修复：用 category(如 current_type/preheat) 查找因素，
        而非硬编码 ID，避免不同焊接方法 ID 偏移导致校验失效。
        无定义则返回 None（该方法可能无此因素项）。
        """
        fdef = self.standard.get_factor_by_category(process, category)
        if fdef is None:
            return None
        ctx = self._invalidate_context(pqr)
        invalidated = self._meets_invalidate(fdef.invalidate_when, ctx)
        action = decide_action(
            fdef.level,
            has_impact_requirement=pqr.impact_required,
            invalidate_conditions_met=invalidated,
        )
        return FactorChange(
            factor_id=fdef.factor_id,
            factor_name=fdef.name,
            level=fdef.level,
            change_description=desc,
            invalidate_conditions=fdef.invalidate_when,
            invalidate_conditions_met=invalidated,
            action=action,
        )

    # ------------------------------------------------------------------
    # 各项参数比对
    # ------------------------------------------------------------------

    def _check_process(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """焊接方法变更（重要因素）。

        支持组合焊：WPS 可能涉及多种方法（每道独立 process），
        要求 PQR 对 WPS 出现的每种方法都有对应评定（NB/T 47014：组合焊
        各方法需分别评定）。PQR 单方法时仅校验该方法是否匹配。
        """
        changes: list[FactorChange] = []
        wps_processes = wps.all_processes
        pqr_processes = pqr.all_processes
        for wp in wps_processes:
            if wp not in pqr_processes:
                detail = (f"焊接方法 {wp.value}({wp.cn}) 无对应PQR评定"
                          if len(wps_processes) > 1
                          else f"焊接方法 {pqr.process.value} → {wp.value}")
                c = self._make_change(
                    pqr, "process_change",
                    detail,
                    pqr.process,
                )
                if c:
                    changes.append(c)
        return changes

    def _check_base_metals(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """母材类组号变更（重要因素）。"""
        changes: list[FactorChange] = []
        pqr_groups = {bm.metal.group.group for bm in pqr.base_metals}
        wps_groups = {bm.metal.group.group for bm in wps.base_metals}

        # WPS 出现 PQR 未覆盖的类组
        for wg in sorted(wps_groups - pqr_groups):
            # 检查 PQR 任一母材能否覆盖
            covered = any(
                self.standard.base_metal_covers(pg, wg) for pg in pqr_groups
            )
            if not covered:
                pg = next(iter(pqr_groups)) if pqr_groups else "?"
                c = self._make_change(
                    pqr, "base_metal_group",
                    f"母材组别 {pg} → {wg}（超出覆盖范围）",
                    pqr.process,
                )
                if c:
                    changes.append(c)
        return changes

    def _check_consumables(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """焊材分类栏位变更（重要因素）。"""
        changes: list[FactorChange] = []
        pqr_slots = {c.classification_slot for c in pqr.consumables}
        wps_slots = {c.classification_slot for c in wps.consumables}
        for ws in sorted(wps_slots - pqr_slots):
            c = self._make_change(
                pqr, "consumable_class",
                f"焊材分类栏位变更 → {ws}",
                pqr.process,
            )
            if c:
                changes.append(c)
        return changes

    def _check_current_type(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """电源类型/极性变更（2023 版重要因素）。"""
        pqr_ct = {p.current_type for p in pqr.passes if p.current_type}
        wps_ct = {p.current_type for p in wps.passes if p.current_type}
        new_ct = wps_ct - pqr_ct
        if new_ct:
            c = self._make_change(
                pqr, "current_type",
                f"电源类型变更 → {', '.join(sorted(x.value for x in new_ct))}",
                pqr.process,
            )
            return [c] if c else []
        return []

    def _check_preheat(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """预热温度降低（重要因素）。"""
        if (
            pqr.preheat_min is not None
            and wps.preheat_min is not None
            and wps.preheat_min < pqr.preheat_min - 50
        ):
            c = self._make_change(
                pqr, "preheat",
                f"预热温度降低 {pqr.preheat_min:g}℃ → {wps.preheat_min:g}℃",
                pqr.process,
            )
            return [c] if c else []
        if pqr.preheat_min and not wps.preheat_min:
            c = self._make_change(
                pqr, "preheat_cancel",
                "取消预热",
                pqr.process,
            )
            return [c] if c else []
        return []

    def _check_pwht(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """PWHT 类别/参数变更（重要因素）。"""
        if pqr.pwht.applied != wps.pwht.applied:
            change = "增加PWHT" if wps.pwht.applied else "取消PWHT"
            c = self._make_change(
                pqr, "pwht",
                f"焊后热处理变更：{change}",
                pqr.process,
            )
            return [c] if c else []
        if (
            pqr.pwht.applied
            and wps.pwht.applied
            and pqr.pwht.pwht_type != wps.pwht.pwht_type
        ):
            c = self._make_change(
                pqr, "pwht",
                f"PWHT类型 {pqr.pwht.pwht_type} → {wps.pwht.pwht_type}",
                pqr.process,
            )
            return [c] if c else []
        return []

    def _check_positions(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """焊接位置变更（向上立焊为补加因素）。"""
        changes: list[FactorChange] = []
        # 向上立焊(3G/5G向上)相对PQR为新增 → 补加因素
        vertical = {"3G", "5G"}
        pqr_has_vertical = bool(vertical & {p.value for p in pqr.positions})
        wps_new_vertical = vertical & {p.value for p in wps.positions}
        if wps_new_vertical and not pqr_has_vertical:
            c = self._make_change(
                pqr, "position_vertical",
                f"新增向上立焊位置 {sorted(wps_new_vertical)}",
                pqr.process,
            )
            if c:
                changes.append(c)
        return changes

    def _check_diameter(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """焊材直径增大（补加因素）。"""
        changes: list[FactorChange] = []
        pqr_max_d = max(
            (p.diameter for p in pqr.passes if p.diameter), default=0.0
        )
        for p in wps.passes:
            if p.diameter and p.diameter > pqr_max_d + 1e-9:
                c = self._make_change(
                    pqr, "diameter",
                    f"焊材直径增大 {pqr_max_d:g} → {p.diameter:g} mm",
                    pqr.process,
                )
                if c:
                    changes.append(c)
                break
        return changes

    def _check_groove(
        self, pqr: Procedure, wps: Procedure
    ) -> list[FactorChange]:
        """坡口形式变更（次要因素）。"""
        changes: list[FactorChange] = []
        pqr_grooves = {j.groove.type for j in pqr.joints}
        wps_grooves = {j.groove.type for j in wps.joints}
        new_grooves = wps_grooves - pqr_grooves
        if new_grooves:
            c = self._make_change(
                pqr, "groove",
                f"坡口形式变更 → {','.join(sorted(new_grooves))}",
                pqr.process,
            )
            if c:
                changes.append(c)
        return changes

    # ------------------------------------------------------------------
    # 覆盖范围校验
    # ------------------------------------------------------------------

    def _check_coverage(
        self, pqr: Procedure, wps: Procedure
    ):
        """校验 WPS 的厚度/管径是否落在 PQR 评定覆盖范围内。"""
        return self._coverage.check_coverage(pqr, wps)
