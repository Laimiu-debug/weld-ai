"""仓储层：领域实体 ↔ ORM 行的双向转换与 CRUD。

转换策略：
  - 简单标量（doc_no/process/厚度等）直接映射列
  - 母材：序列化为 {grade, thickness}，反序列化时从 StandardProfile 重建完整 BaseMetal
  - 焊材：序列化为 {brand, model, ...} 全字段（焊材不在标准库内，自含存储）
  - 焊道/接头/PWHT/位置：序列化为 JSON dict/list
"""
from __future__ import annotations

from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.base_metal import BaseMetal, BaseMetalThicknessPair
from ..domain.consumable import Consumable, ConsumableType
from ..domain.enums import (
    CurrentType,
    JointType,
    MaterialGroup,
    Mechanization,
    Position,
    ProcedureType,
    WeldingProcess,
)
from ..domain.joint import GrooveDesign, Joint
from ..domain.procedure import PassLayer, Procedure, PWHTSpec
from ..domain.welder import RenewalRecord, Welder, WelderQualification
from ..domain.weld_seam import Product, WeldSeam
from ..standards.base import StandardProfile
from .models import ConsumableORM, ProcedureORM, ProductORM, WelderORM


# ---------------------------------------------------------------------------
# 序列化：领域实体 → dict（存入 JSON 列）
# ---------------------------------------------------------------------------

def _consumable_to_dict(c: Consumable) -> dict:
    return {
        "brand": c.brand,
        "model": c.model,
        "type": c.type.value,
        "classification_slot": c.classification_slot,
        "standard": c.standard,
        "diameter": c.diameter,
        "applicable_groups": c.applicable_groups,
        "price": c.price,
        "processes": c.processes,
        "remark": c.remark,
    }


def _consumable_from_dict(d: dict) -> Consumable:
    return Consumable(
        brand=d["brand"],
        model=d["model"],
        type=ConsumableType(d["type"]),
        classification_slot=d["classification_slot"],
        standard=d.get("standard", ""),
        diameter=d.get("diameter"),
        applicable_groups=d.get("applicable_groups", []),
        price=d.get("price", 0.0),
        processes=d.get("processes", []),
        remark=d.get("remark", ""),
    )


def _joint_to_dict(j: Joint) -> dict:
    return {
        "type": j.type.value,
        "groove_type": j.groove.type,
        "groove_angle": j.groove.angle,
        "root_face": j.groove.root_face,
        "root_gap": j.groove.root_gap,
        "has_backing": j.groove.has_backing,
        "thickness": j.thickness,
        "outer_diameter": j.outer_diameter,
    }


def _joint_from_dict(d: dict) -> Joint:
    return Joint(
        type=JointType(d["type"]),
        groove=GrooveDesign(
            type=d.get("groove_type", "V"),
            angle=d.get("groove_angle"),
            root_face=d.get("root_face"),
            root_gap=d.get("root_gap"),
            has_backing=d.get("has_backing", False),
        ),
        thickness=d.get("thickness", 0.0),
        outer_diameter=d.get("outer_diameter"),
    )


def _pass_to_dict(p: PassLayer) -> dict:
    return {
        "sequence": p.sequence,
        "layer_role": p.layer_role,
        "process": p.process.value if p.process else None,
        "consumable": _consumable_to_dict(p.consumable) if p.consumable else None,
        "diameter": p.diameter,
        "current_min": p.current_min,
        "current_max": p.current_max,
        "voltage_min": p.voltage_min,
        "voltage_max": p.voltage_max,
        "current_type": p.current_type.value if p.current_type else None,
        "travel_speed": p.travel_speed,
        "heat_input_min": p.heat_input_min,
        "heat_input_max": p.heat_input_max,
        "gas_type": p.gas_type,
        "gas_flow": p.gas_flow,
        "interpass_temp": p.interpass_temp,
    }


def _pass_from_dict(d: dict) -> PassLayer:
    return PassLayer(
        sequence=d.get("sequence", 1),
        layer_role=d.get("layer_role", "填充"),
        process=WeldingProcess(d["process"]) if d.get("process") else None,
        consumable=_consumable_from_dict(d["consumable"]) if d.get("consumable") else None,
        diameter=d.get("diameter"),
        current_min=d.get("current_min"),
        current_max=d.get("current_max"),
        voltage_min=d.get("voltage_min"),
        voltage_max=d.get("voltage_max"),
        current_type=CurrentType(d["current_type"]) if d.get("current_type") else None,
        travel_speed=d.get("travel_speed"),
        heat_input_min=d.get("heat_input_min"),
        heat_input_max=d.get("heat_input_max"),
        gas_type=d.get("gas_type", ""),
        gas_flow=d.get("gas_flow"),
        interpass_temp=d.get("interpass_temp"),
    )


def _pwht_to_dict(p: PWHTSpec) -> dict:
    return {
        "applied": p.applied,
        "pwht_type": p.pwht_type,
        "temp_min": p.temp_min,
        "temp_max": p.temp_max,
        "hold_time": p.hold_time,
        "upper_transformation": p.upper_transformation,
        "austenitic_solution_treated": p.austenitic_solution_treated,
    }


def _pwht_from_dict(d: dict) -> PWHTSpec:
    return PWHTSpec(
        applied=d.get("applied", False),
        pwht_type=d.get("pwht_type", ""),
        temp_min=d.get("temp_min"),
        temp_max=d.get("temp_max"),
        hold_time=d.get("hold_time"),
        upper_transformation=d.get("upper_transformation", False),
        austenitic_solution_treated=d.get("austenitic_solution_treated", False),
    )


# ---------------------------------------------------------------------------
# Procedure 仓储
# ---------------------------------------------------------------------------

class ProcedureRepository:
    """工艺文件仓储：领域 Procedure ↔ ORM 的转换与 CRUD。

    反序列化母材时，需注入 StandardProfile 以重建完整 BaseMetal（含类组号）。
    """

    def __init__(self, session: Session, standard: StandardProfile):
        self.session = session
        self.standard = standard

    # ----- 转换 -----

    def to_orm(self, proc: Procedure, orm: ProcedureORM | None = None) -> ProcedureORM:
        """领域 Procedure → ORM 行（更新已有或新建）。"""
        if orm is None:
            orm = ProcedureORM(doc_no=proc.doc_no)
        orm.doc_no = proc.doc_no
        orm.type = proc.type.value
        orm.process = proc.process.value
        orm.mechanization = proc.mechanization.value
        orm.supporting_pqr_no = proc.supporting_pqr_no
        orm.standard_version = proc.standard_version or self.standard.registry_key
        orm.impact_required = proc.impact_required
        # 母材：存 {grade, thickness}，反序列化时从标准库重建
        orm.base_metals = [
            {"grade": bm.metal.grade, "thickness": bm.thickness}
            for bm in proc.base_metals
        ]
        orm.consumables = [_consumable_to_dict(c) for c in proc.consumables]
        orm.passes = [_pass_to_dict(p) for p in proc.passes]
        orm.joints = [_joint_to_dict(j) for j in proc.joints]
        orm.positions = [p.value for p in proc.positions]
        orm.preheat_min = proc.preheat_min
        orm.pwht = _pwht_to_dict(proc.pwht)
        orm.deposited_thickness = proc.deposited_thickness
        orm.remark = proc.remark
        orm.doc_meta = {
            "manufacturer": proc.manufacturer,
            "project_no": proc.project_no,
            "drawing_no": proc.drawing_no,
            "prepared_by": proc.prepared_by,
            "reviewed_by": proc.reviewed_by,
            "approved_by": proc.approved_by,
            "prepare_date": proc.prepare_date,
        }
        return orm

    def from_orm(self, orm: ProcedureORM) -> Procedure:
        """ORM 行 → 领域 Procedure。母材从标准库按牌号重建。"""
        base_metals: list[BaseMetalThicknessPair] = []
        for bm in orm.base_metals or []:
            grade = bm.get("grade", "")
            thickness = bm.get("thickness", 0.0)
            metal = self.standard.get_base_metal(grade)
            if metal is None:
                # 牌号不在标准库 → 用最小占位（保留牌号，类组号未知）
                metal = BaseMetal(
                    grade=grade,
                    group=MaterialGroup("?", grade, grade),
                    standard="",
                )
            base_metals.append(BaseMetalThicknessPair(metal, thickness))

        return Procedure(
            doc_no=orm.doc_no,
            type=ProcedureType(orm.type),
            process=WeldingProcess(orm.process),
            mechanization=Mechanization(orm.mechanization or "manual"),
            base_metals=base_metals,
            consumables=[_consumable_from_dict(c) for c in (orm.consumables or [])],
            passes=[_pass_from_dict(p) for p in (orm.passes or [])],
            joints=[_joint_from_dict(j) for j in (orm.joints or [])],
            positions=[Position(v) for v in (orm.positions or [])],
            preheat_min=orm.preheat_min,
            pwht=_pwht_from_dict(orm.pwht or {}),
            impact_required=orm.impact_required,
            deposited_thickness=orm.deposited_thickness,
            supporting_pqr_no=orm.supporting_pqr_no or "",
            standard_version=orm.standard_version or "",
            remark=orm.remark or "",
            manufacturer=(orm.doc_meta or {}).get("manufacturer", ""),
            project_no=(orm.doc_meta or {}).get("project_no", ""),
            drawing_no=(orm.doc_meta or {}).get("drawing_no", ""),
            prepared_by=(orm.doc_meta or {}).get("prepared_by", ""),
            reviewed_by=(orm.doc_meta or {}).get("reviewed_by", ""),
            approved_by=(orm.doc_meta or {}).get("approved_by", ""),
            prepare_date=(orm.doc_meta or {}).get("prepare_date", ""),
        )

    # ----- CRUD -----

    def save(self, proc: Procedure) -> ProcedureORM:
        """保存（插入或更新，按 doc_no 判重）。"""
        existing = self.session.scalar(
            select(ProcedureORM).where(ProcedureORM.doc_no == proc.doc_no)
        )
        orm = self.to_orm(proc, existing)
        self.session.add(orm)
        self.session.commit()
        return orm

    def get(self, doc_no: str) -> Procedure | None:
        orm = self.session.scalar(
            select(ProcedureORM).where(ProcedureORM.doc_no == doc_no)
        )
        return self.from_orm(orm) if orm else None

    def delete(self, doc_no: str) -> bool:
        orm = self.session.scalar(
            select(ProcedureORM).where(ProcedureORM.doc_no == doc_no)
        )
        if orm is None:
            return False
        self.session.delete(orm)
        self.session.commit()
        return True

    def list_all(self, doc_type: ProcedureType | None = None) -> list[Procedure]:
        """列出工艺文件，可按类型过滤（WPS/PQR/pWPS）。"""
        stmt = select(ProcedureORM).order_by(ProcedureORM.doc_no)
        if doc_type is not None:
            stmt = stmt.where(ProcedureORM.type == doc_type.value)
        orms = self.session.scalars(stmt).all()
        return [self.from_orm(o) for o in orms]


# ---------------------------------------------------------------------------
# Welder 仓储（TSG Z6002 焊工资格）
# ---------------------------------------------------------------------------

def _qualification_to_dict(q: WelderQualification) -> dict:
    return {
        "process": q.process.value,
        "material_category": q.material_category,
        "position": q.position.value,
        "deposited_thickness": q.deposited_thickness,
        "outer_diameter": q.outer_diameter,
        "fill_metal_class": q.fill_metal_class,
        "process_factors": list(q.process_factors),
        "process_factor": q.process_factor,  # 兼容旧字段(多选加号连接)
        "specimen_form": q.specimen_form,
        "has_backing": q.has_backing,
        "qualified_date": q.qualified_date.isoformat() if q.qualified_date else None,
        "expire_date": q.expire_date.isoformat() if q.expire_date else None,
    }


def _qualification_from_dict(d: dict) -> WelderQualification:
    # 优先用 process_factors 列表(新)，回退 process_factor 字符串(旧)
    if d.get("process_factors"):
        factors = list(d["process_factors"])
    elif d.get("process_factor"):
        factors = d["process_factor"].split("+") if "+" in d["process_factor"] else [d["process_factor"]]
    else:
        factors = []
    return WelderQualification(
        process=WeldingProcess(d["process"]),
        material_category=d.get("material_category", ""),
        position=Position(_normalize_position(d.get("position", "1G"))),
        deposited_thickness=d.get("deposited_thickness", 12.0),
        outer_diameter=d.get("outer_diameter"),
        fill_metal_class=d.get("fill_metal_class", ""),
        process_factors=factors,
        specimen_form=d.get("specimen_form", ""),
        has_backing=d.get("has_backing", False),
        qualified_date=_parse_date(d.get("qualified_date")),
        expire_date=_parse_date(d.get("expire_date")),
    )


# 旧版位置值 → 新版（管对接加"(管)"后缀、管板改标准FG代号）
_POSITION_LEGACY_MAP = {
    "5G": "5G(管)",
    "6G": "6G(管)",
    # 旧管板代号 → 标准 TSG Z6002 表A-4 代号
    "1F(管板)": "2FRG",
    "2F(管板)": "2FG",
    "2FR": "2FRG",
    "4F(管板)": "4FG",
    "5F(管板)": "5FG",
    "6FG": "6FG",  # 已是标准代号
}


def _normalize_position(val: str) -> str:
    """旧版位置值兼容映射，新值原样返回。

    - 管对接：5G→5G(管)、6G→6G(管)
    - 管板角接：2F(管板)→2FG、4F(管板)→4FG、5F(管板)→5FG（TSG Z6002 表A-4）
    """
    if val in _POSITION_LEGACY_MAP:
        return _POSITION_LEGACY_MAP[val]
    return val


def _renewal_to_dict(r: RenewalRecord) -> dict:
    return {
        "renewal_date": r.renewal_date.isoformat(),
        "renewal_type": r.renewal_type,
        "result": r.result,
        "remark": r.remark,
    }


def _renewal_from_dict(d: dict) -> RenewalRecord:
    return RenewalRecord(
        renewal_date=_parse_date(d["renewal_date"]) or date.today(),
        renewal_type=d.get("renewal_type", "首次"),
        result=d.get("result", "合格"),
        remark=d.get("remark", ""),
    )


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s)


class WelderRepository:
    """焊工仓储：领域 Welder ↔ ORM 的转换与 CRUD。"""

    def __init__(self, session: Session):
        self.session = session

    # ----- 转换 -----

    def to_orm(self, welder: Welder, orm: WelderORM | None = None) -> WelderORM:
        if orm is None:
            orm = WelderORM(stamp_no=welder.stamp_no)
        orm.stamp_no = welder.stamp_no
        orm.cert_no = welder.cert_no
        orm.name = welder.name
        orm.birth_date = welder.birth_date
        orm.status = welder.status
        orm.last_work_date = welder.last_work_date
        orm.qualifications = [_qualification_to_dict(q) for q in welder.qualifications]
        orm.renewals = [_renewal_to_dict(r) for r in welder.renewals]
        return orm

    def from_orm(self, orm: WelderORM) -> Welder:
        return Welder(
            stamp_no=orm.stamp_no,
            cert_no=orm.cert_no or "",
            name=orm.name or "",
            birth_date=orm.birth_date,
            status=orm.status or "有效",
            last_work_date=orm.last_work_date,
            qualifications=[
                _qualification_from_dict(q) for q in (orm.qualifications or [])
            ],
            renewals=[
                _renewal_from_dict(r) for r in (orm.renewals or [])
            ],
        )

    # ----- CRUD -----

    def save(self, welder: Welder) -> WelderORM:
        existing = self.session.scalar(
            select(WelderORM).where(WelderORM.stamp_no == welder.stamp_no)
        )
        orm = self.to_orm(welder, existing)
        self.session.add(orm)
        self.session.commit()
        return orm

    def get(self, stamp_no: str) -> Welder | None:
        orm = self.session.scalar(
            select(WelderORM).where(WelderORM.stamp_no == stamp_no)
        )
        return self.from_orm(orm) if orm else None

    def delete(self, stamp_no: str) -> bool:
        orm = self.session.scalar(
            select(WelderORM).where(WelderORM.stamp_no == stamp_no)
        )
        if orm is None:
            return False
        self.session.delete(orm)
        self.session.commit()
        return True

    def list_all(self) -> list[Welder]:
        stmt = select(WelderORM).order_by(WelderORM.stamp_no)
        orms = self.session.scalars(stmt).all()
        return [self.from_orm(o) for o in orms]


# ---------------------------------------------------------------------------
# Product 仓储（焊缝追溯）
# ---------------------------------------------------------------------------

def _enum_value(v) -> str:
    """取枚举/字符串的值。

    QComboBox.currentData() 对 (str, Enum) 混合枚举会退化为纯 str，
    丢失 .value 属性，这里统一兜底（防御性）。
    """
    return v.value if hasattr(v, "value") else str(v)


def _seam_to_dict(s: WeldSeam) -> dict:
    return {
        "seam_no": s.seam_no,
        "product_no": s.product_no,
        "drawing_no": s.drawing_no,
        "wps_no": s.wps_no,
        "welder_stamp": s.welder_stamp,
        "joint_type": _enum_value(s.joint_type),
        "position": _enum_value(s.position),
        "length": s.length,
        "thickness": s.thickness,
        "weld_date": s.weld_date.isoformat() if s.weld_date else None,
        "ndt_result": s.ndt_result,
        "remark": s.remark,
    }


def _seam_from_dict(d: dict) -> WeldSeam:
    return WeldSeam(
        seam_no=d["seam_no"],
        product_no=d.get("product_no", ""),
        drawing_no=d.get("drawing_no", ""),
        wps_no=d.get("wps_no", ""),
        welder_stamp=d.get("welder_stamp", ""),
        joint_type=JointType(d.get("joint_type", "butt")),
        position=Position(d.get("position", "1G")),
        length=d.get("length", 0.0),
        thickness=d.get("thickness", 0.0),
        weld_date=_parse_date(d.get("weld_date")),
        ndt_result=d.get("ndt_result", ""),
        remark=d.get("remark", ""),
    )


class ProductRepository:
    """产品（容器）+ 焊缝追溯 仓储。"""

    def __init__(self, session: Session):
        self.session = session

    def to_orm(self, product: Product, orm: ProductORM | None = None) -> ProductORM:
        if orm is None:
            orm = ProductORM(product_no=product.product_no)
        orm.product_no = product.product_no
        orm.drawing_no = product.drawing_no
        orm.name = product.name
        orm.customer = product.customer
        orm.manufacture_date = product.manufacture_date
        orm.seams = [_seam_to_dict(s) for s in product.seams]
        orm.remark = ""
        return orm

    def from_orm(self, orm: ProductORM) -> Product:
        return Product(
            product_no=orm.product_no,
            drawing_no=orm.drawing_no or "",
            name=orm.name or "",
            customer=orm.customer or "",
            manufacture_date=orm.manufacture_date,
            seams=[_seam_from_dict(s) for s in (orm.seams or [])],
        )

    def save(self, product: Product) -> ProductORM:
        existing = self.session.scalar(
            select(ProductORM).where(ProductORM.product_no == product.product_no)
        )
        orm = self.to_orm(product, existing)
        self.session.add(orm)
        self.session.commit()
        return orm

    def get(self, product_no: str) -> Product | None:
        orm = self.session.scalar(
            select(ProductORM).where(ProductORM.product_no == product_no)
        )
        return self.from_orm(orm) if orm else None

    def delete(self, product_no: str) -> bool:
        orm = self.session.scalar(
            select(ProductORM).where(ProductORM.product_no == product_no)
        )
        if orm is None:
            return False
        self.session.delete(orm)
        self.session.commit()
        return True

    def list_all(self) -> list[Product]:
        stmt = select(ProductORM).order_by(ProductORM.product_no)
        orms = self.session.scalars(stmt).all()
        return [self.from_orm(o) for o in orms]

    def add_seam(self, product_no: str, seam: WeldSeam) -> bool:
        """向产品追加一条焊缝。产品不存在返回 False。"""
        product = self.get(product_no)
        if product is None:
            return False
        seam.product_no = product_no
        if product.drawing_no:
            seam.drawing_no = product.drawing_no
        product.seams.append(seam)
        self.save(product)
        return True


class ConsumableRepository:
    """焊材库仓库（用户自定义焊材的 CRUD，持久化到 SQLite）。

    系统内置焊材从 YAML 加载（只读），用户添加的焊材存库。
    两者在标准 profile 的 all_consumables() 中合并查询（详见块4）。
    """

    def __init__(self, session: Session):
        self.session = session

    def _to_orm(self, c: Consumable, orm: ConsumableORM | None = None) -> ConsumableORM:
        if orm is None:
            orm = ConsumableORM()
        orm.brand = c.brand
        orm.model = c.model
        orm.type = c.type.value
        orm.classification_slot = c.classification_slot
        orm.standard = c.standard
        orm.diameter = c.diameter
        orm.applicable_groups = list(c.applicable_groups)
        orm.price = c.price
        orm.processes = list(c.processes)
        orm.remark = c.remark
        orm.is_builtin = False  # 用户经此仓库保存的均为自定义
        return orm

    def _from_orm(self, orm: ConsumableORM) -> Consumable:
        return Consumable(
            brand=orm.brand,
            model=orm.model,
            type=ConsumableType(orm.type),
            classification_slot=orm.classification_slot,
            standard=orm.standard or "",
            diameter=orm.diameter,
            applicable_groups=list(orm.applicable_groups or []),
            price=orm.price or 0.0,
            processes=list(orm.processes or []),
            remark=orm.remark or "",
        )

    def list_all(self) -> list[Consumable]:
        stmt = select(ConsumableORM).order_by(ConsumableORM.brand)
        return [self._from_orm(o) for o in self.session.scalars(stmt).all()]

    def get(self, brand: str) -> Consumable | None:
        orm = self.session.scalar(
            select(ConsumableORM).where(ConsumableORM.brand == brand)
        )
        return self._from_orm(orm) if orm else None

    def save(self, c: Consumable) -> Consumable:
        """新增或更新焊材（按 brand 去重）。"""
        orm = self.session.scalar(
            select(ConsumableORM).where(ConsumableORM.brand == c.brand)
        )
        orm = self._to_orm(c, orm)
        self.session.add(orm)
        self.session.commit()
        return self._from_orm(orm)

    def delete(self, brand: str) -> bool:
        orm = self.session.scalar(
            select(ConsumableORM).where(ConsumableORM.brand == brand)
        )
        if orm is None:
            return False
        self.session.delete(orm)
        self.session.commit()
        return True
