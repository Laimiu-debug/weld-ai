"""阶段2-补强 单测：守护深度核实的母材归属结论。"""
from __future__ import annotations

import pytest

from weldai.standards import get_default_standard

STD = get_default_standard()


class TestDuplexStainless:
    """双相不锈钢 = Fe-10H（已确认独立类号，不归Fe-8）。"""

    @pytest.mark.parametrize("grade", [
        "022Cr22Ni5Mo3N",  # S31803
        "022Cr23Ni5Mo3N",  # S32205/2205
        "022Cr25Ni7Mo4N",  # S32750/2507
    ])
    def test_duplex_is_fe10h(self, grade):
        metal = STD.get_base_metal(grade)
        assert metal is not None, f"{grade} 不在库"
        assert metal.category == "Fe-10H"
        assert metal.group.group == "Fe-10H"

    def test_duplex_not_in_fe8(self):
        """双相钢虽含Mo但不归Fe-8-2（关键纠错点）。"""
        m = STD.get_base_metal("022Cr23Ni5Mo3N")
        assert m.category != "Fe-8"
        assert m.group.group != "Fe-8-2"

    def test_duplex_not_covered_by_fe8(self):
        """316(Fe-8-2) 评定不能覆盖双相钢(Fe-10H) → 跨类需重新评定。"""
        assert not STD.base_metal_covers("Fe-8-2", "Fe-10H")


class TestPrecipitationHardening:
    """沉淀硬化不锈钢：17-4PH→Fe-6(马氏体型)，17-7PH→Fe-7(半奥氏体型)。"""

    def test_17_4ph_in_fe6(self):
        m = STD.get_base_metal("05Cr17Ni4Cu4Nb")
        assert m is not None
        assert m.category == "Fe-6"

    def test_17_7ph_in_fe7(self):
        m = STD.get_base_metal("07Cr17Ni7Al")
        assert m is not None
        assert m.category == "Fe-7"

    def test_17_4ph_and_17_7ph_different_category(self):
        """17-4PH与17-7PH按基体组织分属不同类别，互焊需重新评定。"""
        a = STD.get_base_metal("05Cr17Ni4Cu4Nb")
        b = STD.get_base_metal("07Cr17Ni7Al")
        assert a.category != b.category


class TestCrMoSteel:
    """Cr-Mo耐热钢以2%Cr为界：Fe-4(Cr<2%) / Fe-5(Cr≥2%)。"""

    def test_15crmo_in_fe4_1(self):
        """15CrMoR(1Cr-0.5Mo) 归 Fe-4-1（Cr<2%）。"""
        m = STD.get_base_metal("15CrMoR")
        assert m.category == "Fe-4"
        assert m.group.group == "Fe-4-1"

    def test_12cr1movg_in_fe4_2(self):
        """12Cr1MoVG(含V) 归 Fe-4-2，与无V的15CrMoR分组不同。"""
        m = STD.get_base_metal("12Cr1MoVG")
        assert m.category == "Fe-4"
        assert m.group.group == "Fe-4-2"

    def test_12cr2mo1r_in_fe5a(self):
        """12Cr2Mo1R(2.25Cr-1Mo) 归 Fe-5A（Cr≥2%）。"""
        m = STD.get_base_metal("12Cr2Mo1R")
        assert m.category == "Fe-5"
        assert m.group.group == "Fe-5A"

    def test_fe4_and_fe5_different_category(self):
        """Fe-4(Cr<2%) 与 Fe-5(Cr≥2%) 跨类需重新评定。"""
        assert not STD.base_metal_covers("Fe-4-1", "Fe-5A")

    def test_p91_in_fe5b_2(self):
        """P91(9Cr-1Mo-V-Nb) 归 Fe-5B-2。"""
        m = STD.get_base_metal("10Cr9Mo1VNbN")
        assert m.category == "Fe-5"
        assert m.group.group == "Fe-5B-2"

    def test_1cr5mo_in_fe5b_1(self):
        """1Cr5Mo(5Cr-0.5Mo) 归 Fe-5B-1。"""
        m = STD.get_base_metal("1Cr5Mo")
        assert m.category == "Fe-5"
        assert m.group.group == "Fe-5B-1"

    def test_fe5b_1_and_5b_2_parallel_not_cover(self):
        """★Fe-5B-1(1Cr5Mo) 与 Fe-5B-2(P91) 虽同5B但并列，不互相覆盖。"""
        assert not STD.base_metal_covers("Fe-5B-1", "Fe-5B-2")
        assert not STD.base_metal_covers("Fe-5B-2", "Fe-5B-1")


class TestEBWFactorsIntegrity:
    """EBW电子束焊因素表完整性（核心参数均为重要因素）。"""

    def test_ebw_core_params_essential(self):
        """加速电压/束流/焊接速度/真空度 均应为核心重要因素。"""
        from weldai.domain.enums import FactorLevel, WeldingProcess

        factors = {f.factor_id: f for f in STD.get_factors(WeldingProcess.EBW)}
        for fid in ("EBW-E02", "EBW-E03", "EBW-E04", "EBW-E05"):
            assert fid in factors, f"缺 {fid}"
            assert factors[fid].level == FactorLevel.ESSENTIAL
