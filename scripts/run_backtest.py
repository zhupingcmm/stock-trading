"""``python -m scripts.run_backtest`` 命令行入口。

支持：

* ``--strategy KEY``  单策略（key 见 ``--list``）
* ``--strategy-dir PATH``  额外自定义策略目录
* ``--stock / --start / --end``
* ``--no-plot``   跳过 PNG
* ``--list``      列出所有策略 key 并退出

示例::

    python -m scripts.run_backtest                          # 跑全部
    python -m scripts.run_backtest --strategy macd          # 只跑 MACD
    python -m scripts.run_backtest --stock 600519.SH        # 换标的
    python -m scripts.run_backtest --start 2025-01-01 --end 2025-12-31
    python -m scripts.run_backtest --no-plot                # 不要 PNG
    python -m scripts.run_backtest --list                   # 列出 key
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from backtest.engine import (  # noqa: E402
    calc_metrics,
    setup_cerebro,
    setup_multi_tf_cerebro,
    wrap_strategy,
)
from backtest.reports import plot_backtest, print_strategy_metrics, print_summary_table  # noqa: E402
from backtest.strategies import load_strategies  # noqa: E402
from config.settings import (  # noqa: E402
    BACKTEST_END_DATE,
    BACKTEST_START_DATE,
    BACKTEST_STOCK_CODE,
)


def _run_one(entry: dict, stock: str, start: str, end: str, plot: bool,
             storage=None, **strategy_kwargs) -> dict:
    """跑单个策略；返回 ``run_and_report`` 风格的 metrics dict。

    根据 ``STRATEGY_META['setup']`` 自动选择 cerebro 配置：
      - ``"multi_tf"`` → ``setup_multi_tf_cerebro``（周线 + 日线）
      - 其它 → ``setup_cerebro``（单数据源）
    """
    meta = entry["meta"]
    if meta.get("requires_predictions"):
        # ML 类策略需外部预训练模型，直接跑会 0 信号
        raise RuntimeError(
            f"策略 {meta.get('name')} 需要预训练的 ML 预测字典，"
            "请改用 scripts/run_turtle_ml.py"
        )

    setup_kind = meta.get("setup", "default")
    wrapped = wrap_strategy(entry["class"])
    if setup_kind == "multi_tf":
        cerebro, df = setup_multi_tf_cerebro(
            wrapped, stock, start, end,
            storage=storage, **strategy_kwargs,
        )
    else:
        cerebro, df = setup_cerebro(
            wrapped, stock, start, end,
            storage=storage, **strategy_kwargs,
        )
    results = cerebro.run()
    strat = results[0]
    metrics = calc_metrics(cerebro, strat, df)

    print_strategy_metrics(
        metrics, stock=stock,
        start=df.index[0].strftime("%Y-%m-%d"),
        end=df.index[-1].strftime("%Y-%m-%d"),
        trading_days=len(df),
        label=meta["name"],
    )

    result = {**metrics, "df": df,
              "trades": strat._trade_log,
              "nav": strat._nav_log,
              "label": meta["name"]}

    if plot:
        plot_backtest(result, stock_code=stock, title=meta["name"])
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="回测入口：跑一个或多个 backtrader 策略",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--strategy", "-s", default=None,
                        help="只跑指定 key 的策略（用 --list 查看可用 key）")
    parser.add_argument("--strategy-dir", default=None,
                        help="额外的自定义策略目录（绝对路径），递归扫描 .py")
    parser.add_argument("--stock", default=BACKTEST_STOCK_CODE,
                        help=f"股票代码 (默认 {BACKTEST_STOCK_CODE})")
    parser.add_argument("--start", default=BACKTEST_START_DATE,
                        help=f"开始日期 YYYY-MM-DD (默认 {BACKTEST_START_DATE})")
    parser.add_argument("--end", default=BACKTEST_END_DATE,
                        help=f"结束日期 YYYY-MM-DD (默认 {BACKTEST_END_DATE})")
    parser.add_argument("--no-plot", action="store_true",
                        help="不生成 PNG 图表 (提速)")
    parser.add_argument("--list", action="store_true",
                        help="列出所有可用策略 key 并退出")
    return parser


def main() -> int:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()

    extra_dirs = [args.strategy_dir] if args.strategy_dir else None
    strategies = load_strategies(extra_dirs=extra_dirs)

    if args.list:
        print("可用策略 key:")
        for key in sorted(strategies):
            meta = strategies[key]["meta"]
            print(f"  {key:<18} {meta.get('name', '')}  [{meta.get('category', '')}]")
        return 0

    if not strategies:
        print("[错误] 没有可用策略，请检查 backtest/strategies/ 目录")
        return 2

    if args.strategy:
        if args.strategy not in strategies:
            print(f"[错误] 未知策略 key: {args.strategy}")
            print("可用 key:", ", ".join(sorted(strategies)))
            return 1
        targets = {args.strategy: strategies[args.strategy]}
    else:
        targets = strategies

    plot = not args.no_plot
    rows = []
    for key, entry in targets.items():
        print("-" * 100)
        try:
            m = _run_one(entry, args.stock, args.start, args.end, plot)
            # 汇总表要的精简字段
            from backtest.reports.printer import _extract_row
            rows.append(_extract_row(m))
            logger.info("策略 {} 完成: 总收益 {:.2f}%, 夏普 {:.2f}",
                        entry["meta"]["name"],
                        m["total_return"] * 100, m["sharpe_ratio"])
        except Exception as e:
            print(f"[跳过] {entry['meta'].get('name', key)}: {e}")
            traceback.print_exc()
    print("-" * 100)
    print_summary_table(rows, args.stock, args.start, args.end)
    return 0 if rows else 3


if __name__ == "__main__":
    sys.exit(main())
