"""SQLAlchemy ORM 模型。

阶段0 只建立核心表的骨架（母材、焊材、工艺文件、焊工），字段与领域实体对应。
完整的关系约束与索引在阶段1细化。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BaseMetalORM(Base):
    __tablename__ = "base_metals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grade: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16), index=True)
    group: Mapped[str] = mapped_column(String(16), index=True)
    standard: Mapped[str] = mapped_column(String(64), default="")
    yield_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    tensile_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    remark: Mapped[str] = mapped_column(Text, default="")


class ConsumableORM(Base):
    __tablename__ = "consumables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(32))
    classification_slot: Mapped[str] = mapped_column(String(64), index=True)
    standard: Mapped[str] = mapped_column(String(64), default="")
    diameter: Mapped[float | None] = mapped_column(Float, nullable=True)
    applicable_groups: Mapped[list] = mapped_column(JSON, default=list)
    price: Mapped[float] = mapped_column(Float, default=0.0)  # 参考单价 元/kg
    processes: Mapped[list] = mapped_column(JSON, default=list)  # 适用焊接方法代号
    remark: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否内置(YAML)


class ProcedureORM(Base):
    """工艺文件（pWPS/WPS/PQR）主表。"""

    __tablename__ = "procedures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    process: Mapped[str] = mapped_column(String(16))
    mechanization: Mapped[str] = mapped_column(String(16), default="manual")
    supporting_pqr_no: Mapped[str] = mapped_column(String(64), default="")
    standard_version: Mapped[str] = mapped_column(String(32), default="")
    impact_required: Mapped[bool] = mapped_column(Boolean, default=False)
    # 复杂子结构（母材/焊材/焊道）阶段1拆分到子表，阶段0用 JSON 存
    base_metals: Mapped[list] = mapped_column(JSON, default=list)
    consumables: Mapped[list] = mapped_column(JSON, default=list)
    passes: Mapped[list] = mapped_column(JSON, default=list)
    joints: Mapped[list] = mapped_column(JSON, default=list)
    positions: Mapped[list] = mapped_column(JSON, default=list)
    preheat_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    pwht: Mapped[dict] = mapped_column(JSON, default=dict)
    deposited_thickness: Mapped[float | None] = mapped_column(Float, nullable=True)
    doc_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    remark: Mapped[str] = mapped_column(Text, default="")

    passes_rel: Mapped[list["PassLayerORM"]] = relationship(
        back_populates="procedure", cascade="all, delete-orphan"
    )


class PassLayerORM(Base):
    __tablename__ = "pass_layers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    procedure_id: Mapped[int] = mapped_column(ForeignKey("procedures.id"))
    procedure: Mapped[ProcedureORM] = relationship(back_populates="passes_rel")
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    layer_role: Mapped[str] = mapped_column(String(32), default="填充")
    diameter: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gas_type: Mapped[str] = mapped_column(String(64), default="")


class WelderORM(Base):
    __tablename__ = "welders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stamp_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    cert_no: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(64), default="")
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="有效")
    last_work_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    qualifications: Mapped[list] = mapped_column(JSON, default=list)
    renewals: Mapped[list] = mapped_column(JSON, default=list)


class ProductORM(Base):
    """产品（容器）— 焊缝追溯聚合根。"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    drawing_no: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(128), default="")
    customer: Mapped[str] = mapped_column(String(128), default="")
    manufacture_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    seams: Mapped[list] = mapped_column(JSON, default=list)  # WeldSeam 序列化列表
    remark: Mapped[str] = mapped_column(Text, default="")

