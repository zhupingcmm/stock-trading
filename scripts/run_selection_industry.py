"""``python -m scripts.run_selection_industry`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_selection_industry``（项目根目录）
- ``python scripts/run_selection_industry.py``（任意目录）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from data_collection.storage.mysql import MysqlStorage  # noqa: E402
from selection.strategies import IndustryFactorStrategy  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="多因子选股 - 行业版 (industry_factor)",
    )
    parser.add_argument(
        "--min-score", type=int, default=18,
        help="总分阈值（5 项各 1~5 分，总分 5~25，默认 18）",
    )
    parser.add_argument(
        "--no-viz", action="store_true",
        help="跳过行业分布可视化",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="输出根目录（默认 data/selection/industry_factor/）",
    )
    return parser


def main() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()

    storage = MysqlStorage.from_env()
    strategy = IndustryFactorStrategy(
        storage,
        min_score=args.min_score,
        output_dir=args.output_dir,
        enable_viz=not args.no_viz,
    )

    try:
        report = strategy.run()
        logger.info(
            "行业因子选股完成: pool={} passed={} used_industry={} elapsed={:.1f}s",
            report.pool_size, report.passed,
            report.used_industry, report.elapsed,
        )
    finally:
        storage.close()


if __name__ == "__main__":
    main()
