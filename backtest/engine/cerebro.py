"""Cerebro 引擎配置。

统一注入：初始资金 / 手续费 / 仓位 + 三个分析器（Sharpe / DrawDown / TradeAnalyzer）。
"""
from __future__ import annotations

from typing import Type

import backtrader as bt

from backtest.engine.data import load_stock_data
from config.settings import (
    BACKTEST_COMMISSION,
    BACKTEST_INITIAL_CASH,
    BACKTEST_POSITION_PCT,
)
from data_collection.storage.mysql import MysqlStorage


def setup_cerebro(
    strategy_class: Type,
    stock_code: str,
    start_date: str | None,
    end_date: str | None,
    storage: MysqlStorage | None = None,
    **strategy_kwargs,
) -> tuple[bt.Cerebro, "pd.DataFrame"]:
    """配置并返回 ``(cerebro, df)``。

    调用方在 ``setup_cerebro`` 之外负责 ``cerebro.run()`` 与收尾；
    ``storage`` 若传入则不关闭（由调用方持有），None 时内部临时建连。
    """
    df = load_stock_data(stock_code, start_date, end_date, storage=storage)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class, **strategy_kwargs)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.broker.setcash(BACKTEST_INITIAL_CASH)
    cerebro.broker.setcommission(commission=BACKTEST_COMMISSION)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=BACKTEST_POSITION_PCT)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    return cerebro, df
