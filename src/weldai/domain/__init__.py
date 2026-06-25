"""weldAI 领域模型层。

纯数据实体，不依赖数据库或 UI。被 standards/engine/persistence 共享。
"""
from .base_metal import BaseMetal, BaseMetalThicknessPair
from .consumable import Consumable, ConsumableType
from .enums import (
    CurrentType,
    DiameterRange,
    FactorLevel,
    JointType,
    MaterialGroup,
    Mechanization,
    Position,
    ProcedureType,
    ThicknessRange,
    WeldingProcess,
)
from .joint import GrooveDesign, Joint
from .procedure import PassLayer, Procedure, PWHTSpec
from .weld_seam import Product, WeldSeam
from .welder import RenewalRecord, Welder, WelderQualification

__all__ = [
    # enums
    "CurrentType", "DiameterRange", "FactorLevel", "JointType", "MaterialGroup",
    "Mechanization", "Position", "ProcedureType", "ThicknessRange", "WeldingProcess",
    # entities
    "BaseMetal", "BaseMetalThicknessPair",
    "Consumable", "ConsumableType",
    "GrooveDesign", "Joint",
    "PassLayer", "Procedure", "PWHTSpec",
    "RenewalRecord", "Welder", "WelderQualification",
]
