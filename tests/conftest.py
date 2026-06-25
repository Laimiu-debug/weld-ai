"""测试夹具：构造示例 PQR / WPS 用于规则引擎验证。"""
from __future__ import annotations

from datetime import date

from weldai.domain.base_metal import BaseMetal, BaseMetalThicknessPair
from weldai.domain.consumable import Consumable, ConsumableType
from weldai.domain.enums import (
    CurrentType,
    FactorLevel,
    JointType,
    MaterialGroup,
    Mechanization,
    Position,
    ProcedureType,
    WeldingProcess,
)
from weldai.domain.joint import GrooveDesign, Joint
from weldai.domain.procedure import PassLayer, Procedure, PWHTSpec


def make_q345r_metal() -> BaseMetal:
    return BaseMetal(
        grade="Q345R",
        group=MaterialGroup("Fe", "Fe-1", "Fe-1-2"),
        standard="GB/T 713",
        yield_strength=345,
        tensile_strength=510,
    )


def make_q245r_metal() -> BaseMetal:
    return BaseMetal(
        grade="Q245R",
        group=MaterialGroup("Fe", "Fe-1", "Fe-1-1"),
        standard="GB/T 713",
        yield_strength=245,
        tensile_strength=400,
    )


def make_j507() -> Consumable:
    return Consumable(
        brand="J507",
        model="E5015",
        type=ConsumableType.ELECTRODE,
        classification_slot="表2-E50",
        standard="GB/T 5118",
        diameter=3.2,
    )


def make_j422() -> Consumable:
    return Consumable(
        brand="J422",
        model="E4303",
        type=ConsumableType.ELECTRODE,
        classification_slot="表2-E43",
        standard="GB/T 5117",
        diameter=3.2,
    )


def make_pqr_q345r_smaw(
    thickness: float = 16.0,
    current_type: CurrentType = CurrentType.DCEP,
    preheat: float | None = None,
    pwht: PWHTSpec | None = None,
    position: Position = Position.PLATE_1G,
    impact_required: bool = False,
) -> Procedure:
    """标准 PQR：Q345R / SMAW / J507 / 16mm。"""
    metal = make_q345r_metal()
    cons = make_j507()
    return Procedure(
        doc_no="PQR-001",
        type=ProcedureType.PQR,
        process=WeldingProcess.SMAW,
        mechanization=Mechanization.MANUAL,
        base_metals=[BaseMetalThicknessPair(metal, thickness)],
        consumables=[cons],
        joints=[Joint(type=JointType.BUTT, groove=GrooveDesign(type="V"),
                      thickness=thickness)],
        passes=[
            PassLayer(
                sequence=1, layer_role="打底",
                consumable=cons, diameter=3.2,
                current_type=current_type,
                current_min=100, current_max=130,
                voltage_min=22, voltage_max=26,
            ),
            PassLayer(
                sequence=2, layer_role="填充",
                consumable=cons, diameter=3.2,
                current_type=current_type,
                current_min=120, current_max=140,
            ),
        ],
        positions=[position],
        preheat_min=preheat,
        pwht=pwht or PWHTSpec(),
        impact_required=impact_required,
        deposited_thickness=thickness,
        standard_version="NBT47014-2023",
    )


def make_wps_from_pqr(
    pqr: Procedure,
    doc_no: str = "WPS-001",
    supporting_pqr: str = "PQR-001",
) -> Procedure:
    """基于 PQR 克隆一个 WPS（默认完全一致，测试中再按需修改）。"""
    import copy
    wps = copy.deepcopy(pqr)
    wps.doc_no = doc_no
    wps.type = ProcedureType.WPS
    wps.supporting_pqr_no = supporting_pqr
    return wps
