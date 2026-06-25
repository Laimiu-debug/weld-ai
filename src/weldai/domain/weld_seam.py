"""焊缝识别追溯领域模型（GB/T 150 / TSG 21 要求）。

建立 产品图号 → 焊缝编号 → (WPS + 焊工钢印) 的追溯链，
用于压力容器产品质量证明文件和监检追溯。

TSG 21 要求：每条受压元件焊缝须可追溯到所用的焊接工艺(WPS)和施焊焊工。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .enums import JointType, Position


@dataclass
class WeldSeam:
    """单条焊缝记录。

    一个产品容器有多条焊缝，每条焊缝关联：
      - 所属产品（图号/编号）
      - 使用的 WPS 编号
      - 施焊焊工钢印号
      - 焊缝位置/类型/长度
    """

    seam_no: str                          # 焊缝编号（如 A1/B2/C1，按容器分版）
    product_no: str = ""                  # 产品编号
    drawing_no: str = ""                  # 产品图号
    wps_no: str = ""                      # 使用的 WPS 编号
    welder_stamp: str = ""                # 施焊焊工钢印号
    joint_type: JointType = JointType.BUTT  # 焊缝形式
    position: Position = Position.PLATE_1G  # 焊接位置
    length: float = 0.0                   # 焊缝长度 mm
    thickness: float = 0.0                # 母材厚度 mm
    weld_date: date | None = None         # 施焊日期
    ndt_result: str = ""                  # 无损检测结果（RT/UT 合格级别）
    remark: str = ""

    @property
    def is_main_seam(self) -> bool:
        """是否为主焊缝（A/B 类受压焊缝）。

        命名约定：A类(纵缝)/B类(环缝)为主焊缝，C/D类(角焊/接管)为次要。
        """
        return self.seam_no[:1].upper() in ("A", "B")


@dataclass
class Product:
    """产品（容器）容器：聚合多条焊缝。"""

    product_no: str                       # 产品编号（唯一）
    drawing_no: str = ""                  # 产品图号
    name: str = ""                        # 产品名称（如"分离器"）
    customer: str = ""                    # 客户/使用单位
    manufacture_date: date | None = None  # 制造日期
    seams: list[WeldSeam] = field(default_factory=list)

    @property
    def main_seam_count(self) -> int:
        """主焊缝(A/B类)数量。"""
        return sum(1 for s in self.seams if s.is_main_seam)

    @property
    def welder_count(self) -> int:
        """参与施焊的焊工数。"""
        return len({s.welder_stamp for s in self.seams if s.welder_stamp})

    @property
    def wps_count(self) -> int:
        """使用的WPS数量。"""
        return len({s.wps_no for s in self.seams if s.wps_no})

    def seam_by_no(self, seam_no: str) -> WeldSeam | None:
        """按焊缝编号查找。"""
        return next((s for s in self.seams if s.seam_no == seam_no), None)
