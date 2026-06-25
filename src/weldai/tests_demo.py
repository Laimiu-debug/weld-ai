"""演示数据构造器（供 UI 演示使用，与 pytest 夹具分离）。

提供一个完整的示例 PQR（Q345R / SMAW / J507 / 16mm 平焊）
和对应的示例 WPS，用于阶段0 的对比校验演示。
"""
from __future__ import annotations

from .domain.base_metal import BaseMetal, BaseMetalThicknessPair
from .domain.consumable import Consumable, ConsumableType
from .domain.enums import (
    CurrentType,
    JointType,
    MaterialGroup,
    Mechanization,
    Position,
    ProcedureType,
    WeldingProcess,
)
from .domain.joint import GrooveDesign, Joint
from .domain.procedure import PassLayer, Procedure, PWHTSpec


def make_q345r() -> BaseMetal:
    return BaseMetal(
        grade="Q345R",
        group=MaterialGroup("Fe", "Fe-1", "Fe-1-2"),
        standard="GB/T 713",
        yield_strength=345,
        tensile_strength=510,
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


def build_demo_pqr() -> Procedure:
    """示例 PQR：Q345R / SMAW / J507(E5015) / 16mm / 平焊 / 直流反接。"""
    metal = make_q345r()
    cons = make_j507()
    return Procedure(
        doc_no="PQR-001",
        type=ProcedureType.PQR,
        process=WeldingProcess.SMAW,
        mechanization=Mechanization.MANUAL,
        base_metals=[BaseMetalThicknessPair(metal, 16.0)],
        consumables=[cons],
        joints=[Joint(type=JointType.BUTT, groove=GrooveDesign(type="V"),
                      thickness=16.0)],
        passes=[
            PassLayer(
                sequence=1, layer_role="打底",
                consumable=cons, diameter=3.2,
                current_type=CurrentType.DCEP,
                current_min=100, current_max=130,
                voltage_min=22, voltage_max=26,
            ),
            PassLayer(
                sequence=2, layer_role="填充",
                consumable=cons, diameter=3.2,
                current_type=CurrentType.DCEP,
                current_min=120, current_max=140,
            ),
        ],
        positions=[Position.PLATE_1G],
        preheat_min=None,
        pwht=PWHTSpec(),
        impact_required=False,
        deposited_thickness=16.0,
        standard_version="NBT47014-2023",
    )


def build_demo_wps() -> Procedure:
    """示例 WPS：与 PQR 一致（演示中由 UI 按变更项修改）。"""
    import copy
    wps = copy.deepcopy(build_demo_pqr())
    wps.doc_no = "WPS-001"
    wps.type = ProcedureType.WPS
    wps.supporting_pqr_no = "PQR-001"
    return wps
