"""标准配置抽象基类。

这是多标准可切换的核心接口。每个标准（NB/T 47014-2023、ASME IX 等）
实现一个 StandardProfile 子类，从 YAML 数据包加载规则。

切换标准 = 换一个 Profile 实例，业务代码零改动。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.base_metal import BaseMetal
from ..domain.enums import (
    DiameterRange,
    FactorLevel,
    Position,
    ThicknessRange,
    WeldingProcess,
)


class StandardProfile(ABC):
    """焊接工艺评定标准配置。

    所有方法应保持纯查询语义：给定输入 → 返回规则结果，无副作用。
    具体规则数据从 YAML 加载（见 standards/data/）。
    """

    @property
    @abstractmethod
    def standard_code(self) -> str:
        """标准代号，如 'NB/T 47014-2023'。"""

    @property
    @abstractmethod
    def registry_key(self) -> str:
        """注册表键，如 'NBT47014-2023'（机器友好，无空格/斜杠）。"""

    # ----- 母材 ----------------------------------------------------------

    @abstractmethod
    def get_base_metal(self, grade: str) -> BaseMetal | None:
        """按牌号查母材（含类组号）。"""

    @abstractmethod
    def base_metal_covers(
        self, qualified_group: str, target_group: str
    ) -> bool:
        """母材类组覆盖判定：qualified_group 评定合格能否覆盖 target_group。

        NB/T 47014 规则：
          - 同类别号下高组别覆盖低组别（Fe-1-2 覆盖 Fe-1-1）
          - 跨类别号一般需重新评定
        """

    # ----- 焊材 ----------------------------------------------------------

    @abstractmethod
    def consumable_slot_changed(
        self, qualified_slot: str, target_slot: str
    ) -> bool:
        """焊材分类栏位是否跨栏变更（跨栏 → 重要因素）。"""

    # ----- 焊接工艺评定因素 ----------------------------------------------

    @abstractmethod
    def get_factors(
        self, process: WeldingProcess
    ) -> list["FactorDef"]:
        """取某焊接方法的全部评定因素定义（来自表6）。"""

    @abstractmethod
    def get_factor(
        self, process: WeldingProcess, factor_id: str
    ) -> "FactorDef | None":
        """取单个因素定义。"""

    @abstractmethod
    def get_factor_by_category(
        self, process: WeldingProcess, category: str
    ) -> "FactorDef | None":
        """按语义键 category 取因素定义（跨方法稳定，不依赖ID偏移）。"""

    # ----- 覆盖范围（表7）------------------------------------------------

    @abstractmethod
    def coverage_thickness(
        self, coupon_t: float, impact_required: bool = False
    ) -> ThicknessRange:
        """母材厚度覆盖范围。coupon_t 为评定试件厚度 mm。"""

    @abstractmethod
    def coverage_deposited_thickness(
        self, coupon_t: float, impact_required: bool = False
    ) -> ThicknessRange:
        """焊缝金属厚度覆盖范围（对接多层焊，与母材厚度分别计算）。"""

    @abstractmethod
    def coverage_diameter(self, coupon_d: float) -> DiameterRange:
        """管径覆盖范围。coupon_d 为评定试件外径 mm。"""

    @abstractmethod
    def coverage_positions(self, qualified: Position) -> list[Position]:
        """焊接位置覆盖：qualified 合格可覆盖哪些位置（高难度覆盖低难度）。"""


class FactorDef:
    """评定因素定义（表6 的数字化行）。

    level 为该因素的变更等级。supplemental 因素可能有 invalidate_when
    失效条件（如经上转变温度 PWHT 后失效，降为次要）。
    category 为稳定的语义键，供引擎跨方法查找（不依赖具体ID偏移）。
    """

    __slots__ = ("factor_id", "category", "name", "level", "invalidate_when", "note")

    def __init__(
        self,
        factor_id: str,
        name: str,
        level: FactorLevel,
        category: str = "",
        invalidate_when: list[str] | None = None,
        note: str = "",
    ):
        self.factor_id = factor_id
        self.category = category
        self.name = name
        self.level = level
        self.invalidate_when = invalidate_when or []
        self.note = note

    def __repr__(self) -> str:
        return f"FactorDef({self.factor_id}, {self.name}, {self.level.value})"
