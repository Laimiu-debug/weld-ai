"""焊工资格领域模型（依据 TSG Z6002）。

项目代号结构（手工焊）：①-②-③-④-⑤-⑥-⑦
    ① 焊接方法   ② 母材类别   ③ 试件形式   ④ 焊缝金属厚度
    ⑤ 管材外径   ⑥ 焊接位置   ⑦ 焊接工艺因素
母材类别(②)直接复用 NB/T 47014 分类体系。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .enums import Position, WeldingProcess


@dataclass
class WelderQualification:
    """单项合格资格（对应一个项目代号）。

    seven-element 字段化存储 ①-⑦，便于覆盖判定与组合成项目代号字符串。
    """

    process: WeldingProcess          # ① 焊接方法
    material_category: str           # ② 母材类别号，如 "Fe-1"（复用 NB/T 47014）
    specimen_form: str               # ③ 试件形式，如 "板对接"/"管对接"/"管板"
    deposited_thickness: float       # ④ 焊缝金属厚度 mm
    outer_diameter: float | None = None  # ⑤ 管材外径 mm（板材试件为 None）
    position: Position = Position.PLATE_1G  # ⑥ 焊接位置
    process_factor: str = ""         # ⑦ 焊接工艺因素代号，如 "Fef3J"
    has_backing: bool = False        # 是否带衬垫（影响覆盖：不衬垫覆盖衬垫，反之不可）
    qualified_date: date | None = None    # 合格日期
    expire_date: date | None = None       # 到期日（有效期 4 年）

    @property
    def is_expired(self) -> bool:
        return self.expire_date is not None and date.today() > self.expire_date

    @property
    def project_code(self) -> str:
        """生成项目代号字符串 ①-②-③-④(/⑤)-⑥-⑦（TSG Z6002 格式）。"""
        parts = [
            self.process.value,                 # ① 焊接方法
            self.material_category,             # ② 母材类别
            self.specimen_form,                 # ③ 试件形式
        ]
        # ④厚度(/⑤管径)
        size = f"{_fmt(self.deposited_thickness)}"
        if self.outer_diameter is not None:
            size += f"/{_fmt(self.outer_diameter)}"
        parts.append(size)
        # ⑥位置（带衬垫加 K）
        pos = self.position.value
        if self.has_backing:
            pos += "(K)"
        parts.append(pos)
        # ⑦工艺因素
        if self.process_factor:
            parts.append(self.process_factor)
        return "-".join(str(p) for p in parts)

    @property
    def days_to_expire(self) -> int | None:
        """距到期日天数（负数表示已过期）。None 表示无到期日。"""
        if self.expire_date is None:
            return None
        return (self.expire_date - date.today()).days


@dataclass
class RenewalRecord:
    """复审记录。"""

    renewal_date: date
    renewal_type: str = "首次"   # 首次/延期/抽考
    result: str = "合格"          # 合格/不合格
    remark: str = ""


@dataclass
class Welder:
    """焊工档案。钢印号唯一，与证书号对应，用于焊缝质量追溯。"""

    stamp_no: str                       # 钢印号（唯一）
    cert_no: str = ""                   # 证书号
    name: str = ""                      # 姓名
    birth_date: date | None = None      # 出生日期（2026 版：初取证≤63，复审至 65）
    qualifications: list[WelderQualification] = field(default_factory=list)
    renewals: list[RenewalRecord] = field(default_factory=list)
    last_work_date: date | None = None  # 最近一次施焊日期（用于6个月中断判定）
    status: str = "有效"                 # 有效/暂停/失效

    # 预警阈值（2026版）
    CERT_VALID_YEARS = 4                # 证书有效期 4 年
    RENEWAL_WARN_MONTHS = 6             # 到期前6个月开始预警
    INTERRUPT_MONTHS = 6                # 连续中断6个月需重新考核
    MAX_AGE_INITIAL = 63                # 初次取证年龄上限
    MAX_AGE_RENEWAL = 65                # 复审后年龄上限

    @property
    def valid_qualifications(self) -> list[WelderQualification]:
        """当前有效的合格项目（未过期）。"""
        return [q for q in self.qualifications if not q.is_expired]

    @property
    def age(self) -> int | None:
        """当前年龄（周岁）。"""
        if self.birth_date is None:
            return None
        today = date.today()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    @property
    def expiring_qualifications(self) -> list[WelderQualification]:
        """即将到期（6个月内）的有效资格。"""
        return [
            q for q in self.valid_qualifications
            if q.days_to_expire is not None and 0 <= q.days_to_expire
            <= self.RENEWAL_WARN_MONTHS * 30
        ]

    @property
    def is_interrupted(self) -> bool:
        """是否连续中断作业超过6个月（需重新考核）。

        判定依据：最近一次施焊日期距今天超过6个月。
        无施焊记录时无法判定（返回 False）。
        """
        if self.last_work_date is None:
            return False
        days = (date.today() - self.last_work_date).days
        return days > self.INTERRUPT_MONTHS * 30

    def alerts(self) -> list[str]:
        """生成全部预警信息列表（用于界面提示）。"""
        alerts: list[str] = []
        # 到期预警
        for q in self.expiring_qualifications:
            alerts.append(
                f"资格 {q.project_code} 将于 {q.expire_date} 到期"
                f"（剩 {q.days_to_expire} 天），请及时复审"
            )
        for q in self.qualifications:
            if q.is_expired:
                alerts.append(f"资格 {q.project_code} 已过期（{q.expire_date}）")
        # 中断预警
        if self.is_interrupted:
            alerts.append(
                f"连续中断作业超 {self.INTERRUPT_MONTHS} 个月"
                f"（最近施焊 {self.last_work_date}），复工前须重新考核"
            )
        # 年龄预警
        age = self.age
        if age is not None and age >= self.MAX_AGE_RENEWAL:
            alerts.append(f"年龄 {age} 岁已达复审上限 {self.MAX_AGE_RENEWAL} 岁")
        return alerts


def _fmt(v: float) -> str:
    """格式化数值：整数去小数点。"""
    if v == int(v):
        return str(int(v))
    return f"{v:g}"
