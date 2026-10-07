"""因子层。

负责从原始数据计算选股指标。

- :class:`~selection.factors.financial.FinancialFactorComputer`：
  从 ``trade_stock_financial`` 拉数据并计算 5 项财务指标。
"""
from selection.factors.financial import (
    FactorPoolSummary,
    FinancialFactorComputer,
)

__all__ = ["FactorPoolSummary", "FinancialFactorComputer"]