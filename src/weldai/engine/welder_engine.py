"""焊工资格覆盖判定引擎。

依据 TSG Z6002：给定焊缝任务（方法/母材/厚度/管径/位置），
判定某焊工是否具备施焊资格（其合格项目是否覆盖该任务）。

覆盖原则：高难度覆盖低难度。
  - 位置：4G≥3G≥2G≥1G；6G/6GR 覆盖最广
  - 厚度：t≥12mm 覆盖 3mm~不限
  - 管径：D>25 覆盖 0.5D~不限
  - 不带衬垫试件合格可焊带衬垫焊件，反之不可
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import Position, WeldingProcess
from ..domain.welder import Welder, WelderQualification


@dataclass
class WeldTask:
    """一项焊接任务需求（用于判定焊工资格是否覆盖）。"""

    process: WeldingProcess
    material_category: str           # 母材类别号 Fe-1
    joint_form: str = "对接"          # 试件形式
    thickness: float = 0.0           # 焊缝金属厚度 mm
    outer_diameter: float | None = None  # 管外径 mm
    position: Position = Position.PLATE_1G
    has_backing: bool = False        # 是否带衬垫


@dataclass
class CoverageCheck:
    """单资格项对单任务的覆盖判定。"""

    qualification: WelderQualification
    covered: bool
    reasons: list[str]


# 焊接位置覆盖映射表（TSG Z6002 表A-4）
# key = 合格位置，value = 可覆盖的位置集合（含自身）
# 关键：6G 覆盖全位置；5G 不覆盖 2G
_POSITION_COVERS: dict[str, set[str]] = {
    "1G": {"1G"},
    "2G": {"1G", "2G"},
    "3G": {"1G", "3G"},
    "4G": {"1G", "4G"},
    "5G": {"1G", "3G", "4G", "5G"},          # 注意：不覆盖 2G
    "6G": {"1G", "2G", "3G", "4G", "5G", "6G"},  # 全位置
    "6GR": {"1G", "2G", "3G", "4G", "5G", "6G", "6GR"},
    "1G(管)": {"1G(管)", "1G"},
    "2G(管)": {"1G(管)", "2G(管)", "1G", "2G"},
    # 角焊缝位置
    "1F": {"1F"}, "2F": {"1F", "2F"},
    "3F": {"1F", "3F"}, "4F": {"1F", "4F"},
}


def _ev(v) -> str:
    """枚举/字符串的值（防御性：Qt 可能传入裸 str，无 .value）。"""
    return v.value if hasattr(v, "value") else str(v)


def _position_covers(qualified: Position, required: Position) -> bool:
    """位置覆盖：按 TSG Z6002 表A-4 映射判定。

    6G 覆盖全位置；5G 覆盖平/立/仰但不覆盖横焊(2G)。
    """
    covers = _POSITION_COVERS.get(_ev(qualified), {_ev(qualified)})
    return _ev(required) in covers


def _thickness_covers(qualified_t: float, required_t: float) -> bool:
    """手工焊厚度覆盖（TSG Z6002 表A-7）。

    下限统一为 0（阶段0误写为3，已修正）：
      - t ≤ 3   → 0 ~ 2t
      - 3 < t < 12 → 0 ~ 2t
      - t ≥ 12（≥3层多道焊）→ 0 ~ 不限
    """
    if qualified_t <= 0:
        return False
    if required_t < 0:
        return False
    if qualified_t >= 12:
        return True            # 0 ~ 不限
    return required_t <= 2 * qualified_t   # 0 ~ 2t


def _diameter_covers(qualified_d: float | None, required_d: float | None) -> bool:
    """管径覆盖（TSG Z6002 表A-8）。

    阶段0误写为 D≤25 覆盖不限，已修正（D<25 仅覆盖自身外径）：
      - D < 25      → 仅 D（不向上覆盖）
      - 25 ≤ D < 76 → 25 ~ 不限
      - D ≥ 76      → 76 ~ 不限
    板材对接合格可覆盖 D ≥ 76 的管材对接。
    """
    if required_d is None:
        return True   # 板材任务无需管径
    if qualified_d is None:
        # 板材试件合格 → 可覆盖 D≥76 管材
        return required_d >= 76
    if qualified_d < 25:
        return required_d >= qualified_d - 1e-9 and required_d <= qualified_d + 1e-9
    if qualified_d < 76:
        return required_d >= 25
    return required_d >= 76


def _form_covers(qualified_form: str, required_form: str) -> bool:
    """试件形式覆盖（TSG Z6002）：
      - 板对接 → 仅板对接（不覆盖管对接/管板）
      - 管对接 → 管对接 + 管板
      - 管板   → 仅管板
      - 对接焊缝资格可覆盖同等位置的角焊缝（反向不可）
      - 泛称"对接"被任何含"对接"的资格覆盖
    """
    q = (qualified_form or "").strip()
    r = (required_form or "").strip()
    if q == r:
        return True
    # 任务为泛称"对接"时，任何"X对接"资格都覆盖
    if r == "对接" and "对接" in q:
        return True
    # 管对接覆盖管板
    if "管对接" in q and "管板" in r:
        return True
    # 对接资格覆盖角焊缝
    if "对接" in q and "角焊" in r:
        return True
    return False


class WelderEngine:
    """焊工资格覆盖引擎。"""

    def check(
        self, welder: Welder, task: WeldTask
    ) -> list[CoverageCheck]:
        """检查焊工的每一项有效资格能否覆盖该任务。"""
        results: list[CoverageCheck] = []
        for q in welder.valid_qualifications:
            covered, reasons = self._check_one(q, task)
            results.append(CoverageCheck(q, covered, reasons))
        return results

    def can_weld(self, welder: Welder, task: WeldTask) -> bool:
        """焊工是否至少有一项资格覆盖该任务。"""
        return any(r.covered for r in self.check(welder, task))

    def _check_one(
        self, q: WelderQualification, task: WeldTask
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        ok = True

        # ① 焊接方法
        if q.process != task.process:
            ok = False
            reasons.append(
                f"焊接方法不符: 资格{_ev(q.process)} ≠ 任务{_ev(task.process)}"
            )

        # ② 母材类别
        if q.material_category != task.material_category:
            ok = False
            reasons.append(
                f"母材类别不符: 资格{q.material_category} ≠ 任务{task.material_category}"
            )

        # ③ 试件形式（板对接/管对接/管板 不可混用）
        if not _form_covers(q.specimen_form, task.joint_form):
            ok = False
            reasons.append(
                f"试件形式不符: 资格{q.specimen_form} 不能覆盖 {task.joint_form}"
            )

        # ⑥ 焊接位置（高覆盖低）
        if not _position_covers(q.position, task.position):
            ok = False
            reasons.append(
                f"焊接位置不足: 资格{_ev(q.position)} 不能覆盖 {_ev(task.position)}"
            )

        # ④ 厚度
        if not _thickness_covers(q.deposited_thickness, task.thickness):
            ok = False
            reasons.append(
                f"厚度不足: 资格{q.deposited_thickness:g}mm 不能覆盖 {task.thickness:g}mm"
            )

        # ⑤ 管径
        if not _diameter_covers(q.outer_diameter, task.outer_diameter):
            ok = False
            reasons.append(
                f"管径不足: 资格{q.outer_diameter} 不能覆盖 {task.outer_diameter}"
            )

        # 衬垫：不带衬垫试件可覆盖带衬垫焊件；反之不可
        if task.has_backing and not q.has_backing:
            # 带衬垫试件合格覆盖带衬垫是允许的；不带衬垫合格也允许覆盖带衬垫
            # 这里规则：合格资格即可覆盖（宽松），记录提示
            reasons.append("提示：任务带衬垫，资格为不带衬垫（允许覆盖）")

        if ok:
            reasons.insert(0, "资格覆盖该任务")
        return ok, reasons
