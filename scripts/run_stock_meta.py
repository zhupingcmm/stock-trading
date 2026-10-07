"""``python -m scripts.run_stock_meta`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_stock_meta``（项目根目录）
- ``python scripts/run_stock_meta.py``（任意目录）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让直接 ``python scripts/run_X.py`` 调用时也能 import 到项目顶层包。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402  必须在 sys.path bootstrap 之后

from data_collection.collectors.stock_meta import StockMetaCollector  # noqa: E402
from data_collection.sources.xtquant import XtQuantDataSource  # noqa: E402
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="股票元数据采集 (名称 + 行业, MiniQMT -> MySQL)",
    )
    parser.add_argument(
        "--mode", choices=["test", "full"], default="full",
        help="test: 仅采集测试股；full: 全量板块",
    )
    parser.add_argument("--stock", default="600519.SH", help="测试模式下采集的股票代码")
    parser.add_argument("--sector", default="沪深A股", help="全量模式下的板块名")
    parser.add_argument("--workers", type=int, default=8, help="并行采集线程数")
    return parser


def main() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()

    source = XtQuantDataSource()
    source.connect()
    storage = MysqlStorage.from_env()
    collector = StockMetaCollector(source, storage, workers=args.workers)

    try:
        report = collector.collect(
            mode=args.mode,
            test_stock=args.stock,
            sector=args.sector,
        )
        logger.info(
            "采集完成: success={}/{} n_with_industry={} failed={} elapsed={:.1f}s",
            report.success, report.total, report.n_with_industry,
            len(report.failed), report.elapsed,
        )
    finally:
        storage.close()


if __name__ == "__main__":
    main()
