"""焊接工艺文件领域模型（pWPS / WPS / PQR）。

规则引擎的核心工作：对比一个 PQR（评定基准）与一个 WPS（生产规程），
判断 WPS 相对 PQR 的每一项变更属于哪个因素等级，是否需要重新评定。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base_metal import BaseMetalThicknessPair
from .consumable import Consumable
from .enums import (
    CurrentType,
    JointType,
    Mechanization,
    Position,
    ProcedureType,
    WeldingProcess,
)
from .joint import Joint


@dataclass
class PassLayer:
    """单焊道/焊层参数。

    按"打底/填充/盖面"分列，是 NB/T 47015 WPS 表格的核心栏目。

    process 支持组合焊接（如 GTAW打底 + SMAW填充）：每道可指定独立焊接方法，
    为 None 时回退到 Procedure.process（向后兼容单方法工艺）。
    """

    sequence: int = 1                       # 焊道序号
    layer_role: str = "填充"                 # 打底/填充/盖面
    process: WeldingProcess | None = None   # 本道焊接方法（None=继承Procedure.process）
    consumable: Consumable | None = None    # 焊材
    diameter: float | None = None           # 焊材直径 mm
    current_min: float | None = None        # 电流下限 A
    current_max: float | None = None        # 电流上限 A
    voltage_min: float | None = None        # 电压下限 V
    voltage_max: float | None = None        # 电压上限 V
    current_type: CurrentType | None = None  # 极性/电流种类
    travel_speed: float | None = None       # 焊接速度 cm/min
    heat_input_min: float | None = None     # 热输入下限 kJ/mm
    heat_input_max: float | None = None     # 热输入上限 kJ/mm
    gas_type: str = ""                      # 保护气体
    gas_flow: float | None = None           # 气体流量 L/min
    interpass_temp: float | None = None     # 层间温度 ℃

    def effective_process(self, default: WeldingProcess) -> WeldingProcess:
        """本道实际焊接方法：优先用本道 process，否则回退到 procedure 默认。"""
        return self.process if self.process is not None else default


@dataclass
class PWHTSpec:
    """焊后热处理参数。"""

    applied: bool = False              # 是否进行 PWHT
    pwht_type: str = ""                # 类型（消除应力/正火/固溶等）
    temp_min: float | None = None      # 温度下限 ℃
    temp_max: float | None = None      # 温度上限 ℃
    hold_time: float | None = None     # 保温时间 min
    upper_transformation: bool = False  # 是否上转变温度热处理（影响补加因素失效）
    austenitic_solution_treated: bool = False  # 奥氏体固溶处理（影响补加因素失效）


@dataclass
class Procedure:
    """焊接工艺文件（pWPS / WPS / PQR 通用结构）。

    PQR 是评定基准（记录实际试验参数），WPS 是生产规程（范围不得超出 PQR）。
    """

    doc_no: str                          # 文件编号
    type: ProcedureType                  # pWPS / WPS / PQR
    process: WeldingProcess              # 焊接方法
    mechanization: Mechanization = Mechanization.MANUAL

    # 母材（异种钢时两侧不同）
    base_metals: list[BaseMetalThicknessPair] = field(default_factory=list)

    # 焊材
    consumables: list[Consumable] = field(default_factory=list)

    # 接头
    joints: list[Joint] = field(default_factory=list)

    # 焊道参数
    passes: list[PassLayer] = field(default_factory=list)

    # 焊接位置
    positions: list[Position] = field(default_factory=list)

    # 预热
    preheat_min: float | None = None     # 最低预热温度 ℃

    # 焊后热处理
    pwht: PWHTSpec = field(default_factory=PWHTSpec)

    # 关联（WPS 关联其支撑的 PQR 编号）
    supporting_pqr_no: str = ""          # 本 WPS 所依据的 PQR 编号
    standard_version: str = ""           # 评定依据标准版本，如 "NBT47014-2023"

    # 是否有冲击试验要求（决定补加因素是否升级）
    impact_required: bool = False

    # 焊缝金属厚度（对接多层焊，与母材厚度分别计算覆盖）
    deposited_thickness: float | None = None

    # 文档元信息（用于报表表头，特检院报检要求）
    manufacturer: str = ""             # 编制单位名称
    project_no: str = ""               # 项目/产品编号
    drawing_no: str = ""               # 产品图号
    prepared_by: str = ""              # 编制人
    reviewed_by: str = ""              # 审核人
    approved_by: str = ""              # 批准人
    prepare_date: str = ""             # 编制日期

    remark: str = ""

    @property
    def joint_type(self) -> JointType | None:
        return self.joints[0].type if self.joints else None

    @property
    def max_base_thickness(self) -> float:
        return max((bm.thickness for bm in self.base_metals), default=0.0)

    @property
    def all_processes(self) -> list[WeldingProcess]:
        """本工艺涉及的全部焊接方法（支持组合焊）。

        焊道显式指定 process 时收集之；否则用 procedure.process。
        用于组合焊（GTAW打底+SMAW填充）的规则判定与报表显示。
        返回去重保序列后的方法列表。
        """
        seen: list[WeldingProcess] = []
        if self.passes:
            for pa in self.passes:
                p = pa.effective_process(self.process)
                if p not in seen:
                    seen.append(p)
        else:
            seen.append(self.process)
        return seen

    @property
    def is_combined_process(self) -> bool:
        """是否为组合焊接方法（多于一种方法）。"""
        return len(self.all_processes) > 1

    @property
    def process_display(self) -> str:
        """焊接方法显示文本（组合焊时列出全部方法）。"""
        return " + ".join(p.cn for p in self.all_processes)
