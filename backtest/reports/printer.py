"""回测报告打印。

* :func:`print_strategy_metrics` — 单策略指标两行块（与案例格式一致）
* :func:`print_summary_table` — 多策略汇总表 + 极值高亮
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from config.settings import BACKTEST_INITIAL_CASH


# 汇总表列定义：(metric_key, 显示列名)
SUMMARY_COLS = [
    ("label", "策略"),
    ("total_return", "总收益%"),
    ("annual_return", "年化%"),
    ("max_drawdown", "最大回撤%"),
    ("sharpe_ratio", "夏普"),
    ("calmar_ratio", "卡玛"),
    ("win_rate", "胜率%"),
    ("profit_loss_ratio", "盈亏比"),
    ("profit_factor", "利润因子"),
    ("total_trades", "交易次数"),
    ("benchmark_return", "基准%"),
]

# 控制台展示时需 ×100 的百分比键
PCT_KEYS = {"total_return", "annual_return", "max_drawdown", "win_rate", "benchmark_return"}


def _fmt_pct(x):
    if x is None:
        return "    N/A"
    return f"{x * 100:+8.2f}"


def print_strategy_metrics(metrics: dict, stock: str, start: str, end: str,
                           trading_days: int, label: str = "") -> None:
    """单策略两行指标打印，格式与 ``CASE-Backtrader回测`` 一致。"""
    if label:
        print(
            f"{label} | {stock} | {start} ~ {end} | {trading_days}个交易日"
        )
    print(
        f"  总收益: {metrics['total_return'] * 100:+.2f}% | "
        f"年化: {metrics['annual_return'] * 100:+.2f}% | "
        f"最大回撤: {metrics['max_drawdown'] * 100:.2f}% | "
        f"夏普: {metrics['sharpe_ratio']:.2f} | "
        f"卡玛: {metrics['calmar_ratio']:.2f}"
    )
    print(
        f"  交易: {metrics['total_trades']}次 | "
        f"胜率: {metrics['win_rate'] * 100:.1f}% | "
        f"盈亏比: {metrics['profit_loss_ratio']:.2f} | "
        f"利润因子: {metrics['profit_factor']:.2f} | "
        f"最大连亏: {metrics['max_consecutive_losses']}次"
    )
    print(f"  [基准] 买入持有: {metrics['benchmark_return'] * 100:+.2f}%")
    print(f"  [资金] 初始 {BACKTEST_INITIAL_CASH:,.0f} → 最终 {metrics['final_value']:,.0f}")


def _extract_row(metrics: dict) -> dict:
    row = {}
    for key, _ in SUMMARY_COLS:
        v = metrics.get(key)
        if v is None:
            row[key] = None
        elif key in PCT_KEYS:
            row[key] = v * 100
        else:
            row[key] = v
    return row


def print_summary_table(rows: Iterable[dict], stock: str, start: str, end: str) -> None:
    """打印多策略汇总表 + 最佳/最差高亮。"""
    rows = list(rows)
    if not rows:
        print("\n[汇总表] 没有可用结果。\n")
        return

    df = pd.DataFrame(rows).rename(columns=dict(SUMMARY_COLS))
    print("\n" + "=" * 100)
    print(f"  多策略回测汇总  |  标的: {stock}  |  窗口: {start} ~ {end}")
    print("=" * 100)
    print(df.to_string(index=False, float_format=lambda x: f"{x:>8.2f}"))
    print("=" * 100)

    def _pick(key: str, reverse: bool = False):
        valid = [r for r in rows if r.get(key) is not None]
        if not valid:
            return None
        return (max if reverse else min)(valid, key=lambda r: r[key])

    def _fmt(r, key: str) -> str:
        if r is None:
            return "N/A"
        return f"{r['label']} ({r[key]:+.2f})"

    print(f"  最佳总收益:    {_fmt(_pick('total_return', reverse=True), 'total_return')}")
    print(f"  最佳夏普比:    {_fmt(_pick('sharpe_ratio', reverse=True), 'sharpe_ratio')}")
    print(f"  最大回撤最小:  {_fmt(_pick('max_drawdown'), 'max_drawdown')}")
    print(f"  胜率最高:      {_fmt(_pick('win_rate', reverse=True), 'win_rate')}")
    print("=" * 100 + "\n")


# 暴露内部辅助函数给 tests / 高级用法
__all__ = [
    "SUMMARY_COLS",
    "print_strategy_metrics",
    "print_summary_table",
]
