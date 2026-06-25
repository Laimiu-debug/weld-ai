"""weldAI 规则引擎层。

核心壁垒：因素变更判定、覆盖范围计算、焊工资格覆盖、成本计算、AI辅助。
与具体标准解耦，通过注入 StandardProfile 工作。
"""
from .actions import Action, FactorChange, decide_action
from .ai_engine import ParameterAdvisor, Recommendation, WPSDeriver, DerivationReport
from .cost_engine import CostEngine, CostSchemeComparison
from .coverage_engine import CoverageEngine, CoverageResult
from .factor_engine import FactorEngine, QualificationResult
from .pqr_matcher import MatchDimension, PQRMatcher, PQRSuitability, WeldRequirement
from .welder_engine import WeldTask, WelderEngine

__all__ = [
    "Action",
    "FactorChange",
    "decide_action",
    "FactorEngine",
    "QualificationResult",
    "CoverageEngine",
    "CoverageResult",
    "WelderEngine",
    "WeldTask",
    "CostEngine",
    "CostSchemeComparison",
    "WPSDeriver",
    "DerivationReport",
    "ParameterAdvisor",
    "Recommendation",
    "PQRMatcher",
    "WeldRequirement",
    "PQRSuitability",
    "MatchDimension",
]
