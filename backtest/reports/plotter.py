"""回测结果可视化 — 三联图。

* 上：收盘价 + 买卖点 + 右侧指标框
* 中：策略净值曲线 vs 买入持有基准
* 下：回撤填充

输出到 ``outputs/`` 目录（与案例一致）。
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from config.settings import BACKTEST_INITIAL_CASH, DATA_ROOT

# 中文字体（headless 环境用 Agg 后端；调用方也可提前 import）
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = Path(DATA_ROOT) / "backtest" if DATA_ROOT else Path("outputs")


def plot_backtest(
    result: dict,
    stock_code: str = "",
    title: str = "",
    output_dir: str | os.PathLike | None = None,
) -> Path | None:
    """绘制三联图并保存为 PNG。

    Parameters
    ----------
    result : :func:`run_backtest` 返回的 dict（含 ``df`` / ``trades`` / ``nav`` / 指标）
    stock_code / title : 图表标题拼接
    output_dir : 输出目录；默认 ``DATA_ROOT/backtest``，回退 ``./outputs``

    Returns
    -------
    保存的 PNG 路径；没有净值数据时返回 None。
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    df = result["df"]
    trades = result.get("trades", [])
    nav_data = result.get("nav", [])
    if not nav_data:
        print("没有净值数据，跳过绘图")
        return None

    nav_df = pd.DataFrame(nav_data)
    nav_df["date"] = pd.to_datetime(nav_df["date"])
    nav_df.set_index("date", inplace=True)
    nav_df["nav_pct"] = nav_df["nav"] / BACKTEST_INITIAL_CASH
    nav_df["peak"] = nav_df["nav"].cummax()
    nav_df["drawdown"] = (nav_df["nav"] - nav_df["peak"]) / nav_df["peak"] * 100

    close_start = float(df["close"].iloc[0])
    benchmark = df["close"] / close_start

    buy_dates = [t["date"] for t in trades if t["type"] == "BUY"]
    buy_prices = [t["price"] for t in trades if t["type"] == "BUY"]
    sell_dates = [t["date"] for t in trades if t["type"] == "SELL"]
    sell_prices = [t["price"] for t in trades if t["type"] == "SELL"]

    m = result
    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(16, 12),
        gridspec_kw={"height_ratios": [3, 2, 1]},
    )

    # 上：K线 + 买卖点
    ax1.plot(df.index, df["close"], "gray", linewidth=1, alpha=0.8, label="收盘价")
    if buy_dates:
        ax1.scatter(buy_dates, buy_prices, color="#e74c3c", marker="^", s=80,
                    zorder=5, label=f"买入({len(buy_dates)}次)")
    if sell_dates:
        ax1.scatter(sell_dates, sell_prices, color="#2ecc71", marker="v", s=80,
                    zorder=5, label=f"卖出({len(sell_dates)}次)")
    ax1.set_ylabel("价格")
    ax1.set_title(f"{title}  {stock_code}", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, alpha=0.3)

    info_text = (
        f"Return:    {m['total_return'] * 100:+.2f}%\n"
        f"Benchmark: {m.get('benchmark_return', 0) * 100:+.2f}%\n"
        f"Annual:    {m['annual_return'] * 100:+.2f}%\n"
        f"MaxDD:     {m['max_drawdown'] * 100:.2f}%\n"
        f"Sharpe:    {m['sharpe_ratio']:.2f}\n"
        f"Calmar:    {m['calmar_ratio']:.2f}\n"
        f"WinRate:   {m['win_rate'] * 100:.1f}%\n"
        f"P/L Ratio: {m['profit_loss_ratio']:.2f}\n"
        f"ProfitF:   {m['profit_factor']:.2f}"
    )
    ax1.text(0.98, 0.97, info_text, transform=ax1.transAxes,
             fontsize=9, verticalalignment="top", horizontalalignment="right",
             bbox=dict(boxstyle="round,pad=0.5", facecolor="wheat", alpha=0.8),
             family="monospace")

    # 中：净值曲线 vs 基准
    ax2.plot(nav_df.index, nav_df["nav_pct"], "#2980b9", linewidth=1.5, label="策略净值")
    ax2.plot(benchmark.index, benchmark, "gray", linewidth=1, alpha=0.6, label="买入持有")
    ax2.axhline(y=1.0, color="red", linestyle="--", alpha=0.3)
    ax2.set_ylabel("净值 (初始=1.0)")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.grid(True, alpha=0.3)

    # 下：回撤
    ax3.fill_between(nav_df.index, nav_df["drawdown"], 0, color="#e74c3c", alpha=0.4)
    ax3.plot(nav_df.index, nav_df["drawdown"], "#c0392b", linewidth=0.8)
    ax3.set_ylabel("回撤(%)")
    ax3.set_xlabel("日期")
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()

    safe_name = (title or "backtest").replace(" ", "_").replace("/", "_")
    plot_file = out_dir / f"{safe_name}.png"
    plt.savefig(plot_file, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  图表已保存: {plot_file}")
    return plot_file


__all__ = ["plot_backtest"]
