"""回测报告输出子包。

公开 API::

    from backtest.reports import print_strategy_metrics, print_summary_table, plot_backtest
"""
from backtest.reports.plotter import plot_backtest
from backtest.reports.printer import print_strategy_metrics, print_summary_table

__all__ = ["print_strategy_metrics", "print_summary_table", "plot_backtest"]
