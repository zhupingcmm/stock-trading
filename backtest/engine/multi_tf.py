"""多周期回测引擎：日线 data0 + 周线 data1（resampledata）。

适用场景：策略同时使用两个时间尺度的信号，例如：
  - 周线过滤趋势方向
  - 日线寻找入场时机
  （海龟多周期融合策略就是典型）

API 用法::

    cerebro, df = setup_multi_tf_cerebro(MultiTFTurtle, "510300.SH", ...)
    results = cerebro.run()
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


def setup_multi_tf_cerebro(
    strategy_class: Type,
    stock_code: str,
    start_date: str | None,
    end_date: str | None,
    storage: MysqlStorage | None = None,
    **strategy_kwargs,
) -> tuple[bt.Cerebro, "pd.DataFrame"]:
    """配置多周期 cerebro：日线 data0 + 周线 data1（resampledata）。

    返回 ``(cerebro, df)``。``storage`` 若传入则不关闭（调用方持有），
    None 时内部临时建连。
    """
    df = load_stock_data(stock_code, start_date, end_date, storage=storage)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class, **strategy_kwargs)
    # 日线：data0
    data_daily = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data_daily)
    # 周线：data1（从同一份日线数据 resample）
    data_weekly = bt.feeds.PandasData(dataname=df)
    cerebro.resampledata(data_weekly, timeframe=bt.TimeFrame.Weeks)

    cerebro.broker.setcash(BACKTEST_INITIAL_CASH)
    cerebro.broker.setcommission(commission=BACKTEST_COMMISSION)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=BACKTEST_POSITION_PCT)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    return cerebro, df
