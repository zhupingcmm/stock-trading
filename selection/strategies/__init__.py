"""策略层：把因子 → 过滤 → 打分排序串成完整的选股流水线。

- :class:`~selection.strategies.industry_factor.IndustryFactorStrategy`：
  行业因子选股（原 ``多因子选股-筛选2.py`` 的项目化版本）。
"""
from selection.strategies.industry_factor import (
    IndustryFactorReport,
    IndustryFactorStrategy,
)

__all__ = ["IndustryFactorReport", "IndustryFactorStrategy"]