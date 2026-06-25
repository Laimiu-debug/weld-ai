"""母材领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import MaterialGroup


@dataclass
class BaseMetal:
    """母材（如 Q345R）。

    规则引擎判定基于 category/group（类组号），牌号仅作人工识别。
    """

    grade: str               # 牌号，如 "Q345R"
    group: MaterialGroup     # 类组号
    standard: str            # 产品标准号，如 "GB/T 713"
    tensile_strength: float | None = None  # 抗拉强度 MPa
    yield_strength: float | None = None    # 屈服强度 MPa
    chemistry: dict[str, float] = field(default_factory=dict)  # 化学成分（质量分数）
    remark: str = ""

    @property
    def category(self) -> str:
        return self.group.category

    def __str__(self) -> str:
        return f"{self.grade} ({self.group.group})"


@dataclass
class BaseMetalThicknessPair:
    """异种钢焊接时的一对母材 + 各自厚度。"""

    metal: BaseMetal
    thickness: float          # 母材厚度 mm
