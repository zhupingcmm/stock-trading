"""``python -m scripts.run_report`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_report``（项目根目录）
- ``python scripts/run_report.py``（任意目录）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from data_collection.collectors.report import ReportCollector  # noqa: E402
from data_collection.sources.akshare import AkshareDataSource  # noqa: E402
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="研报数据采集 (AkShare -> MySQL)",
    )
    parser.add_argument(
        "--mode", choices=["test", "full"], default="full",
        help="test=只采贵州茅台, full=全量A股 (默认 full)",
    )
    parser.add_argument(
        "--stock", default="600519.SH",
        help="测试模式下采集的股票",
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="并行下载线程数",
    )
    parser.add_argument(
        "--recent-days", type=int, default=7,
        help="跳过近 N 天已采集的股票（仅 full 模式生效）",
    )
    return parser


def main() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()

    source = AkshareDataSource()
    storage = MysqlStorage.from_env()
    collector = ReportCollector(
        source, storage,
        workers=args.workers,
        recent_days=args.recent_days,
    )

    try:
        report = collector.collect(mode=args.mode, test_stock=args.stock)
        logger.info(
            "研报采集完成: processed={}/{} recommend={} forecast={} elapsed={:.1f}s",
            report.processed, report.total,
            report.recommend_saved, report.forecast_saved,
            report.elapsed,
        )
    finally:
        storage.close()


if __name__ == "__main__":
    main()