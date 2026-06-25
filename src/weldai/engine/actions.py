"""评定动作决策：把因素等级 + 上下文 → 具体处置动作。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..domain.enums import FactorLevel


class Action(str, Enum):
    """变更后的处置动作。"""

    REQUALIFY = "requalify"            # 重新评定（做全套PQR）
    SUPPLEMENT_IMPACT = "supplement"   # 补做冲击试验
    REVISE_WPS = "revise_wps"          # 仅修改WPS，无需重新评定
    NONE = "none"                      # 无需任何动作

    @property
    def cn(self) -> str:
        return {
            Action.REQUALIFY: "需重新评定",
            Action.SUPPLEMENT_IMPACT: "需补做冲击试验",
            Action.REVISE_WPS: "仅修改WPS",
            Action.NONE: "无需动作",
        }[self]


def decide_action(
    level: FactorLevel,
    has_impact_requirement: bool,
    invalidate_conditions_met: bool,
) -> Action:
    """根据因素等级 + 冲击要求 + 失效条件，决定处置动作。

    逻辑（NB/T 47014 三级因素体系）：
      - 重要因素变更 → 重新评定
      - 补加因素变更：
          * 若失效条件满足（如上转变PWHT）→ 降为次要，仅改WPS
          * 否则有冲击要求 → 补做冲击
          * 否则 → 仅改WPS
      - 次要因素变更 → 仅改WPS
    """
    if level == FactorLevel.ESSENTIAL:
        return Action.REQUALIFY
    if level == FactorLevel.SUPPLEMENTAL:
        if invalidate_conditions_met:
            return Action.REVISE_WPS
        if has_impact_requirement:
            return Action.SUPPLEMENT_IMPACT
        return Action.REVISE_WPS
    # NONESSENTIAL
    return Action.REVISE_WPS


@dataclass
class FactorChange:
    """单因素变更记录（PQR vs WPS 对比的一项结果）。"""

    factor_id: str
    factor_name: str
    level: FactorLevel
    change_description: str                 # 变更内容描述
    invalidate_conditions: list[str]        # 补加因素的失效条件名
    invalidate_conditions_met: bool         # 失效条件是否满足
    action: Action                          # 处置动作

    @property
    def level_cn(self) -> str:
        return self.level.cn

    @property
    def action_cn(self) -> str:
        return self.action.cn

    def __repr__(self) -> str:
        return (
            f"[{self.level_cn}] {self.factor_name}: {self.change_description}"
            f" → {self.action_cn}"
        )
