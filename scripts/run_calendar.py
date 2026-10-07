"""``python -m scripts.run_calendar`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_calendar``（项目根目录）
- ``python scripts/run_calendar.py``（任意目录）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from data_collection.collectors.calendar import CalendarCollector  # noqa: E402
from data_collection.sources.akshare import AkshareDataSource  # noqa: E402
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="财经日历采集 (AkShare -> MySQL)",
    )
    parser.add_argument(
        "--days-back", type=int, default=7,
        help="窗口起点：today - N 天",
    )
    parser.add_argument(
        "--days-forward", type=int, default=30,
        help="窗口终点：today + N 天",
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
    collector = CalendarCollector(
        source, storage,
        days_back=args.days_back,
        days_forward=args.days_forward,
    )

    try:
        report = collector.collect()
        logger.info(
            "财经日历采集完成: raw={} filtered={} saved={} elapsed={:.1f}s",
            report.raw_count, report.filtered_count,
            report.saved, report.elapsed,
        )
    finally:
        storage.close()


if __name__ == "__main__":
    main()