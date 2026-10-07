"""回测报告打印。

* :func:`print_strategy_metrics` — 单策略指标两行块（与案例格式一致）
* :func:`print_summary_table` — 多策略汇总表 + 极值高亮（带边框）
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd
from tabulate import tabulate

from config.settings import BACKTEST_INITIAL_CASH


# 汇总表列定义：(metric_key, 显示列名, fmt)
#   fmt="pct_signed"  → "+12.34"     收益类，年化带正负号
#   fmt="pct"         → "12.34"      回撤 / 胜率，无正负号
#   fmt="num2"        → "1.23"       夏普 / 卡玛 / 盈亏比 / 利润因子，2 位小数
#   fmt="int"         → "12"         交易次数，整数
SUMMARY_COLS: list[tuple[str, str, str]] = [
    ("label",            "策略",      "label"),
    ("total_return",     "总收益%",   "pct_signed"),
    ("annual_return",    "年化%",     "pct_signed"),
    ("max_drawdown",     "最大回撤%", "pct"),
    ("sharpe_ratio",     "夏普",      "num2"),
    ("calmar_ratio",     "卡玛",      "num2"),
    ("win_rate",         "胜率%",     "pct"),
    ("profit_loss_ratio","盈亏比",    "num2"),
    ("profit_factor",    "利润因子",  "num2"),
    ("total_trades",     "交易次数",  "int"),
    ("benchmark_return", "基准%",     "pct_signed"),
]


def _fmt_cell(value, kind: str) -> str:
    """按列类型格式化单元格。"""
    if value is None:
        return "N/A"
    if kind == "label":
        return str(value)
    if kind == "pct_signed":
        return f"{value:+8.2f}"
    if kind == "pct":
        return f"{value:8.2f}"
    if kind == "num2":
        return f"{value:8.2f}"
    if kind == "int":
        return f"{int(value):d}"
    return str(value)


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
    """从 metrics dict 抽取汇总表所需的列（值已 ×100 化为百分比）。"""
    row = {}
    for key, _, _ in SUMMARY_COLS:
        v = metrics.get(key)
        if v is None:
            row[key] = None
        elif key in ("total_return", "annual_return", "max_drawdown",
                     "win_rate", "benchmark_return"):
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

    headers = [col_name for _, col_name, _ in SUMMARY_COLS]
    table = [
        [_fmt_cell(r.get(key), kind) for key, _, kind in SUMMARY_COLS]
        for r in rows
    ]

    print()
    print(f"  多策略回测汇总  |  标的: {stock}  |  窗口: {start} ~ {end}")
    print(tabulate(table, headers=headers, tablefmt="grid", numalign="right"))

    def _pick(key: str, reverse: bool = False):
        valid = [r for r in rows if r.get(key) is not None]
        if not valid:
            return None
        return (max if reverse else min)(valid, key=lambda r: r[key])

    def _fmt(r, key: str) -> str:
        if r is None:
            return "N/A"
        return f"{r['label']} ({r[key]:+.2f})"

    print()
    print(f"  最佳总收益:    {_fmt(_pick('total_return', reverse=True), 'total_return')}")
    print(f"  最佳夏普比:    {_fmt(_pick('sharpe_ratio', reverse=True), 'sharpe_ratio')}")
    print(f"  最大回撤最小:  {_fmt(_pick('max_drawdown'), 'max_drawdown')}")
    print(f"  胜率最高:      {_fmt(_pick('win_rate', reverse=True), 'win_rate')}")
    print()


# 暴露内部辅助函数给 tests / 高级用法
__all__ = [
    "SUMMARY_COLS",
    "print_strategy_metrics",
    "print_summary_table",
]
