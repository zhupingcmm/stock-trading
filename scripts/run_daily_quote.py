"""``python -m scripts.run_daily_quote`` 命令行入口。"""
from __future__ import annotations

import argparse
import sys

from loguru import logger

from data_collection.collectors.daily_quote import DailyQuoteCollector
from data_collection.sources.xtquant import XtQuantDataSource
from data_collection.storage.mysql import MysqlStorage


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="行情数据采集 (MiniQMT -> MySQL)",
    )
    parser.add_argument(
        "--mode", choices=["test", "full"], default="test",
        help="test: 仅采集测试股；full: 全量板块",
    )
    parser.add_argument("--stock", default="600519.SH", help="测试模式下采集的股票代码")
    parser.add_argument("--sector", default="沪深A股", help="全量模式下的板块名")
    parser.add_argument("--start", default="20230101", help="首次采集的起始日期 YYYYMMDD")
    parser.add_argument("--workers", type=int, default=8, help="并行下载线程数")
    return parser


def main() -> None:
    # Windows 控制台输出 UTF-8
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()

    source = XtQuantDataSource()
    source.connect()
    storage = MysqlStorage.from_env()
    collector = DailyQuoteCollector(source, storage, workers=args.workers)

    try:
        report = collector.collect(
            mode=args.mode,
            test_stock=args.stock,
            sector=args.sector,
            data_start=args.start,
        )
        logger.info(
            "采集完成: success={}/{} rows={} failed={} elapsed={:.1f}s",
            report.success, report.total, report.rows,
            len(report.failed), report.elapsed,
        )
    finally:
        storage.close()


if __name__ == "__main__":
    main()