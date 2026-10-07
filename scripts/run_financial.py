"""``python -m scripts.run_financial`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_financial``（项目根目录）
- ``python scripts/run_financial.py``（任意目录）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from data_collection.collectors.financial import FinancialCollector  # noqa: E402
from data_collection.sources.xtquant import XtQuantDataSource  # noqa: E402
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="财务数据采集 (MiniQMT -> MySQL)",
    )
    parser.add_argument(
        "--mode", choices=["test", "full"], default="test",
        help="test: 仅采集测试股；full: 全量板块",
    )
    parser.add_argument("--stock", default="600519.SH", help="测试模式下采集的股票代码")
    parser.add_argument("--sector", default="沪深A股", help="全量模式下的板块名")
    parser.add_argument("--start", default="20150101", help="财务数据起始日期 YYYYMMDD")
    parser.add_argument("--batch-size", type=int, default=50, help="每批下载的股票数")
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
    collector = FinancialCollector(
        source, storage, batch_size=args.batch_size, data_start=args.start,
    )

    try:
        report = collector.collect(
            mode=args.mode,
            test_stock=args.stock,
            sector=args.sector,
        )
        logger.info(
            "财务采集完成: success={}/{} rows={} batches={} elapsed={:.1f}s",
            report.success, report.total_stocks, report.rows,
            report.batches, report.elapsed,
        )
    finally:
        storage.close()


if __name__ == "__main__":
    main()