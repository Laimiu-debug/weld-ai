"""阶段2 数据完整性单测：守护母材分类核实与新增因素表加载。"""
from __future__ import annotations

import pytest

from weldai.domain.enums import FactorLevel, WeldingProcess
from weldai.standards import get_default_standard

STD = get_default_standard()


# ---------------------------------------------------------------------------
# 不锈钢类组归属核实（阶段2核心修正）
# ---------------------------------------------------------------------------

class TestStainlessSteelClassification:
    """验证不锈钢分类：Fe-6马氏体/Fe-7铁素体(分2组)/Fe-8奥氏体(分8-1/8-2)。"""

    @pytest.mark.parametrize("grade,category,group", [
        # Fe-6 马氏体不锈钢（不分组）
        ("06Cr13", "Fe-6", "Fe-6"),
        ("12Cr13", "Fe-6", "Fe-6"),
        ("20Cr13", "Fe-6", "Fe-6"),
        ("14Cr17Ni2", "Fe-6", "Fe-6"),
        # Fe-7 铁素体不锈钢（分7-1/7-2）
        ("06Cr13Al", "Fe-7", "Fe-7-1"),
        ("10Cr17", "Fe-7", "Fe-7-2"),
        # Fe-8 奥氏体不含Mo → Fe-8-1
        ("06Cr19Ni10", "Fe-8", "Fe-8-1"),   # 304
        ("022Cr19Ni10", "Fe-8", "Fe-8-1"),  # 304L
        ("06Cr18Ni11Ti", "Fe-8", "Fe-8-1"),  # 321
        ("06Cr18Ni11Nb", "Fe-8", "Fe-8-1"),  # 347
        # Fe-8 奥氏体含Mo → Fe-8-2
        ("06Cr17Ni12Mo2", "Fe-8", "Fe-8-2"),   # 316
        ("022Cr17Ni12Mo2", "Fe-8", "Fe-8-2"),  # 316L
        ("06Cr19Ni13Mo3", "Fe-8", "Fe-8-2"),   # 317
    ])
    def test_stainless_classification(self, grade, category, group):
        metal = STD.get_base_metal(grade)
        assert metal is not None, f"{grade} 不在母材库"
        assert metal.category == category, f"{grade} 类别号应为 {category}"
        assert metal.group.group == group, f"{grade} 组别号应为 {group}"

    def test_304_vs_316_different_subgroup(self):
        """304(不含Mo,Fe-8-1) 与 316(含Mo,Fe-8-2) 应在不同组别 → 互焊需重新评定。"""
        m304 = STD.get_base_metal("06Cr19Ni10")
        m316 = STD.get_base_metal("06Cr17Ni12Mo2")
        assert m304.group.group != m316.group.group
        # 跨组别不覆盖
        assert not STD.base_metal_covers(m316.group.group, m304.group.group)

    def test_fe8_1_high_not_cover_low(self):
        """Fe-8 不存在 8-2 覆盖 8-1 的高覆盖低规则（不同组别，互不覆盖）。"""
        assert not STD.base_metal_covers("Fe-8-2", "Fe-8-1")


# ---------------------------------------------------------------------------
# Fe-5 是 Cr-Mo 耐热钢（非不锈钢）核实
# ---------------------------------------------------------------------------

class TestCrMoClassification:
    def test_12cr2mo1r_is_crmo_not_stainless(self):
        """12Cr2Mo1R 应归 Cr-Mo 耐热钢(Fe-5A)，不在不锈钢 Fe-6/7/8。"""
        metal = STD.get_base_metal("12Cr2Mo1R")
        assert metal is not None
        assert metal.group.family == "Fe"
        assert metal.category not in ("Fe-6", "Fe-7", "Fe-8"), \
            "Cr-Mo耐热钢不应归入不锈钢类"


# ---------------------------------------------------------------------------
# 新增焊接方法因素表加载完整性
# ---------------------------------------------------------------------------

class TestNewProcessFactors:
    """验证 GMAW/PAW/EGW/EBW 因素表已加载且结构完整。"""

    @pytest.mark.parametrize("process,expected_count_min", [
        (WeldingProcess.GMAW, 10),  # 10重要+5补加+5次要
        (WeldingProcess.PAW, 10),
        (WeldingProcess.EGW, 7),
        (WeldingProcess.EBW, 8),
    ])
    def test_factors_loaded(self, process, expected_count_min):
        factors = STD.get_factors(process)
        assert len(factors) >= expected_count_min, (
            f"{process.value} 因素数 {len(factors)} 少于预期 {expected_count_min}"
        )

    def test_gmaw_has_consumable_factor(self):
        """GMAW 应有焊丝类别(F号/A号)变更这一重要因素。"""
        factors = {f.factor_id: f for f in STD.get_factors(WeldingProcess.GMAW)}
        assert "GMAW-E04" in factors
        assert factors["GMAW-E04"].level == FactorLevel.ESSENTIAL

    def test_gmaw_has_transfer_mode_supplemental(self):
        """GMAW 熔滴过渡方式变更应为补加因素。"""
        factors = {f.factor_id: f for f in STD.get_factors(WeldingProcess.GMAW)}
        assert "GMAW-S05" in factors
        assert factors["GMAW-S05"].level == FactorLevel.SUPPLEMENTAL

    def test_paw_has_keyhole_mode_essential(self):
        """PAW 小孔型↔熔透型切换应为重要因素。"""
        factors = {f.factor_id: f for f in STD.get_factors(WeldingProcess.PAW)}
        assert "PAW-E07" in factors
        assert factors["PAW-E07"].level == FactorLevel.ESSENTIAL

    def test_egw_groove_is_supplemental(self):
        """★EGW 坡口形式=补加因素（2023版新增，多来源确认）。"""
        factors = {f.factor_id: f for f in STD.get_factors(WeldingProcess.EGW)}
        assert "EGW-S01" in factors
        assert factors["EGW-S01"].level == FactorLevel.SUPPLEMENTAL

    def test_ebw_has_beam_params_essential(self):
        """EBW 加速电压/束流/真空度应为核心重要因素。"""
        factors = {f.factor_id: f for f in STD.get_factors(WeldingProcess.EBW)}
        for fid in ("EBW-E02", "EBW-E03", "EBW-E05"):
            assert fid in factors
            assert factors[fid].level == FactorLevel.ESSENTIAL


# ---------------------------------------------------------------------------
# 所有焊接方法电源类型均为重要因素（2023版统一升级）
# ---------------------------------------------------------------------------

class TestPowerSourceUpgrade:
    """2023版关键修订：电源类型（电流种类/极性）全焊接方法升级为重要因素。"""

    @pytest.mark.parametrize("process", [
        WeldingProcess.SMAW, WeldingProcess.GTAW, WeldingProcess.SAW,
        WeldingProcess.GMAW, WeldingProcess.PAW, WeldingProcess.EGW,
    ])
    def test_power_source_factor_exists_and_essential(self, process):
        """每种焊接方法都应有一个电源类型相关的重要因素。"""
        factors = STD.get_factors(process)
        power_factors = [
            f for f in factors
            if "电源类型" in f.name or "电流种类" in f.name
        ]
        assert power_factors, f"{process.value} 缺少电源类型因素"
        # 至少有一个为重要因素
        essential_power = [
            f for f in power_factors if f.level == FactorLevel.ESSENTIAL
        ]
        assert essential_power, (
            f"{process.value} 电源类型应至少有一条为重要因素(2023版升级)"
        )


# ---------------------------------------------------------------------------
# 焊材分类库（表2/3/4）
# ---------------------------------------------------------------------------

class TestConsumableLibrary:
    """验证焊材牌号↔型号↔分类栏位 录入正确。"""

    @pytest.mark.parametrize("brand,model,slot", [
        # 焊条
        ("J422", "E4303", "表2-E43"),
        ("J507", "E5015", "表2-E50"),
        ("A102", "E308-16", "表2-E308"),
        ("A022", "E316L-16", "表2-E316L"),
        # 焊丝
        ("ER50-6", "ER50-6", "表3-ER50"),
        ("ER308L", "ER308L", "表3-ER308L"),
        # 埋弧焊焊丝
        ("H08MnA", "H08MnA", "表4-H08MnA"),
    ])
    def test_consumable_lookup(self, brand, model, slot):
        cons = STD.get_consumable(brand)
        assert cons is not None, f"{brand} 不在焊材库"
        assert cons.model == model
        assert cons.classification_slot == slot

    def test_j507_vs_j422_cross_slot(self):
        """J507(表2-E50) 与 J422(表2-E43) 分类栏位不同 → 跨栏变更。"""
        j507 = STD.get_consumable("J507")
        j422 = STD.get_consumable("J422")
        assert STD.consumable_slot_changed(j507.classification_slot,
                                            j422.classification_slot)

    def test_a102_vs_a022_cross_slot(self):
        """A102(304,表2-E308) 与 A022(316L,表2-E316L) 跨栏 → 重要因素。"""
        a102 = STD.get_consumable("A102")
        a022 = STD.get_consumable("A022")
        assert STD.consumable_slot_changed(a102.classification_slot,
                                            a022.classification_slot)

    def test_consumables_for_fe1_2_group(self):
        """适用 Fe-1-2 的焊材应含 J507/H08MnA。"""
        cons = STD.consumables_for_group("Fe-1-2")
        brands = {c.brand for c in cons}
        assert "J507" in brands
        assert "H08MnA" in brands

    def test_consumables_for_fe8_1_vs_fe8_2_differ(self):
        """Fe-8-1(不含Mo)焊材 与 Fe-8-2(含Mo)焊材 应不同。"""
        c81 = {c.brand for c in STD.consumables_for_group("Fe-8-1")}
        c82 = {c.brand for c in STD.consumables_for_group("Fe-8-2")}
        assert "A102" in c81   # 304 不含Mo
        assert "A022" in c82   # 316L 含Mo
        assert "A102" not in c82
        assert "A022" not in c81

    def test_buried_arc_combo_model_parsed(self):
        """埋弧焊焊丝-焊剂组合型号格式正确。"""
        combo = STD.get_consumable("F48A2-H08MnA")
        assert combo is not None
        assert combo.type.value == "combo"
        assert "F48A2" in combo.model  # 抗拉≥480/焊态/冲击-20℃
