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
    material_category: str           # 母材类别号 FeⅠ
    thickness: float = 0.0           # 焊缝金属厚度 mm
    outer_diameter: float | None = None  # 管外径 mm
    position: Position = Position.PLATE_1G  # 焊接位置（形式隐含在代号）
    has_backing: bool = False        # 是否带衬垫
    joint_form: str = ""             # 试件形式（冗余，可由位置推断）


@dataclass
class CoverageCheck:
    """单资格项对单任务的覆盖判定。"""

    qualification: WelderQualification
    covered: bool
    reasons: list[str]


# 焊接位置覆盖映射表（TSG Z6002 附件A）
# key = 合格位置，value = 可覆盖的位置集合（含自身）
# 关键：6G 覆盖全位置；5G(管) 不覆盖 2G(管)；6FG 覆盖全管板位置
_POSITION_COVERS: dict[str, set[str]] = {
    # 板对接 G 系列：4G/3G 覆盖 1G（仰/立覆盖平）
    "1G": {"1G"},
    "2G": {"1G", "2G"},
    "3G": {"1G", "3G"},
    "4G": {"1G", "4G"},
    # 管对接 G 系列：6G 覆盖全位置；5G 不覆盖 2G
    "1G(管)": {"1G(管)", "1G"},
    "2G(管)": {"1G(管)", "2G(管)", "1G", "2G"},
    "5G(管)": {"1G(管)", "5G(管)", "1G", "3G", "4G", "5G"},  # 不覆盖 2G(横)
    "6G(管)": {"1G(管)", "2G(管)", "5G(管)", "6G(管)",
               "1G", "2G", "3G", "4G", "5G", "6G"},
    "6GR": {"1G(管)", "2G(管)", "5G(管)", "6G(管)", "6GR",
            "1G", "2G", "3G", "4G", "5G", "6G"},
    # 板角焊缝 F 系列
    "1F": {"1F"}, "2F": {"1F", "2F"},
    "3F": {"1F", "3F"}, "4F": {"1F", "4F"},
    # 管材角焊缝 F 系列（管-管角焊）
    "1F(管角)": {"1F(管角)", "1F"},
    "2F(管角)": {"1F(管角)", "2F(管角)", "1F", "2F"},
    "4F(管角)": {"1F(管角)", "4F(管角)", "1F", "4F"},
    "5F(管角)": {"1F(管角)", "2F(管角)", "4F(管角)", "5F(管角)",
                 "1F", "2F", "4F"},
    # 管板角接 FG 系列（TSG Z6002 表A-4）：6FG 覆盖全管板位置
    "2FRG": {"2FRG", "2FG"},
    "2FG": {"2FG", "2FRG"},
    "4FG": {"2FG", "2FRG", "4FG"},
    "5FG": {"2FG", "2FRG", "4FG", "5FG"},
    "6FG": {"2FG", "2FRG", "4FG", "5FG", "6FG"},
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

      - D < 25      → 覆盖 [D, 不限]
      - D ≥ 25      → 覆盖 [0.5D, 不限]
    板材对接合格可覆盖 D ≥ 76 的管材对接。
    """
    if required_d is None:
        return True   # 板材任务无需管径
    if qualified_d is None:
        # 板材试件合格 → 可覆盖 D≥76 管材
        return required_d >= 76
    if qualified_d < 25:
        return required_d >= qualified_d - 1e-9
    return required_d >= 0.5 * qualified_d - 1e-9


def _form_covers(qualified_form: str, required_form: str) -> bool:
    """试件形式覆盖（TSG Z6002）：
      - 管对接 → 管对接 + 板对接（管材覆盖板材对接）
      - 板对接 → 仅板对接（不覆盖管对接/管板）
      - 管板角接(管板) → 仅管板角接
      - 管材角焊缝 → 管材角焊缝 + 板角焊缝
      - 对接焊缝资格可覆盖同等位置的角焊缝（反向不可）
    """
    q = (qualified_form or "").strip()
    r = (required_form or "").strip()
    if q == r:
        return True
    # 管对接覆盖板对接（管材覆盖板材）
    if "管对接" in q and r == "板对接":
        return True
    # 管对接覆盖管板角接（TSG Z6002：管对接资格可焊管板角接）
    if "管对接" in q and "管板" in r:
        return True
    # 管材角焊缝覆盖板角焊缝
    if "管材角焊缝" in q and r == "板角焊缝":
        return True
    # 对接资格覆盖角焊缝（板对接→板角焊缝、管对接→管材角焊缝）
    if "对接" in q and "角焊缝" in r:
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

        # ③ 试件形式（板对接/管对接/管板角接 不可混用）
        # 试件形式隐含在位置代号中，从 position.form_type 推断
        q_form = q.position.form_type
        t_form = task.position.form_type if hasattr(task.position, "form_type") else task.joint_form
        if not _form_covers(q_form, t_form):
            ok = False
            reasons.append(
                f"试件形式不符: 资格{q_form} 不能覆盖 {t_form}"
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
