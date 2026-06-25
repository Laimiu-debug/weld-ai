"""因素变更判定引擎单测。

验证 NB/T 47014-2023 规则：各类参数变更对应正确的因素等级与处置动作。
"""
from __future__ import annotations

import pytest

from weldai.domain.consumable import Consumable, ConsumableType
from weldai.domain.enums import (
    CurrentType,
    FactorLevel,
    JointType,
    Position,
    WeldingProcess,
)
from weldai.domain.joint import GrooveDesign, Joint
from weldai.domain.procedure import PWHTSpec
from weldai.engine import Action, FactorEngine
from weldai.standards import get_default_standard

from .conftest import (
    make_j422,
    make_pqr_q345r_smaw,
    make_q345r_metal,
    make_q245r_metal,
    make_wps_from_pqr,
)
from weldai.domain.base_metal import BaseMetalThicknessPair


@pytest.fixture
def engine() -> FactorEngine:
    return FactorEngine(get_default_standard())


def _actions_by_level(result):
    """按等级归类变更动作。"""
    by_level: dict[str, list] = {}
    for c in result.changes:
        by_level.setdefault(c.level.value, []).append(c)
    return by_level


# ---------------------------------------------------------------------------
# 基础：WPS 与 PQR 完全一致 → 无变更、合格
# ---------------------------------------------------------------------------

def test_identical_wps_no_changes(engine):
    pqr = make_pqr_q345r_smaw()
    wps = make_wps_from_pqr(pqr)
    result = engine.compare(pqr, wps)
    assert result.changes == []
    assert result.coverage_ok is True
    assert result.worst_action == Action.NONE
    assert "合格" in result.verdict_cn


# ---------------------------------------------------------------------------
# 重要因素：电源类型变更（2023 版升级为重要）→ 需重新评定
# ---------------------------------------------------------------------------

def test_current_type_change_is_essential(engine):
    pqr = make_pqr_q345r_smaw(current_type=CurrentType.DCEP)
    wps = make_wps_from_pqr(pqr)
    # WPS 改用直流正接
    for p in wps.passes:
        p.current_type = CurrentType.DCEN
    result = engine.compare(pqr, wps)
    assert result.needs_requalify
    assert result.worst_action == Action.REQUALIFY
    ct_changes = [c for c in result.changes if "电源类型" in c.factor_name]
    assert ct_changes, "应检出电源类型变更"
    assert ct_changes[0].level == FactorLevel.ESSENTIAL


# ---------------------------------------------------------------------------
# 重要因素：母材跨类别号 → 需重新评定；同类高覆盖低 → 合格
# ---------------------------------------------------------------------------

def test_base_metal_same_category_high_covers_low(engine):
    """PQR=Q345R(Fe-1-2) 评定，WPS 用 Q245R(Fe-1-1) → 高覆盖低，合格。"""
    pqr = make_pqr_q345r_smaw()  # Fe-1-2
    wps = make_wps_from_pqr(pqr)
    # 替换母材为 Fe-1-1（低组别）
    wps.base_metals = [BaseMetalThicknessPair(make_q245r_metal(), 16.0)]
    result = engine.compare(pqr, wps)
    # 不应触发母材重新评定
    bm_changes = [
        c for c in result.changes if "母材组别" in c.factor_name
    ]
    assert bm_changes == []


def test_base_metal_cross_category_needs_requalify(engine):
    """PQR=Fe-1，WPS 用 Fe-8 不锈钢 → 跨类，需重新评定。"""
    pqr = make_pqr_q345r_smaw()  # Fe-1-2
    wps = make_wps_from_pqr(pqr)
    from weldai.domain.enums import MaterialGroup
    from weldai.domain.base_metal import BaseMetal
    ss = BaseMetal(
        grade="06Cr19Ni10",
        group=MaterialGroup("Fe", "Fe-8", "Fe-8"),
        standard="GB/T 24511",
    )
    wps.base_metals = [BaseMetalThicknessPair(ss, 16.0)]
    result = engine.compare(pqr, wps)
    assert result.needs_requalify


# ---------------------------------------------------------------------------
# 重要因素：焊材跨分类栏位 → 需重新评定
# ---------------------------------------------------------------------------

def test_consumable_slot_change_essential(engine):
    """PQR=J507(表2-E50)，WPS 改 J422(表2-E43) → 跨栏，重要因素。"""
    pqr = make_pqr_q345r_smaw()  # J507
    wps = make_wps_from_pqr(pqr)
    wps.consumables = [make_j422()]
    result = engine.compare(pqr, wps)
    assert result.needs_requalify
    slot_changes = [c for c in result.changes if "分类栏位" in c.factor_name]
    assert slot_changes
    assert slot_changes[0].level == FactorLevel.ESSENTIAL


# ---------------------------------------------------------------------------
# 补加因素：向上立焊（无冲击要求 → 仅改WPS；失效条件满足 → 降级）
# ---------------------------------------------------------------------------

def test_vertical_position_supplemental_no_impact(engine):
    """PQR 平焊，WPS 加立焊，无冲击要求 → 补加因素降为仅改WPS。"""
    pqr = make_pqr_q345r_smaw(position=Position.PLATE_1G, impact_required=False)
    wps = make_wps_from_pqr(pqr)
    wps.positions = [Position.PLATE_3G]  # 立焊
    result = engine.compare(pqr, wps)
    # 无冲击要求 → 补加因素 → 仅改WPS
    assert not result.needs_requalify
    vert_changes = [c for c in result.changes if "立焊" in c.factor_name]
    assert vert_changes


def test_vertical_position_invalidated_by_upper_transformation_pwht(engine):
    """经上转变PWHT后，向上立焊补加因素失效 → 仅改WPS（不补冲击）。"""
    pqr = make_pqr_q345r_smaw(
        position=Position.PLATE_1G,
        impact_required=True,  # 有冲击要求
        pwht=PWHTSpec(applied=True, pwht_type="正火",
                      upper_transformation=True),
    )
    wps = make_wps_from_pqr(pqr)
    wps.positions = [Position.PLATE_3G]
    result = engine.compare(pqr, wps)
    vert_changes = [c for c in result.changes if "立焊" in c.factor_name]
    assert vert_changes
    # 失效条件满足 → 不补冲击，仅改WPS
    assert vert_changes[0].action == Action.REVISE_WPS
    assert vert_changes[0].invalidate_conditions_met is True


def test_vertical_position_supplemental_with_impact(engine):
    """有冲击要求 + 向上立焊 + 无失效条件 → 补做冲击。"""
    pqr = make_pqr_q345r_smaw(
        position=Position.PLATE_1G,
        impact_required=True,
        pwht=PWHTSpec(),  # 无PWHT，失效条件不满足
    )
    wps = make_wps_from_pqr(pqr)
    wps.positions = [Position.PLATE_3G]
    result = engine.compare(pqr, wps)
    vert_changes = [c for c in result.changes if "立焊" in c.factor_name]
    assert vert_changes
    assert vert_changes[0].action == Action.SUPPLEMENT_IMPACT


# ---------------------------------------------------------------------------
# 重要因素：预热温度大幅降低 / 取消PWHT
# ---------------------------------------------------------------------------

def test_preheat_decrease_essential(engine):
    pqr = make_pqr_q345r_smaw(preheat=150.0)
    wps = make_wps_from_pqr(pqr)
    wps.preheat_min = 50.0  # 降低超过50℃
    result = engine.compare(pqr, wps)
    assert result.needs_requalify


def test_pwht_removed_essential(engine):
    pqr = make_pqr_q345r_smaw(pwht=PWHTSpec(applied=True, pwht_type="消除应力"))
    wps = make_wps_from_pqr(pqr)
    wps.pwht = PWHTSpec(applied=False)
    result = engine.compare(pqr, wps)
    assert result.needs_requalify


# ---------------------------------------------------------------------------
# 次要因素：坡口形式变更 → 仅改WPS
# ---------------------------------------------------------------------------

def test_groove_change_nonessential(engine):
    pqr = make_pqr_q345r_smaw()
    wps = make_wps_from_pqr(pqr)
    wps.joints = [Joint(type=JointType.BUTT, groove=GrooveDesign(type="X"),
                        thickness=16.0)]
    result = engine.compare(pqr, wps)
    groove_changes = [c for c in result.changes if "坡口" in c.factor_name]
    assert groove_changes
    assert groove_changes[0].level == FactorLevel.NONESSENTIAL
    assert groove_changes[0].action == Action.REVISE_WPS
    assert not result.needs_requalify


# ---------------------------------------------------------------------------
# 修正回归：位置未覆盖不应让补加因素场景误判为"重新评定"
# ---------------------------------------------------------------------------

def test_vertical_position_verdict_not_masked_by_coverage(engine):
    """PQR 平焊 + WPS 立焊 + 有冲击要求 → 应判"补做冲击"，
    而非被覆盖校验误判为"超出评定范围需重新评定"。"""
    pqr = make_pqr_q345r_smaw(
        position=Position.PLATE_1G, impact_required=True
    )
    wps = make_wps_from_pqr(pqr)
    wps.positions = [Position.PLATE_3G]
    result = engine.compare(pqr, wps)
    # 厚度/管径数值范围仍合格
    assert result.hard_coverage_ok
    # 因素引擎正确判定为补加因素 → 补做冲击
    assert result.needs_supplement_impact
    assert not result.needs_requalify
    # 整体结论应为"补做冲击"，不含"重新评定"
    assert "补做冲击" in result.verdict_cn
    assert "重新评定" not in result.verdict_cn


def test_thickness_hard_failure_still_requalifies(engine):
    """厚度超限（硬失败）仍应判重新评定（修正不能误伤此场景）。"""
    pqr = make_pqr_q345r_smaw(thickness=16.0)
    wps = make_wps_from_pqr(pqr)
    wps.base_metals[0].thickness = 40.0  # 超 2t=32
    wps.deposited_thickness = 40.0
    result = engine.compare(pqr, wps)
    assert not result.hard_coverage_ok
    assert "重新评定" in result.verdict_cn


# ---------------------------------------------------------------------------
# 组合焊接方法：GTAW打底 + SMAW填充
# ---------------------------------------------------------------------------

def test_combined_process_detection():
    """组合焊：焊道显式指定不同方法时，all_processes 应去重收集全部。"""
    from weldai.domain.procedure import PassLayer, Procedure
    from weldai.domain.enums import ProcedureType

    p = Procedure(doc_no="WPS-C1", type=ProcedureType.WPS,
                  process=WeldingProcess.GTAW)
    p.passes = [
        PassLayer(sequence=1, process=WeldingProcess.GTAW),
        PassLayer(sequence=2, process=WeldingProcess.SMAW),
        PassLayer(sequence=3),  # None → 继承 procedure.process=GTAW
    ]
    assert [x.value for x in p.all_processes] == ["GTAW", "SMAW"]
    assert p.is_combined_process
    # 继承的焊道回退到 procedure.process
    assert p.passes[2].effective_process(p.process) == WeldingProcess.GTAW


def test_combined_process_pass_returned_when_pqr_single(engine):
    """WPS 用组合焊(GTAW+SMAW)，但 PQR 仅 SMAW 评定 → GTAW 无评定应判重新评定。"""
    pqr = make_pqr_q345r_smaw()  # 单 SMAW 评定
    wps = make_wps_from_pqr(pqr)
    # WPS 第一道改用 GTAW（组合焊），其余仍 SMAW
    wps.passes[0].process = WeldingProcess.GTAW
    result = engine.compare(pqr, wps)
    # GTAW 无对应PQR评定 → 重要因素变更 → 重新评定
    assert result.needs_requalify
    # 应报告"焊接方法"相关变更（factor_name 含"焊接方法"或描述含 GTAW）
    process_changes = [c for c in result.changes
                       if "焊接方法" in c.factor_name or "GTAW" in c.change_description]
    assert process_changes
