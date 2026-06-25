"""跨焊接方法因素校验单测（H1 修复守护 + L2 盲区覆盖）。

验证 factor_engine 对 SMAW/GTAW/SAW/GMAW 等方法都能正确检出因素变更，
而不仅是 SMAW（修复前非 SMAW 方法因 ID 硬编码而静默失效）。
"""
from __future__ import annotations

import copy
import pytest

from weldai.domain.enums import (
    CurrentType,
    JointType,
    Position,
    WeldingProcess,
)
from weldai.domain.joint import GrooveDesign, Joint
from weldai.engine import Action, FactorEngine
from weldai.standards import get_default_standard
from tests.conftest import make_pqr_q345r_smaw, make_wps_from_pqr


@pytest.fixture
def engine():
    return FactorEngine(get_default_standard())


def _make_pqr_for_process(process: WeldingProcess):
    """构造指定焊接方法的 PQR（基于 SMAW 模板替换 process）。"""
    pqr = make_pqr_q345r_smaw()
    pqr.process = process
    for p in pqr.passes:
        p.consumable = pqr.consumables[0] if pqr.consumables else None
    return pqr


# ---------------------------------------------------------------------------
# H1 核心回归：各方法的电源类型变更都能检出（修复前仅SMAW）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("process", [
    WeldingProcess.SMAW,
    WeldingProcess.GTAW,
    WeldingProcess.SAW,
    WeldingProcess.GMAW,
    WeldingProcess.PAW,
])
def test_current_type_change_detected_all_processes(engine, process):
    """★H1修复守护：各方法电源类型变更都应检出为重要因素→需重新评定。"""
    pqr = _make_pqr_for_process(process)
    wps = make_wps_from_pqr(pqr)
    for p in wps.passes:
        p.current_type = CurrentType.DCEN  # PQR 是 DCEP
    result = engine.compare(pqr, wps)
    power_changes = [c for c in result.changes if "电源" in c.factor_name]
    assert power_changes, f"{process.value} 电源类型变更未被检出（H1回归）"
    assert result.needs_requalify


@pytest.mark.parametrize("process", [
    WeldingProcess.SMAW,
    WeldingProcess.GTAW,
    WeldingProcess.SAW,
    WeldingProcess.GMAW,
])
def test_preheat_decrease_detected_all_processes(engine, process):
    """各方法预热温度大幅降低都应检出为重要因素。"""
    pqr = _make_pqr_for_process(process)
    pqr.preheat_min = 150.0
    wps = make_wps_from_pqr(pqr)
    wps.preheat_min = 50.0
    result = engine.compare(pqr, wps)
    assert result.needs_requalify
    assert any("预热" in c.factor_name for c in result.changes)


@pytest.mark.parametrize("process", [
    WeldingProcess.SMAW,
    WeldingProcess.GTAW,
    WeldingProcess.GMAW,
])
def test_groove_change_detected_all_processes(engine, process):
    """各方法坡口形式变更都应检出为次要因素。"""
    pqr = _make_pqr_for_process(process)
    wps = make_wps_from_pqr(pqr)
    wps.joints = [Joint(type=JointType.BUTT, groove=GrooveDesign(type="X"),
                        thickness=16.0)]
    result = engine.compare(pqr, wps)
    groove_changes = [c for c in result.changes if "坡口" in c.factor_name]
    assert groove_changes
    assert not result.needs_requalify  # 次要因素不重新评定


# ---------------------------------------------------------------------------
# 因素定义 category 完整性
# ---------------------------------------------------------------------------

class TestFactorCategories:
    def test_all_processes_have_current_type_category(self):
        """每个方法都应有 current_type 语义键的因素。"""
        std = get_default_standard()
        for proc in [WeldingProcess.SMAW, WeldingProcess.GTAW, WeldingProcess.SAW,
                     WeldingProcess.GMAW, WeldingProcess.PAW]:
            fdef = std.get_factor_by_category(proc, "current_type")
            assert fdef is not None, f"{proc.value} 缺 current_type 因素"

    def test_category_lookup_stable_across_methods(self):
        """category 查找返回的因素名应含'电源'（跨方法一致语义）。"""
        std = get_default_standard()
        for proc in [WeldingProcess.SMAW, WeldingProcess.GTAW, WeldingProcess.SAW]:
            fdef = std.get_factor_by_category(proc, "current_type")
            assert "电源" in fdef.name or "电流" in fdef.name


# ---------------------------------------------------------------------------
# M2 specimen_form 试件形式检查
# ---------------------------------------------------------------------------

class TestSpecimenFormCheck:
    def test_plate_qual_not_cover_pipe(self):
        """板对接资格不能覆盖管对接任务。"""
        from weldai.engine.welder_engine import _form_covers
        assert not _form_covers("板对接", "管对接")

    def test_pipe_qual_covers_nozzle(self):
        """管对接资格可覆盖管板。"""
        from weldai.engine.welder_engine import _form_covers
        assert _form_covers("管对接", "管板")

    def test_butt_qual_covers_fillet(self):
        """对接资格可覆盖角焊缝。"""
        from weldai.engine.welder_engine import _form_covers
        assert _form_covers("板对接", "板材角焊缝")

    def test_nozzle_not_cover_pipe(self):
        """管板资格不能覆盖管对接。"""
        from weldai.engine.welder_engine import _form_covers
        assert not _form_covers("管板", "管对接")
