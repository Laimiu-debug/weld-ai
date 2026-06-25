"""AI 辅助引擎单测：PQR→WPS 派生 + 参数推荐。"""
from __future__ import annotations

import pytest

from weldai.domain.enums import (
    CurrentType,
    Position,
    ProcedureType,
    WeldingProcess,
)
from weldai.engine import FactorEngine, ParameterAdvisor, WPSDeriver
from weldai.standards import get_default_standard

from .conftest import make_pqr_q345r_smaw


@pytest.fixture
def deriver() -> WPSDeriver:
    return WPSDeriver(get_default_standard())


@pytest.fixture
def advisor() -> ParameterAdvisor:
    return ParameterAdvisor(get_default_standard())


# ---------------------------------------------------------------------------
# PQR → WPS 派生
# ---------------------------------------------------------------------------

class TestWPSDerivation:
    def test_derived_wps_type_and_pqr_link(self, deriver):
        """派生的 WPS 类型应为 WPS，并关联源 PQR。"""
        pqr = make_pqr_q345r_smaw()
        report = deriver.derive(pqr)
        assert report.wps.type == ProcedureType.WPS
        assert report.wps.supporting_pqr_no == pqr.doc_no

    def test_derived_wps_passes_verification(self, deriver):
        """★核心保证：派生的 WPS 必须能通过 factor_engine 校验（不需重新评定）。"""
        pqr = make_pqr_q345r_smaw()
        report = deriver.derive(pqr)
        engine = FactorEngine(get_default_standard())
        result = engine.compare(pqr, report.wps)
        assert not result.needs_requalify, (
            "派生的 WPS 不应触发重新评定。" +
            "; ".join(c.factor_name for c in result.changes
                      if c.action.value == "requalify")
        )

    def test_derived_thickness_within_coverage(self, deriver):
        """派生 WPS 的厚度应落在 PQR 覆盖范围内。"""
        pqr = make_pqr_q345r_smaw(thickness=16.0)  # 覆盖[8,32]
        report = deriver.derive(pqr, target_thickness_ratio=0.5)
        wps_t = report.wps.base_metals[0].thickness
        assert 8 <= wps_t <= 32

    def test_derive_with_valid_position(self, deriver):
        """目标位置在 PQR 覆盖内时，WPS 应采用目标位置。"""
        # PQR 4G(仰焊)覆盖平/横/立/仰
        pqr = make_pqr_q345r_smaw(position=Position.PLATE_4G)
        report = deriver.derive(
            pqr, target_positions=[Position.PLATE_1G]  # 平焊，在4G覆盖内
        )
        assert Position.PLATE_1G in report.wps.positions
        assert not any("超出 PQR 覆盖范围" in w for w in report.warnings)

    def test_derive_with_invalid_position_warns(self, deriver):
        """目标位置超出 PQR 覆盖时，应告警并回退到 PQR 位置。"""
        pqr = make_pqr_q345r_smaw(position=Position.PLATE_1G)  # 平焊仅覆盖1G
        report = deriver.derive(
            pqr, target_positions=[Position.PLATE_4G]  # 仰焊，超出
        )
        assert any("超出 PQR 覆盖范围" in w for w in report.warnings)

    def test_derivation_report_has_explanations(self, deriver):
        """派生报告应包含可解释的依据说明（非黑盒）。"""
        pqr = make_pqr_q345r_smaw()
        report = deriver.derive(pqr)
        assert len(report.notes) >= 3
        assert any("母材厚度" in n for n in report.notes)
        assert any("电源类型" in n for n in report.notes)


# ---------------------------------------------------------------------------
# 参数智能推荐
# ---------------------------------------------------------------------------

class TestParameterRecommendation:
    def test_recommend_returns_consumables(self, advisor):
        """推荐应返回适用母材的焊材列表。"""
        rec = advisor.recommend("Q345R", WeldingProcess.SMAW)
        # Q345R(Fe-1-2) 适用 J507
        brands = [c.brand for c in rec.consumables]
        assert "J507" in brands

    def test_recommend_returns_params(self, advisor):
        """推荐应返回经验参数（电流/电压/直径）。"""
        rec = advisor.recommend("Q345R", WeldingProcess.SMAW, thickness=12.0)
        assert rec.recommended_diameter > 0
        assert rec.current_range[1] > rec.current_range[0] > 0
        assert rec.voltage_range[1] > rec.voltage_range[0] > 0

    def test_thickness_affects_diameter(self, advisor):
        """薄板应推荐较小直径，厚板较大直径。"""
        thin = advisor.recommend("Q345R", WeldingProcess.SMAW, thickness=3.0)
        thick = advisor.recommend("Q345R", WeldingProcess.SMAW, thickness=30.0)
        assert thin.recommended_diameter <= thick.recommended_diameter

    def test_recommend_unknown_material(self, advisor):
        """未知母材应告警但不崩溃。"""
        rec = advisor.recommend("UNKNOWN-STEEL", WeldingProcess.SMAW)
        assert any("不在标准库" in n for n in rec.notes)

    def test_recommend_gmaw_has_gas(self, advisor):
        """GMAW 推荐应包含保护气体信息。"""
        rec = advisor.recommend("Q245R", WeldingProcess.GMAW)
        assert rec.gas_type
        assert rec.gas_flow_range[1] > rec.gas_flow_range[0]

    def test_stainless_recommends_stainless_consumable(self, advisor):
        """不锈钢母材应推荐不锈钢焊材（而非碳钢焊材）。"""
        rec = advisor.recommend("06Cr19Ni10", WeldingProcess.SMAW)  # 304
        brands = [c.brand for c in rec.consumables]
        assert "A102" in brands  # 304 不锈钢焊条
        assert "J507" not in brands  # 不应推荐碳钢焊条
