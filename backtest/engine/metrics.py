"""回测绩效计算。

从 backtrader 的 analyzers + 包装器记录的净值序列中提取完整指标。
"""
from __future__ import annotations

from typing import Any

import backtrader as bt
import pandas as pd

from config.settings import BACKTEST_INITIAL_CASH

# 一年交易日数（A 股）
TRADING_DAYS_PER_YEAR = 252


def _calc_max_consecutive_losses(ta: dict) -> int:
    streak = ta.get("streak", {})
    lost = streak.get("lost", {})
    return lost.get("longest", 0) if lost else 0


def calc_metrics(cerebro: bt.Cerebro, strat: bt.Strategy, df: pd.DataFrame) -> dict[str, Any]:
    """提取完整绩效指标字典。"""
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - BACKTEST_INITIAL_CASH) / BACKTEST_INITIAL_CASH

    trading_days = len(df)
    years = trading_days / TRADING_DAYS_PER_YEAR
    if years > 0 and total_return > -1:
        annual_return = (1 + total_return) ** (1 / years) - 1
    else:
        annual_return = total_return

    sharpe_ratio = (
        strat.analyzers.sharpe.get_analysis().get("sharperatio", 0) or 0
    )

    # 最大回撤：优先用净值序列计算（避免 backtrader 在异常情况下返回 > 100%）
    max_drawdown = 0.0
    max_dd_len = 0
    nav_log = getattr(strat, "_nav_log", [])
    if nav_log:
        navs = [x["nav"] for x in nav_log]
        peak = navs[0]
        dd_len = 0
        for v in navs:
            if v > peak:
                peak = v
                dd_len = 0
            else:
                dd_len += 1
                if peak > 0 and v > 0:
                    dd_pct = (peak - v) / peak
                    # 长仓策略回撤不超过 100%，异常值截断
                    max_drawdown = max(max_drawdown, min(dd_pct, 1.0))
                max_dd_len = max(max_dd_len, dd_len)
    if not nav_log:
        dd = strat.analyzers.drawdown.get_analysis()
        bt_dd = dd.get("max", {}).get("drawdown", 0) / 100
        max_drawdown = min(bt_dd, 1.0)
        max_dd_len = dd.get("max", {}).get("len", 0)

    calmar_ratio = annual_return / max_drawdown if max_drawdown > 0 else 0

    # 交易统计
    ta = strat.analyzers.trades.get_analysis()
    total_trades = ta.get("total", {}).get("total", 0)
    won_trades = ta.get("won", {}).get("total", 0)
    lost_trades = ta.get("lost", {}).get("total", 0)
    win_rate = won_trades / total_trades if total_trades > 0 else 0

    avg_win = ta.get("won", {}).get("pnl", {}).get("average", 0) or 0
    avg_loss = ta.get("lost", {}).get("pnl", {}).get("average", 0) or 0
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    gross_profit = ta.get("won", {}).get("pnl", {}).get("total", 0) or 0
    gross_loss = ta.get("lost", {}).get("pnl", {}).get("total", 0) or 0
    profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else 0

    max_consecutive_losses = _calc_max_consecutive_losses(ta)
    expected_value = (
        win_rate * avg_win + (1 - win_rate) * avg_loss if total_trades > 0 else 0
    )

    # 买入持有基准
    valid_close = df["close"][df["close"] > 0]
    if len(valid_close) >= 2:
        close_start = float(valid_close.iloc[0])
        close_end = float(valid_close.iloc[-1])
        benchmark_return = (close_end / close_start - 1) if close_start > 0 else 0
    else:
        benchmark_return = 0

    return {
        "final_value": round(final_value, 2),
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "max_dd_len": max_dd_len,
        "sharpe_ratio": round(sharpe_ratio, 4),
        "calmar_ratio": round(calmar_ratio, 4),
        "total_trades": total_trades,
        "won_trades": won_trades,
        "lost_trades": lost_trades,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "profit_factor": round(profit_factor, 2),
        "max_consecutive_losses": max_consecutive_losses,
        "expected_value": round(expected_value, 2),
        "years": round(years, 2),
        "trading_days": trading_days,
        "benchmark_return": benchmark_return,
    }
