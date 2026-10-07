"""``python -m scripts.run_turtle_ml`` 命令行入口。

完整流程：训练 ML 模型 → 生成预测 → 跑 ML 海龟回测。

流程
----
1. 从多只股票历史数据中提取突破事件特征
2. 按 split_date 切分训练/测试集，训练 LightGBM / XGBoost / sklearn GBDT
3. 为目标股票生成预测 ``{date: probability}``
4. 把 predictions 注入 ML 海龟策略，跑回测

示例::

    python -m scripts.run_turtle_ml --stock 601318.SH --split-date 2025-01-01
    python -m scripts.run_turtle_ml --stock 510300.SH --threshold 0.55
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402

from backtest.engine import calc_metrics, setup_cerebro, wrap_strategy  # noqa: E402
from backtest.engine.data import load_stock_data  # noqa: E402
from backtest.reports import plot_backtest, print_strategy_metrics  # noqa: E402
from backtest.strategies.turtle_ml import Strategy as MLTurtle  # noqa: E402
from backtest.utils import (  # noqa: E402
    collect_multi_stock_features,
    compute_features,
    detect_engine,
    generate_predictions,
    train_model,
)
from config.settings import (  # noqa: E402
    BACKTEST_END_DATE,
    BACKTEST_START_DATE,
    BACKTEST_STOCK_CODE,
)
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


# 默认训练股票池（跨行业，提升泛化）
DEFAULT_TRAIN_STOCKS: list[tuple[str, str]] = [
    ("600519.SH", "贵州茅台"),
    ("300750.SZ", "宁德时代"),
    ("510300.SH", "沪深300ETF"),
    ("688981.SH", "中芯国际"),
    ("601318.SH", "平安银行"),
    ("159941.SZ", "纳指ETF"),
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ML 增强海龟策略 (LightGBM/XGBoost 过滤假突破)",
    )
    parser.add_argument(
        "--stock", default=BACKTEST_STOCK_CODE,
        help=f"目标股票代码 (默认 {BACKTEST_STOCK_CODE})",
    )
    parser.add_argument(
        "--start", default=BACKTEST_START_DATE,
        help=f"开始日期 (默认 {BACKTEST_START_DATE})",
    )
    parser.add_argument(
        "--end", default=BACKTEST_END_DATE,
        help=f"结束日期 (默认 {BACKTEST_END_DATE})",
    )
    parser.add_argument(
        "--split-date", default="2025-01-01",
        help="训练/测试分割日期 (默认 2025-01-01)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.5,
        help="ML 概率阈值，>= 此值才入场 (默认 0.5)",
    )
    parser.add_argument(
        "--no-plot", action="store_true",
        help="跳过 PNG 图表",
    )
    return parser


def _train_load(code: str, start: str, end: str) -> pd.DataFrame:
    """供 ``collect_multi_stock_features`` 使用的 loader。"""
    return load_stock_data(code, start, end)


def main() -> int:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()
    split_date = pd.Timestamp(args.split_date)
    storage = MysqlStorage.from_env()

    try:
        # ============================================================
        # Step 1: 多股票特征收集
        # ============================================================
        print("=" * 70)
        print("Step 1: 多股票突破事件特征收集")
        print("=" * 70)
        train_codes = [c for c, _ in DEFAULT_TRAIN_STOCKS]
        features_df, labels = collect_multi_stock_features(
            train_codes, _train_load,
            start_date=args.start, end_date=args.end,
        )
        if len(features_df) < 10:
            print(f"[错误] 样本不足 ({len(features_df)} 个突破事件)")
            return 2
        print(f"  合计: {len(features_df)} 个突破事件")
        print(f"  真突破: {labels.sum()} ({labels.mean() * 100:.0f}%)")
        print(f"  假突破: {len(labels) - labels.sum()} ({(1 - labels.mean()) * 100:.0f}%)")

        # ============================================================
        # Step 2: 训练
        # ============================================================
        print("\n" + "=" * 70)
        print(f"Step 2: 模型训练 (split={args.split_date}, engine={detect_engine()})")
        print("=" * 70)
        model, m = train_model(features_df, labels, split_date)
        if model is None:
            print(f"[错误] 样本不足: train={m.train_size} test={m.test_size}")
            return 2
        print(f"  训练集: {m.train_size} | 测试集: {m.test_size}")
        print(f"  准确率: {m.accuracy * 100:.1f}% | 精确率: {m.precision * 100:.1f}%")
        print(f"  召回率: {m.recall * 100:.1f}% | F1: {m.f1 * 100:.1f}%")
        if m.feature_importances:
            print("\n  特征重要性:")
            for name, imp in m.feature_importances.items():
                bar = "#" * int(imp * 25)
                print(f"    {name:<22} {imp:.2f} {bar}")

        # ============================================================
        # Step 3: 目标股票预测
        # ============================================================
        print("\n" + "=" * 70)
        print(f"Step 3: 目标股票 {args.stock} 预测生成")
        print("=" * 70)
        target_df = _train_load(args.stock, args.start, args.end)
        target_feat, _ = compute_features(target_df)
        predictions = generate_predictions(model, target_feat)
        high_prob = sum(1 for p in predictions.values() if p >= args.threshold)
        print(f"  突破事件: {len(predictions)}")
        print(f"  ML 概率 >= {args.threshold}: {high_prob} 个")

        # ============================================================
        # Step 4: 回测
        # ============================================================
        print("\n" + "=" * 70)
        print("Step 4: ML 海龟回测")
        print("=" * 70)
        wrapped = wrap_strategy(MLTurtle)
        cerebro, df = setup_cerebro(
            wrapped, args.stock, args.start, args.end,
            storage=storage,
            predictions=predictions,
            ml_threshold=args.threshold,
        )
        results = cerebro.run()
        strat = results[0]
        metrics = calc_metrics(cerebro, strat, df)

        print_strategy_metrics(
            metrics, stock=args.stock,
            start=df.index[0].strftime("%Y-%m-%d"),
            end=df.index[-1].strftime("%Y-%m-%d"),
            trading_days=len(df),
            label="ML 海龟",
        )

        if not args.no_plot:
            result = {**metrics, "df": df,
                      "trades": strat._trade_log,
                      "nav": strat._nav_log,
                      "label": "ML 海龟"}
            plot_backtest(result, stock_code=args.stock, title="ML 海龟策略")

        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    sys.exit(main())
