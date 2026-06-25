"""接头与坡口领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .enums import JointType


@dataclass
class GrooveDesign:
    """坡口设计（坡口形式变更属次要因素，无需重新评定，但仍写入 WPS）。"""

    type: str = "V"            # V / U / X / I(直边) 等
    angle: float | None = None       # 坡口角度 °
    root_face: float | None = None   # 钝边 mm
    root_gap: float | None = None    # 根部间隙 mm
    has_backing: bool = False        # 是否带衬垫


@dataclass
class Joint:
    """焊接接头。"""

    type: JointType                      # 接头形式
    groove: GrooveDesign = field(default_factory=GrooveDesign)
    thickness: float = 0.0               # 母材厚度 mm（对接）
    outer_diameter: float | None = None  # 管外径 mm（管对接）
    drawing_path: str = ""               # 接头草图（预留，未来可接 SVG/PNG）
