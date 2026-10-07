"""``python -m scripts.run_news`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_news``（项目根目录）
- ``python scripts/run_news.py``（任意目录）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from data_collection.collectors.news import NewsCollector  # noqa: E402
from data_collection.sources.akshare import AkshareDataSource  # noqa: E402
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="新闻事件采集 (AkShare -> MySQL)",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="并行下载线程数",
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
    collector = NewsCollector(source, storage, workers=args.workers)

    try:
        report = collector.collect()
        logger.info(
            "新闻采集完成: processed={}/{} fetched={} saved={} elapsed={:.1f}s",
            report.processed, report.total, report.fetched,
            report.saved, report.elapsed,
        )
    finally:
        storage.close()


if __name__ == "__main__":
    main()