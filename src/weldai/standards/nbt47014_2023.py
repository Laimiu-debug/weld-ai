"""NB/T 47014-2023《承压设备焊接工艺评定》标准实现。

规则数据从 standards/data/nbt47014_2023/*.yaml 加载（数据驱动）。
本类只承载规则逻辑，不含硬编码数据。
"""
from __future__ import annotations

import ast

from ..domain.base_metal import BaseMetal
from ..domain.consumable import Consumable, ConsumableType
from ..domain.enums import (
    DiameterRange,
    FactorLevel,
    MaterialGroup,
    Position,
    ThicknessRange,
    WeldingProcess,
)
from .base import FactorDef, StandardProfile
from .loader import load_standard_data

_REGISTRY_KEY = "nbt47014_2023"
_STANDARD_CODE = "NB/T 47014-2023"


class NBT47014_2023Profile(StandardProfile):
    """NB/T 47014-2023 标准配置。

    关键规则（数据来自 YAML，逻辑在此）：
      - 母材：同类高组别覆盖低组别；跨类一般重新评定
      - 焊材：分类栏位跨栏 → 重要因素
      - 厚度：按试件厚度分段（表7）
      - 位置：高难度覆盖低难度（向上立焊为补加因素，需单独评定）
    """

    def __init__(self) -> None:
        self._base_metals: dict[str, BaseMetal] = {}
        self._factors: dict[WeldingProcess, dict[str, FactorDef]] = {}
        self._factors_by_category: dict[WeldingProcess, dict[str, FactorDef]] = {}
        self._thickness_rules: list[dict] = []
        self._deposited_thickness_rules: list[dict] = []
        self._diameter_rules: list[dict] = []
        self._position_covers: dict[str, list[str]] = {}
        self._metal_coverage_policy: dict[str, str] = {}
        self._consumables: dict[str, Consumable] = {}
        self._load_data()

    # ----- 数据加载 ------------------------------------------------------

    def _load_data(self) -> None:
        # 母材
        bm_data = load_standard_data(_REGISTRY_KEY, "base_metals.yaml")
        for entry in bm_data.get("base_metals", []):
            group = MaterialGroup(
                family=entry["family"],
                category=entry["category"],
                group=entry.get("group", entry["category"]),
            )
            metal = BaseMetal(
                grade=str(entry["grade"]),
                group=group,
                standard=entry.get("standard", ""),
                tensile_strength=entry.get("tensile_strength"),
                yield_strength=entry.get("yield_strength"),
                remark=entry.get("remark", ""),
            )
            if metal.grade in self._base_metals:
                import warnings
                warnings.warn(
                    f"母材牌号重复(后者覆盖前者): {metal.grade} "
                    f"[{self._base_metals[metal.grade].group.group} → {group.group}]",
                    stacklevel=2,
                )
            self._base_metals[metal.grade] = metal

        # 焊材
        cons_data = load_standard_data(_REGISTRY_KEY, "consumables.yaml")
        for entry in cons_data.get("consumables", []):
            ctype = ConsumableType(entry["type"])
            cons = Consumable(
                brand=entry["brand"],
                model=entry["model"],
                type=ctype,
                classification_slot=entry["classification_slot"],
                standard=entry.get("standard", ""),
                diameter=entry.get("diameter"),
                applicable_groups=entry.get("applicable_groups", []),
                remark=entry.get("remark", ""),
            )
            # 以牌号为键（牌号唯一），型号可重复
            self._consumables[cons.brand] = cons

        # 因素表（按焊接方法分文件）
        factor_files = {
            WeldingProcess.SMAW: "factors_smaw.yaml",
            WeldingProcess.GTAW: "factors_gtaw.yaml",
            WeldingProcess.SAW: "factors_saw.yaml",
            WeldingProcess.GMAW: "factors_gmaw.yaml",
            WeldingProcess.FCAW: "factors_gmaw.yaml",  # 2023版 FCAW 并入 GMAW
            WeldingProcess.PAW: "factors_paw.yaml",
            WeldingProcess.EGW: "factors_egw.yaml",
            WeldingProcess.EBW: "factors_ebw.yaml",
        }
        for proc, fname in factor_files.items():
            try:
                fdata = load_standard_data(_REGISTRY_KEY, fname)
            except FileNotFoundError:
                continue
            self._factors[proc] = {}
            self._factors_by_category[proc] = {}
            for f in fdata.get("factors", []):
                level = FactorLevel(f["level"])
                category = f.get("category", "")
                fdef = FactorDef(
                    factor_id=f["id"],
                    name=f["name"],
                    level=level,
                    category=category,
                    invalidate_when=f.get("invalidate_when", []),
                    note=f.get("note", ""),
                )
                self._factors[proc][f["id"]] = fdef
                if category:
                    self._factors_by_category[proc][category] = fdef

        # 覆盖规则
        cov = load_standard_data(_REGISTRY_KEY, "coverage_rules.yaml")
        self._thickness_rules = cov.get("thickness", {}).get("rules", [])
        self._deposited_thickness_rules = cov.get("deposited_thickness", {}).get("rules", [])
        self._diameter_rules = cov.get("diameter", {}).get("rules", [])
        self._position_covers = cov.get("position", {})
        self._metal_coverage_policy = cov.get("base_metal_coverage", {})

    # ----- StandardProfile 标识 -----------------------------------------

    @property
    def standard_code(self) -> str:
        return _STANDARD_CODE

    @property
    def registry_key(self) -> str:
        return _REGISTRY_KEY

    # ----- 母材 ----------------------------------------------------------

    def get_base_metal(self, grade: str) -> BaseMetal | None:
        return self._base_metals.get(grade)

    def all_base_metals(self) -> list[BaseMetal]:
        return list(self._base_metals.values())

    def base_metal_covers(
        self, qualified_group: str, target_group: str
    ) -> bool:
        """母材类组覆盖判定。

        qualified_group / target_group 形如 'Fe-1-2'。
        规则：
          1. 完全相同 → 覆盖
          2. 同类别号下，按该类别的覆盖策略判定：
             - progressive：组别递进，高组别覆盖低组别（如 Fe-1 强度递进）
             - parallel：组别并列，互不覆盖（如 Fe-8-1/8-2 成分区分）
          3. 跨类别号 → 不覆盖（需重新评定）
        """
        if qualified_group == target_group:
            return True
        qfam, qcat, qgrp = _split_group(qualified_group)
        tfam, tcat, tgrp = _split_group(target_group)
        # 跨大类或跨类别号 → 不覆盖
        if qfam != tfam or qcat != tcat:
            return False
        # 同类别号：按策略判定
        policy = self._metal_coverage_policy.get(qcat,
                    self._metal_coverage_policy.get("default", "parallel"))
        if policy == "progressive":
            return qgrp >= tgrp
        # parallel / none：并列或同组（已在开头处理完全相同），互不覆盖
        return False

    # ----- 焊材 ----------------------------------------------------------

    def consumable_slot_changed(
        self, qualified_slot: str, target_slot: str
    ) -> bool:
        """焊材分类栏位变更判定。栏位相同 → 未变更（不触发重要因素）。"""
        return qualified_slot.strip() != target_slot.strip()

    def get_consumable(self, brand: str) -> Consumable | None:
        """按牌号查焊材。"""
        return self._consumables.get(brand)

    def all_consumables(self) -> list[Consumable]:
        """全部焊材（按牌号排序）。"""
        return sorted(self._consumables.values(), key=lambda c: c.brand)

    def consumables_for_group(self, group: str) -> list[Consumable]:
        """查适用某母材类组的焊材。"""
        return [
            c for c in self._consumables.values()
            if group in c.applicable_groups
        ]

    # ----- 焊接工艺评定因素 ----------------------------------------------

    def get_factors(self, process: WeldingProcess) -> list[FactorDef]:
        return list(self._factors.get(process, {}).values())

    def get_factor(
        self, process: WeldingProcess, factor_id: str
    ) -> FactorDef | None:
        return self._factors.get(process, {}).get(factor_id)

    def get_factor_by_category(
        self, process: WeldingProcess, category: str
    ) -> FactorDef | None:
        """按语义键查因素（跨方法稳定）。"""
        return self._factors_by_category.get(process, {}).get(category)

    # ----- 覆盖范围 ------------------------------------------------------

    def coverage_thickness(
        self, coupon_t: float, impact_required: bool = False
    ) -> ThicknessRange:
        return _eval_thickness_rules(self._thickness_rules, coupon_t,
                                     impact_required)

    def coverage_deposited_thickness(
        self, coupon_t: float, impact_required: bool = False
    ) -> ThicknessRange:
        rules = self._deposited_thickness_rules or self._thickness_rules
        return _eval_thickness_rules(rules, coupon_t, impact_required)

    def coverage_diameter(self, coupon_d: float) -> DiameterRange:
        lo, hi = _eval_rules(self._diameter_rules, coupon_d, "d")
        return DiameterRange(min_d=lo, max_d=hi)

    def coverage_positions(self, qualified: Position) -> list[Position]:
        """焊接位置覆盖：合格位置覆盖其本身及更低难度位置。"""
        covers_raw = self._position_covers.get("covers", {})
        covered_strs = covers_raw.get(qualified.value, [qualified.value])
        result: list[Position] = []
        for s in covered_strs:
            try:
                result.append(Position(s))
            except ValueError:
                continue
        return result


# ---------------------------------------------------------------------------
# 辅助函数：解析类组号、求值覆盖规则表达式
# ---------------------------------------------------------------------------

def _split_group(group: str) -> tuple[str, str, int]:
    """拆分类组号 'Fe-1-2' → ('Fe', 'Fe-1', 2)。

    无组别细分时（如 'Fe-8'）→ ('Fe', 'Fe-8', 0)。
    """
    parts = group.split("-")
    family = parts[0]                          # Fe
    category = f"{parts[0]}-{parts[1]}"        # Fe-1
    grp_num = int(parts[2]) if len(parts) > 2 else 0
    return family, category, grp_num


# 表达式安全求值：仅允许算术运算与内建函数 min/max/abs
_SAFE_FUNCS = {
    "min": min, "max": max, "abs": abs,
    "round": round, "int": int, "float": float,
}
_SAFE_CONSTS = {"inf": float("inf"), "True": True, "False": False, "true": True, "false": False}


class _RuleEvaluator(ast.NodeVisitor):
    """基于 AST 的安全算术表达式求值器（替代 eval）。

    仅允许：常数、名字(变量/常量)、算术运算、比较、布尔运算、
    三元表达式(IfExp)和白名单函数调用(min/max/abs/round/int/float)。
    拒绝：属性访问、下标、推导式、任意函数、lambda 等可逃逸构造。
    """

    def __init__(self, variables: dict):
        self.vars = variables

    def visit(self, node):
        return super().visit(node)

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        return node.value

    def visit_Name(self, node):
        n = node.id
        if n in self.vars:
            return self.vars[n]
        if n in _SAFE_CONSTS:
            return _SAFE_CONSTS[n]
        raise NameError(f"规则中含未定义变量: {n}")

    def visit_BoolOp(self, node):
        vals = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            result = True
            for v in vals:
                result = result and v
            return result
        result = False
        for v in vals:
            result = result or v
        return result

    def visit_UnaryOp(self, node):
        operand = self.visit(node.operand)
        op = node.op
        if isinstance(op, ast.USub):
            return -operand
        if isinstance(op, ast.UAdd):
            return +operand
        if isinstance(op, ast.Not):
            return not operand
        raise ValueError(f"不支持的一元运算: {type(op).__name__}")

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.FloorDiv):
            return left // right
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.Pow):
            return left ** right
        raise ValueError(f"不支持的二元运算: {type(op).__name__}")

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comp in zip(node.ops, node.comparators):
            right = self.visit(comp)
            if isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            else:
                raise ValueError(f"不支持的比较: {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True

    def visit_IfExp(self, node):
        """三元表达式 a if cond else b（用于冲击约束）。"""
        if self.visit(node.test):
            return self.visit(node.body)
        return self.visit(node.orelse)

    def visit_Call(self, node):
        func_name = node.func.id if isinstance(node.func, ast.Name) else None
        if func_name not in _SAFE_FUNCS:
            raise ValueError(f"不支持的函数调用: {func_name}")
        args = [self.visit(a) for a in node.args]
        return _SAFE_FUNCS[func_name](*args)

    def generic_visit(self, node):
        raise ValueError(f"规则含不允许的表达式: {type(node).__name__}")


def _safe_eval(expr: str, variables: dict) -> float | bool:
    """基于 AST 的安全求值（替代 eval）。

    仅允许算术/比较/布尔/三元/白名单函数，杜绝任意代码执行。
    """
    tree = ast.parse(str(expr), "<rule>", "eval")
    return _RuleEvaluator(variables).visit(tree)


def _eval_rules(
    rules: list[dict], value: float, var_name: str,
    impact: bool = False,
) -> tuple[float, float | None]:
    """通用规则求值：按 if 条件分段，命中后返回 (min, max)。

    变量 ``t`` / ``d`` 取 value，``impact`` 取冲击标志(0/1)，
    均作为真实变量名直接传入（不做字符串替换，避免破坏含 t 的标识符）。
    """
    ctx = {"t": value, "d": value, "impact": 1 if impact else 0}
    for rule in rules:
        try:
            if _safe_eval(rule["if"], ctx):
                then = rule["then"]
                lo = _eval_bound(then.get("min"), ctx)
                hi = _eval_bound(then.get("max"), ctx)
                return lo, hi
        except (ValueError, NameError, SyntaxError, ZeroDivisionError,
                KeyError, TypeError) as e:
            import warnings
            warnings.warn(
                f"覆盖规则求值失败，已跳过: if={rule.get('if')!r} 错误={e}",
                stacklevel=2,
            )
            continue
    # 兜底：无命中规则，返回值本身区间
    return value, value


def _eval_bound(expr, ctx: dict[str, float]) -> float | None:
    """求值单个边界表达式（min/max）。None → None（不限）。"""
    if expr is None:
        return None
    if isinstance(expr, (int, float)):
        return float(expr)
    return float(_safe_eval(str(expr), ctx))


def _eval_thickness_rules(
    rules: list[dict], coupon_t: float, impact: bool = False
) -> ThicknessRange:
    lo, hi = _eval_rules(rules, coupon_t, "t", impact)
    return ThicknessRange(min_t=lo, max_t=hi)
