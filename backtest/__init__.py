"""回测模块。

基于 backtrader 引擎 + xtquant/MySQL 数据，输出收益与风险指标。

顶层 API::

    from backtest import load_stock_data, setup_cerebro, wrap_strategy, calc_metrics
    from backtest import print_strategy_metrics, print_summary_table, plot_backtest
    from backtest import load_strategies, get_strategy

CLI 入口::

    python -m scripts.run_backtest [--strategy KEY] [--stock 600519.SH]
"""
from backtest.engine import calc_metrics, load_stock_data, setup_cerebro, wrap_strategy
from backtest.reports import plot_backtest, print_strategy_metrics, print_summary_table
from backtest.strategies import get_strategy, load_strategies

__all__ = [
    "load_stock_data",
    "setup_cerebro",
    "wrap_strategy",
    "calc_metrics",
    "print_strategy_metrics",
    "print_summary_table",
    "plot_backtest",
    "load_strategies",
    "get_strategy",
]