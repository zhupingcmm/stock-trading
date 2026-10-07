"""``python -m scripts.run_macro`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_macro``（项目根目录）
- ``python scripts/run_macro.py``（任意目录）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from data_collection.collectors.macro import MacroCollector  # noqa: E402
from data_collection.sources.akshare import AkshareDataSource  # noqa: E402
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="宏观经济数据采集 (AkShare -> MySQL)",
    )
    parser.add_argument(
        "--retention-years", type=int, default=10,
        help="月度宏观指标的保留年限",
    )
    parser.add_argument(
        "--rate-years", type=int, default=3,
        help="日频国债收益率的回溯年限",
    )
    return parser


def main() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()

    print("=" * 60)
    print("宏观经济数据采集 -> MySQL")
    print("=" * 60)

    source = AkshareDataSource()
    storage = MysqlStorage.from_env()
    collector = MacroCollector(
        source, storage,
        retention_years=args.retention_years,
        rate_history_years=args.rate_years,
    )

    try:
        monthly, daily = collector.collect()
        collector.print_summary()

        logger.info(
            "宏观采集完成: monthly_rows={} daily_rows={}",
            monthly.rows_written, daily.rows_written,
        )
    finally:
        storage.close()

    print("\n" + "=" * 60)
    print("宏观数据采集完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()