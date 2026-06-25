"""领域枚举定义。

这些枚举是跨标准通用的概念抽象。各标准(StandardProfile)在自己的
YAML 数据包中给出具体取值，引擎通过这些枚举统一处理。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FactorLevel(str, Enum):
    """焊接工艺评定因素变更等级（NB/T 47014 三级体系）。

    用 str 枚举便于直接序列化为 YAML/DB 字段。
    """

    ESSENTIAL = "essential"        # 重要因素：变更→必须重新评定
    SUPPLEMENTAL = "supplemental"  # 补加因素：有冲击要求→补做冲击；否则同次要
    NONESSENTIAL = "nonessential"  # 次要因素：仅改 WPS

    @property
    def cn(self) -> str:
        return {
            FactorLevel.ESSENTIAL: "重要因素",
            FactorLevel.SUPPLEMENTAL: "补加因素",
            FactorLevel.NONESSENTIAL: "次要因素",
        }[self]


class WeldingProcess(str, Enum):
    """常用焊接方法代号（与 TSG Z6002 表 A-1 / NB/T 47014 一致）。"""

    OFW = "OFW"    # 气焊
    SMAW = "SMAW"  # 焊条电弧焊
    GTAW = "GTAW"  # 钨极气体保护焊（氩弧焊）
    GMAW = "GMAW"  # 熔化极气体保护焊
    FCAW = "FCAW"  # 药芯焊丝电弧焊
    SAW = "SAW"    # 埋弧焊
    PAW = "PAW"    # 等离子弧焊
    EGW = "EGW"    # 气电立焊
    ESW = "ESW"    # 电渣焊
    FRW = "FRW"    # 摩擦焊
    SW = "SW"      # 螺柱焊
    EBW = "EBW"    # 电子束焊（2023 版新增）

    @property
    def cn(self) -> str:
        return {
            WeldingProcess.OFW: "气焊",
            WeldingProcess.SMAW: "焊条电弧焊",
            WeldingProcess.GTAW: "钨极气体保护焊",
            WeldingProcess.GMAW: "熔化极气体保护焊",
            WeldingProcess.FCAW: "药芯焊丝电弧焊",
            WeldingProcess.SAW: "埋弧焊",
            WeldingProcess.PAW: "等离子弧焊",
            WeldingProcess.EGW: "气电立焊",
            WeldingProcess.ESW: "电渣焊",
            WeldingProcess.FRW: "摩擦焊",
            WeldingProcess.SW: "螺柱焊",
            WeldingProcess.EBW: "电子束焊",
        }[self]


class Mechanization(str, Enum):
    """机械化程度。"""

    MANUAL = "manual"        # 手工焊
    MECHANIZED = "mechanized"  # 机动焊
    AUTOMATIC = "automatic"  # 自动焊

    @property
    def cn(self) -> str:
        return {
            Mechanization.MANUAL: "手工焊",
            Mechanization.MECHANIZED: "机动焊",
            Mechanization.AUTOMATIC: "自动焊",
        }[self]


class ProcedureType(str, Enum):
    """工艺文件类型。"""

    PWPS = "pWPS"  # 预焊接工艺规程
    WPS = "WPS"    # 焊接工艺规程
    PQR = "PQR"    # 工艺评定记录


class JointType(str, Enum):
    """接头/焊缝形式。"""

    BUTT = "butt"        # 对接焊缝
    FILLET = "fillet"    # 角焊缝
    TEE = "tee"          # T 形接头
    CORNER = "corner"    # 角接
    NOZZLE = "nozzle"    # 管板/接管

    @property
    def cn(self) -> str:
        return {
            JointType.BUTT: "对接焊缝",
            JointType.FILLET: "角焊缝",
            JointType.TEE: "T形接头",
            JointType.CORNER: "角接接头",
            JointType.NOZZLE: "管板/接管",
        }[self]


class CurrentType(str, Enum):
    """电流种类（NB/T 47014-2023 将电源类型升级为重要因素，覆盖此项）。"""

    DCEN = "DCEN"  # 直流正接
    DCEP = "DCEP"  # 直流反接
    AC = "AC"      # 交流
    PULSE = "PULSE"  # 脉冲
    VP = "VP"      # 变极性（2023 版明确为独立电流种类）

    @property
    def cn(self) -> str:
        return {
            CurrentType.DCEN: "直流正接(DCEN)",
            CurrentType.DCEP: "直流反接(DCEP)",
            CurrentType.AC: "交流(AC)",
            CurrentType.PULSE: "脉冲",
            CurrentType.VP: "变极性(VP)",
        }[self]


class Position(str, Enum):
    """焊接位置代号（板/管）。难度等级用于覆盖判定（高难度覆盖低难度）。"""

    # 板对接
    PLATE_1G = "1G"
    PLATE_2G = "2G"
    PLATE_3G = "3G"
    PLATE_4G = "4G"
    # 板角焊缝
    PLATE_1F = "1F"
    PLATE_2F = "2F"
    PLATE_3F = "3F"
    PLATE_4F = "4F"
    # 管对接
    PIPE_1G = "1G(管)"
    PIPE_2G = "2G(管)"
    PIPE_5G = "5G"
    PIPE_6G = "6G"
    PIPE_6GR = "6GR"


@dataclass(frozen=True)
class ThicknessRange:
    """厚度覆盖区间 [min, max]，max 为 None 表示不限。"""

    min_t: float
    max_t: float | None

    def contains(self, t: float) -> bool:
        upper = self.max_t if self.max_t is not None else float("inf")
        return self.min_t - 1e-9 <= t <= upper + 1e-9

    def __repr__(self) -> str:
        mx = "不限" if self.max_t is None else f"{self.max_t:g}"
        return f"[{self.min_t:g}, {mx}]"


@dataclass(frozen=True)
class DiameterRange:
    """管径覆盖区间 [min, max]，max 为 None 表示不限。"""

    min_d: float
    max_d: float | None

    def contains(self, d: float) -> bool:
        upper = self.max_d if self.max_d is not None else float("inf")
        return self.min_d - 1e-9 <= d <= upper + 1e-9


@dataclass(frozen=True)
class MaterialGroup:
    """母材类组号（类别号 + 组别号）。

    例如 Fe-1-2 → family="Fe", category="Fe-1", group="Fe-1-2"。
    组别号有时不细分（如部分不锈钢只有类别号），group 可等于 category。
    """

    family: str       # Fe / Al / Ti / Zr / Cu / Ni
    category: str     # Fe-1 / Fe-8 ...
    group: str        # Fe-1-2 / Fe-8-1 ...（无细分时同 category）
