"""回测引擎基础测试。

不依赖真实数据库（fixture 用一个最小可用的 DataFrame）。
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest.engine import calc_metrics, setup_cerebro, wrap_strategy
from backtest.engine.metrics import TRADING_DAYS_PER_YEAR


# ---------- fixture ----------
@pytest.fixture
def tiny_ohlcv() -> pd.DataFrame:
    """~120 个交易日的合成 K 线，足够覆盖双均线/RSI 等指标的 warmup。"""
    n = 120
    idx = pd.bdate_range(end=date(2025, 12, 31), periods=n)
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close + np.random.randn(n) * 0.1,
        "high": close + np.abs(np.random.randn(n)) * 0.2,
        "low": close - np.abs(np.random.randn(n)) * 0.2,
        "close": close,
        "volume": np.random.randint(1_000_000, 5_000_000, n),
    }, index=idx)
    df.index.name = "trade_date"
    return df


@pytest.fixture(autouse=True)
def _patch_load_stock_data(monkeypatch, tiny_ohlcv):
    """把 ``load_stock_data`` 替换成返回合成数据，避免依赖真实数据库。

    注意：必须打在 ``backtest.engine.cerebro`` 这个**引用方**，
    因为 setup_cerebro 里 `from backtest.engine.data import load_stock_data`
    已经把符号绑死了。
    """
    from backtest.engine import cerebro as cerebro_mod
    monkeypatch.setattr(cerebro_mod, "load_stock_data",
                        lambda *a, **k: tiny_ohlcv.copy())


# ---------- 测试 ----------
def test_calc_metrics_keys_present():
    """指标字典包含关键字段。"""
    import backtrader as bt

    class AlwaysBuy(bt.Strategy):
        def next(self):
            if not self.position:
                self.buy()

    wrapped = wrap_strategy(AlwaysBuy)
    cerebro, df = setup_cerebro(wrapped, "TEST.X", None, None)
    strat = cerebro.run()[0]
    metrics = calc_metrics(cerebro, strat, df)

    expected = {"final_value", "total_return", "annual_return", "max_drawdown",
                "sharpe_ratio", "calmar_ratio", "total_trades",
                "win_rate", "profit_loss_ratio", "profit_factor",
                "benchmark_return", "trading_days", "years"}
    missing = expected - set(metrics)
    assert not missing, f"missing keys: {missing}"
    assert metrics["trading_days"] == 120


def test_trading_days_per_year_constant():
    assert TRADING_DAYS_PER_YEAR == 252


def test_setup_cerebro_runs_and_yields_metrics():
    """端到端冒烟：setup_cerebro 配置好后能完整跑出 Sharpe/DrawDown/TradeAnalyzer 指标。"""
    import backtrader as bt

    class AlwaysBuy(bt.Strategy):
        def next(self):
            if not self.position:
                self.buy()

    wrapped = wrap_strategy(AlwaysBuy)
    cerebro, df = setup_cerebro(wrapped, "TEST.X", None, None)
    strat = cerebro.run()[0]
    m = calc_metrics(cerebro, strat, df)

    # 三个分析器的输出都已落到 metrics dict 里
    assert m["sharpe_ratio"] is not None
    assert 0 <= m["max_drawdown"] <= 1.0
    assert m["total_trades"] >= 0

