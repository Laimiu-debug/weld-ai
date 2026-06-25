"""PQR 匹配筛选器单测。

核心场景：给定焊缝需求（母材+厚度+位置），从多个 PQR 中筛出能覆盖它的。
"""
from __future__ import annotations

import pytest

from weldai.domain.enums import (
    CurrentType,
    JointType,
    Mechanization,
    Position,
    ProcedureType,
    WeldingProcess,
)
from weldai.domain.base_metal import BaseMetalThicknessPair
from weldai.domain.consumable import Consumable, ConsumableType
from weldai.domain.joint import GrooveDesign, Joint
from weldai.domain.procedure import PassLayer, Procedure, PWHTSpec
from weldai.engine import PQRMatcher, WeldRequirement
from weldai.persistence import ProcedureRepository, get_session, init_db
from weldai.standards import get_default_standard


def _make_pqr(doc_no, grade, category, group, thickness, process=WeldingProcess.SMAW,
              position=Position.PLATE_1G, outer_diameter=None):
    """构造一个 PQR（指定母材类组+厚度）。"""
    from weldai.domain.base_metal import BaseMetal
    from weldai.domain.enums import MaterialGroup
    metal = BaseMetal(
        grade=grade, group=MaterialGroup("Fe", category, group),
        standard="GB/T 713", yield_strength=345, tensile_strength=510,
    )
    cons = Consumable(brand="J507", model="E5015", type=ConsumableType.ELECTRODE,
                      classification_slot="表2-E50", standard="GB/T 5118", diameter=3.2)
    return Procedure(
        doc_no=doc_no, type=ProcedureType.PQR, process=process,
        mechanization=Mechanization.MANUAL,
        base_metals=[BaseMetalThicknessPair(metal, thickness)],
        consumables=[cons],
        joints=[Joint(type=JointType.BUTT, groove=GrooveDesign(type="V"),
                      thickness=thickness, outer_diameter=outer_diameter)],
        passes=[PassLayer(sequence=1, layer_role="打底", consumable=cons,
                          diameter=3.2, current_type=CurrentType.DCEP,
                          current_min=100, current_max=130)],
        positions=[position], pwht=PWHTSpec(), impact_required=False,
        deposited_thickness=thickness, standard_version="NBT47014-2023",
    )


@pytest.fixture
def matcher():
    """构造含多个 PQR 的测试库。"""
    init_db(":memory:")
    repo = ProcedureRepository(get_session(), get_default_standard())
    # PQR-A: Q345R(Fe-1-2) / 16mm / SMAW / 平焊 → 覆盖Fe-1-1&Fe-1-2, [8,32]mm, 1G
    repo.save(_make_pqr("PQR-A", "Q345R", "Fe-1", "Fe-1-2", 16.0))
    # PQR-B: Q245R(Fe-1-1) / 6mm / SMAW / 平焊 → 覆盖Fe-1-1, [1.5,12]mm, 1G
    repo.save(_make_pqr("PQR-B", "Q245R", "Fe-1", "Fe-1-1", 6.0))
    # PQR-C: Q345R / 16mm / GTAW / 平焊 → 不同方法
    repo.save(_make_pqr("PQR-C", "Q345R", "Fe-1", "Fe-1-2", 16.0,
                        process=WeldingProcess.GTAW))
    # PQR-D: Q345R / 16mm / SMAW / 仰焊(4G) → 覆盖全板位置
    repo.save(_make_pqr("PQR-D", "Q345R", "Fe-1", "Fe-1-2", 16.0,
                        position=Position.PLATE_4G))
    return PQRMatcher(repo, get_default_standard())


# ---------------------------------------------------------------------------
# 核心匹配场景
# ---------------------------------------------------------------------------

class TestPQRMatch:
    def test_fully_matched_pqr(self, matcher):
        """Q345R/16mm/SMAW/平焊 应被 PQR-A 完全覆盖。"""
        req = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q345R",
            thickness=16.0, position=Position.PLATE_1G,
        )
        matched = matcher.find_matched(req)
        assert any(p.doc_no == "PQR-A" for p in matched)

    def test_high_group_covers_low(self, matcher):
        """PQR-A(Fe-1-2) 评定，Q245R(Fe-1-1)焊缝应能被覆盖（高覆盖低）。"""
        req = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q245R",
            thickness=10.0, position=Position.PLATE_1G,
        )
        matched = matcher.find_matched(req)
        assert "PQR-A" in [p.doc_no for p in matched]

    def test_low_group_not_cover_high(self, matcher):
        """PQR-B(Fe-1-1) 评定，不能覆盖 Q345R(Fe-1-2)。"""
        req = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q345R",
            thickness=10.0, position=Position.PLATE_1G,
        )
        results = {r.pqr_no: r for r in matcher.match(req)}
        # PQR-B 不能完全覆盖（母材类组维度不满足）
        assert not results["PQR-B"].fully_matched
        b_group_dim = next(d for d in results["PQR-B"].dimensions if d.name == "母材类组")
        assert not b_group_dim.passed

    def test_thickness_outside_coverage(self, matcher):
        """PQR-B 覆盖[1.5,12]mm，40mm焊缝应不被覆盖。"""
        req = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q245R",
            thickness=40.0, position=Position.PLATE_1G,
        )
        results = {r.pqr_no: r for r in matcher.match(req)}
        assert not results["PQR-B"].fully_matched
        b_t_dim = next(d for d in results["PQR-B"].dimensions if d.name == "母材厚度")
        assert not b_t_dim.passed

    def test_wrong_process_not_matched(self, matcher):
        """SMAW 焊缝不应被 GTAW PQR(PQR-C) 覆盖。"""
        req = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q345R",
            thickness=16.0, position=Position.PLATE_1G,
        )
        results = {r.pqr_no: r for r in matcher.match(req)}
        assert not results["PQR-C"].fully_matched
        c_method_dim = next(d for d in results["PQR-C"].dimensions if d.name == "焊接方法")
        assert not c_method_dim.passed

    def test_position_coverage(self, matcher):
        """PQR-D(4G仰焊) 应覆盖平焊(1G)需求；PQR-A(1G)不覆盖仰焊需求。"""
        # 平焊需求
        req_flat = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q345R",
            thickness=16.0, position=Position.PLATE_1G,
        )
        matched_flat = matcher.find_matched(req_flat)
        assert "PQR-D" in [p.doc_no for p in matched_flat]  # 4G覆盖1G

        # 仰焊需求
        req_overhead = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q345R",
            thickness=16.0, position=Position.PLATE_4G,
        )
        matched_oh = matcher.find_matched(req_overhead)
        assert "PQR-D" in [p.doc_no for p in matched_oh]
        assert "PQR-A" not in [p.doc_no for p in matched_oh]  # 1G不覆盖4G


# ---------------------------------------------------------------------------
# 结果排序与汇总
# ---------------------------------------------------------------------------

class TestMatchResult:
    def test_results_sorted_matched_first(self, matcher):
        """完全匹配的 PQR 应排在前面。"""
        req = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q345R",
            thickness=16.0, position=Position.PLATE_1G,
        )
        results = matcher.match(req)
        # 第一个应该是完全匹配的（PQR-A 或 PQR-D）
        assert results[0].fully_matched

    def test_verdict_text(self, matcher):
        """未完全匹配的应有 verdict 说明。"""
        req = WeldRequirement(
            process=WeldingProcess.GMAW, material_grade="Q345R",
            thickness=16.0, position=Position.PLATE_1G,
        )
        results = matcher.match(req)
        # 所有现有 PQR 都是 SMAW/GTAW，GMAW 需求应都不匹配
        for r in results:
            assert not r.fully_matched
            assert "不满足" in r.verdict_cn or "项" in r.verdict_cn

    def test_dimension_detail_is_explanatory(self, matcher):
        """维度详情应可解释（含 PQR 覆盖范围 vs 需求）。"""
        req = WeldRequirement(
            process=WeldingProcess.SMAW, material_grade="Q345R",
            thickness=16.0, position=Position.PLATE_1G,
        )
        results = matcher.match(req)
        for r in results:
            for d in r.dimensions:
                assert d.name
                assert d.detail
