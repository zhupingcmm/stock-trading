"""回测引擎子包。

对外暴露最小 API::

    from backtest.engine import setup_cerebro, wrap_strategy, calc_metrics, load_stock_data
"""
from backtest.engine.cerebro import setup_cerebro
from backtest.engine.data import load_stock_data
from backtest.engine.metrics import calc_metrics
from backtest.engine.wrapper import wrap_strategy

__all__ = ["setup_cerebro", "wrap_strategy", "calc_metrics", "load_stock_data"]
