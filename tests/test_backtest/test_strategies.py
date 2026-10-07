"""6 个内置策略 + 1 个 custom 示例的烟雾测试。

每个策略用最小合成 K 线跑一遍，确认 ``next()`` 不抛异常、产出
``_trade_log`` / ``_nav_log`` 字段。
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backtest.engine import calc_metrics, setup_cerebro, wrap_strategy
from backtest.engine import data as data_mod
from backtest.strategies import load_strategies


@pytest.fixture
def synthetic_ohlcv() -> pd.DataFrame:
    n = 200  # 双均线/布林带/RSI 等需要足够 warmup
    idx = pd.bdate_range(end=date(2025, 12, 31), periods=n)
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame({
        "open": close + rng.normal(0, 0.1, n),
        "high": close + np.abs(rng.normal(0, 0.2, n)),
        "low": close - np.abs(rng.normal(0, 0.2, n)),
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n),
    }, index=idx)
    df.index.name = "trade_date"
    return df


@pytest.fixture(autouse=True)
def _patch_load_data(monkeypatch, synthetic_ohlcv):
    """把 ``load_stock_data`` 替换成返回合成数据，避免依赖真实数据库。

    同样打在 ``backtest.engine.cerebro`` 这个引用方。
    """
    from backtest.engine import cerebro as cerebro_mod
    monkeypatch.setattr(cerebro_mod, "load_stock_data",
                        lambda *a, **k: synthetic_ohlcv.copy())


def _run(strategy_class) -> dict:
    wrapped = wrap_strategy(strategy_class)
    cerebro, df = setup_cerebro(wrapped, "TEST.X", None, None)
    strat = cerebro.run()[0]
    metrics = calc_metrics(cerebro, strat, df)
    assert hasattr(strat, "_trade_log")
    assert hasattr(strat, "_nav_log")
    assert len(strat._nav_log) > 0
    return metrics


# ---------- 所有策略都能跑通 ----------
def test_load_strategies_returns_builtin_keys():
    found = load_strategies()
    for key in ("double_ma", "macd", "rsi", "boll", "bias", "momentum",
                "macd_divergence"):
        assert key in found, f"missing strategy: {key}"


def test_double_ma_runs():
    from backtest.strategies.double_ma import Strategy
    m = _run(Strategy)
    assert m["trading_days"] == 200


def test_macd_runs():
    from backtest.strategies.macd import Strategy
    _run(Strategy)


def test_rsi_runs():
    from backtest.strategies.rsi import Strategy
    _run(Strategy)


def test_boll_runs():
    from backtest.strategies.boll import Strategy
    _run(Strategy)


def test_bias_runs():
    from backtest.strategies.bias import Strategy
    _run(Strategy)


def test_momentum_runs():
    from backtest.strategies.momentum import Strategy
    _run(Strategy)


def test_custom_macd_divergence_runs():
    from backtest.strategies.custom.macd_divergence import Strategy
    _run(Strategy)
