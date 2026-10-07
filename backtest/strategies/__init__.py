"""回测策略子包。

公开 API::

    from backtest.strategies import load_strategies, get_strategy

策略组织
--------
* ``backtest/strategies/*.py`` — 内置 6 个策略（双均线/MACD/RSI/布林带/乖离率/动量）
* ``backtest/strategies/custom/*.py`` — 用户自定义插件（自动加载）

每个策略文件必须含 ``STRATEGY_META`` 字典 + ``Strategy(bt.Strategy)`` 类。
"""
from backtest.strategies.base import get_strategy, load_strategies

__all__ = ["load_strategies", "get_strategy"]
