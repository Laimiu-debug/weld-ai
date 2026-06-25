"""焊接材料（填充金属）领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConsumableType(str, Enum):
    """焊材类型。"""

    ELECTRODE = "electrode"      # 焊条（表2，GB/T 5117/5118/983）
    WIRE = "wire"                # 焊丝/填充丝（表3，GB/T 8110/4240）
    FLUX = "flux"                # 焊剂
    WIRE_FLUX_COMBO = "combo"    # 埋弧焊焊丝-焊剂组合（表4，GB/T 5293/12470）
    STRIP = "strip"              # 焊带（堆焊）

    @property
    def cn(self) -> str:
        return {
            ConsumableType.ELECTRODE: "焊条",
            ConsumableType.WIRE: "焊丝/填充丝",
            ConsumableType.FLUX: "焊剂",
            ConsumableType.WIRE_FLUX_COMBO: "焊丝-焊剂组合",
            ConsumableType.STRIP: "焊带",
        }[self]

    @property
    def deposition_efficiency(self) -> float:
        """典型熔敷效率（用于成本估算）。"""
        return {
            ConsumableType.ELECTRODE: 0.55,
            ConsumableType.WIRE: 0.95,
            ConsumableType.FLUX: 0.99,
            ConsumableType.WIRE_FLUX_COMBO: 0.99,
            ConsumableType.STRIP: 0.95,
        }[self]


@dataclass
class Consumable:
    """焊材。

    NB/T 47014 判定变更以 ``classification_slot``（表2/3/4 栏位）为基准，
    而非牌号或型号字符串。

    - ``brand``      商品牌号，如 "J507"（焊材厂自定义，非标准强制）
    - ``model``      国标型号，如 "E5015"（规则引擎唯一可信字段）
    - ``classification_slot``  所属分类栏位，如 "表2-E50"（变更判定主键）
    """

    brand: str                       # 牌号 J507
    model: str                       # 型号 E5015
    type: ConsumableType             # 类型
    classification_slot: str         # 分类栏位（表2/3/4 栏位），变更判定基准
    standard: str = ""               # 产品标准号 GB/T 5118
    diameter: float | None = None    # 规格/直径 mm
    applicable_groups: list[str] = field(default_factory=list)  # 适用母材类组
    remark: str = ""

    def __str__(self) -> str:
        d = f" φ{self.diameter:g}" if self.diameter else ""
        return f"{self.brand} [{self.model}]{d}"
