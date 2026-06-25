"""焊工引擎与领域单测：守护 TSG Z6002 覆盖规则修正与预警逻辑。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from weldai.domain.enums import Position, WeldingProcess
from weldai.domain.welder import Welder, WelderQualification
from weldai.engine.welder_engine import (
    WeldTask,
    WelderEngine,
    _diameter_covers,
    _position_covers,
    _thickness_covers,
)


# ---------------------------------------------------------------------------
# 厚度覆盖修正（阶段0 错误：下限3；正确：下限0）
# ---------------------------------------------------------------------------

class TestThicknessCoverageFix:
    @pytest.mark.parametrize("qualified_t, required_t, expect", [
        (12.0, 50.0, True),    # t≥12 → 0~不限
        (12.0, 3.0, True),     # t≥12 → 含薄板
        (12.0, 200.0, True),   # t≥12 → 不限上限
        (6.0, 12.0, True),     # 3<t<12 → 0~2t=12
        (6.0, 13.0, False),    # 超 2t=12
        (6.0, 1.0, True),      # 3<t<12 → 下限0，含薄板（阶段0错误会判False）
        (3.0, 6.0, True),      # t≤3 → 0~2t=6
        (3.0, 7.0, False),     # 超 2t=6
    ])
    def test_thickness_covers(self, qualified_t, required_t, expect):
        assert _thickness_covers(qualified_t, required_t) is expect

    def test_thickness_floor_is_zero_not_three(self):
        """★回归守护：t=8 覆盖 t=1（下限0），阶段0错误下限3会漏判。"""
        assert _thickness_covers(8.0, 1.0) is True
        assert _thickness_covers(8.0, 0.5) is True


# ---------------------------------------------------------------------------
# 管径覆盖修正（阶段0 错误：D<25覆盖不限；正确：D<25仅覆盖自身）
# ---------------------------------------------------------------------------

class TestDiameterCoverageFix:
    @pytest.mark.parametrize("qualified_d, required_d, expect", [
        (20.0, 20.0, True),    # D<25 → 仅覆盖自身
        (20.0, 30.0, False),   # D<25 → 不向上覆盖（阶段0错误会判True）
        (50.0, 100.0, True),   # 25≤D<76 → 25~不限
        (50.0, 20.0, False),   # 25≤D<76 → 下限25
        (100.0, 80.0, True),   # D≥76 → 76~不限
        (100.0, 50.0, False),  # D≥76 → 下限76
    ])
    def test_diameter_covers(self, qualified_d, required_d, expect):
        assert _diameter_covers(qualified_d, required_d) is expect

    def test_plate_qual_covers_pipe_over_76(self):
        """板材试件合格（无管径）可覆盖 D≥76 管材。"""
        assert _diameter_covers(None, 100.0) is True
        assert _diameter_covers(None, 50.0) is False


# ---------------------------------------------------------------------------
# 位置覆盖修正（5G不覆盖2G；6G全覆盖）
# ---------------------------------------------------------------------------

class TestPositionCoverageFix:
    @pytest.mark.parametrize("qualified, required, expect", [
        (Position.PIPE_6G, Position.PLATE_1G, True),    # 6G 覆盖平焊
        (Position.PIPE_6G, Position.PLATE_2G, True),    # 6G 覆盖横焊
        (Position.PIPE_6G, Position.PLATE_4G, True),    # 6G 覆盖仰焊
        (Position.PIPE_5G, Position.PLATE_2G, False),   # ★5G 不覆盖 2G
        (Position.PIPE_5G, Position.PLATE_3G, True),    # 5G 覆盖立焊
        (Position.PLATE_4G, Position.PLATE_1G, True),   # 仰焊覆盖平焊
        (Position.PLATE_1G, Position.PLATE_4G, False),  # 平焊不覆盖仰焊
    ])
    def test_position_covers(self, qualified, required, expect):
        assert _position_covers(qualified, required) is expect

    @pytest.mark.parametrize("qualified, required, expect", [
        # 管板 F 系列：6FG 覆盖全管板位置
        (Position.TUBE_6F, Position.TUBE_5F, True),
        (Position.TUBE_6F, Position.TUBE_2FR, True),
        (Position.TUBE_6F, Position.TUBE_1F, True),
        # 低级不覆盖高级
        (Position.TUBE_2F, Position.TUBE_6F, False),
        (Position.TUBE_5F, Position.TUBE_6F, False),
    ])
    def test_tube_sheet_position_covers(self, qualified, required, expect):
        """管板（管-管板）F 系列位置覆盖：6FG 覆盖全管板位置。"""
        assert _position_covers(qualified, required) is expect


# ---------------------------------------------------------------------------
# 项目代号生成
# ---------------------------------------------------------------------------

class TestProjectCode:
    def test_basic_project_code(self):
        q = WelderQualification(
            process=WeldingProcess.SMAW,
            material_category="Fe-1",
            specimen_form="板对接",
            deposited_thickness=12.0,
            position=Position.PLATE_1G,
        )
        code = q.project_code
        assert "SMAW" in code
        assert "Fe-1" in code
        assert "板对接" in code
        assert "12" in code
        assert "1G" in code

    def test_backing_mark_in_code(self):
        q = WelderQualification(
            process=WeldingProcess.GTAW,
            material_category="Fe-8",
            specimen_form="管对接",
            deposited_thickness=6.0,
            outer_diameter=57.0,
            position=Position.PIPE_6G,
            has_backing=True,
            process_factor="Fef3J",
        )
        code = q.project_code
        assert "6G(管)(K)" in code   # 带衬垫标记（管对接位置带"(管)"后缀）
        assert "6/57" in code    # 厚度/管径
        assert "Fef3J" in code


# ---------------------------------------------------------------------------
# 复审预警
# ---------------------------------------------------------------------------

class TestWelderAlerts:
    def _make_welder(self, expire_offset_days=0, last_work=None, birth=None):
        expire = date.today() + timedelta(days=expire_offset_days)
        q = WelderQualification(
            process=WeldingProcess.SMAW,
            material_category="Fe-1",
            specimen_form="板对接",
            deposited_thickness=12.0,
            position=Position.PLATE_1G,
            expire_date=expire,
        )
        return Welder(
            stamp_no="T1", name="测试", birth_date=birth,
            last_work_date=last_work, qualifications=[q],
        )

    def test_expiring_alert(self):
        """资格30天后到期（6个月内）→ 应有到期预警。"""
        w = self._make_welder(expire_offset_days=30)
        alerts = w.alerts()
        assert any("到期" in a for a in alerts)

    def test_expired_alert(self):
        """资格已过期 → 应有已过期预警。"""
        w = self._make_welder(expire_offset_days=-10)
        alerts = w.alerts()
        assert any("已过期" in a for a in alerts)

    def test_no_alert_when_valid(self):
        """资格2年后到期 → 无到期预警。"""
        w = self._make_welder(expire_offset_days=730)
        assert w.alerts() == []

    def test_interrupt_alert(self):
        """中断超6个月 → 应有中断预警。"""
        old = date.today() - timedelta(days=200)  # 超6个月
        w = self._make_welder(expire_offset_days=730, last_work=old)
        alerts = w.alerts()
        assert any("中断" in a for a in alerts)

    def test_no_interrupt_alert_recent_work(self):
        """最近1个月施焊 → 无中断预警。"""
        recent = date.today() - timedelta(days=30)
        w = self._make_welder(expire_offset_days=730, last_work=recent)
        assert not any("中断" in a for a in w.alerts())

    def test_age_alert(self):
        """年龄达65 → 应有年龄预警。"""
        old_enough = date.today().replace(year=date.today().year - 66)
        w = self._make_welder(expire_offset_days=730, birth=old_enough)
        alerts = w.alerts()
        assert any("年龄" in a for a in alerts)


# ---------------------------------------------------------------------------
# 焊工资格覆盖查询（WelderEngine.can_weld）
# ---------------------------------------------------------------------------

class TestWelderEngine:
    def _make_welder(self, **kwargs):
        defaults = dict(
            process=WeldingProcess.SMAW,
            material_category="Fe-1",
            specimen_form="板对接",
            deposited_thickness=12.0,
            position=Position.PIPE_6G,  # 6G 覆盖全位置
            expire_date=date.today() + timedelta(days=365),
        )
        defaults.update(kwargs)
        q = WelderQualification(**defaults)
        return Welder(stamp_no="W1", name="焊工甲", qualifications=[q])

    def test_can_weld_matching_task(self):
        w = self._make_welder()
        engine = WelderEngine()
        task = WeldTask(
            process=WeldingProcess.SMAW,
            material_category="Fe-1",
            thickness=10.0,
            position=Position.PLATE_1G,  # 6G覆盖平焊
        )
        assert engine.can_weld(w, task)

    def test_cannot_weld_wrong_process(self):
        w = self._make_welder()
        task = WeldTask(
            process=WeldingProcess.GTAW,  # 方法不符
            material_category="Fe-1",
            thickness=10.0,
            position=Position.PLATE_1G,
        )
        assert not engine_can_weld(w, task)

    def test_cannot_weld_position_not_covered(self):
        """1G合格不能覆盖4G（仰焊）。"""
        w = self._make_welder(position=Position.PLATE_1G)
        engine = WelderEngine()
        task = WeldTask(
            process=WeldingProcess.SMAW,
            material_category="Fe-1",
            thickness=10.0,
            position=Position.PLATE_4G,
        )
        assert not engine.can_weld(w, task)

    def test_expired_qualification_not_valid(self):
        """过期资格不应计入有效资格。"""
        w = self._make_welder(
            expire_date=date.today() - timedelta(days=1)
        )
        assert w.valid_qualifications == []


def engine_can_weld(w, task):
    """辅助：避免在 parametrize 中重复构造 engine。"""
    return WelderEngine().can_weld(w, task)
