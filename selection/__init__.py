"""选股模块。

流水线：因子计算 → 过滤 → 打分排序 → 策略编排。
"""
from selection.factors import FactorPoolSummary, FinancialFactorComputer
from selection.filters import FilterResult, ScoreThresholdFilter
from selection.ranking import (
    IndustryScoreRanker,
    IndustryScoreResult,
    pct_to_score,
)
from selection.strategies import IndustryFactorReport, IndustryFactorStrategy

__all__ = [
    "FactorPoolSummary",
    "FilterResult",
    "FinancialFactorComputer",
    "IndustryFactorReport",
    "IndustryFactorStrategy",
    "IndustryScoreRanker",
    "IndustryScoreResult",
    "ScoreThresholdFilter",
    "pct_to_score",
]