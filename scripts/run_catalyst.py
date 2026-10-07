"""``python -m scripts.run_catalyst`` 命令行入口。

支持两种调用方式：
- ``python -m scripts.run_catalyst``（项目根目录）
- ``python scripts/run_catalyst.py``（任意目录）

子命令：
- 默认 / 无参数：执行主流程（搜索事件 + 生成 prompt + 写入）
- ``--backfill-prompts``：仅给 ``ai_prompt`` 为空的事件补全 prompt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger  # noqa: E402

from data_collection.collectors.catalyst import CatalystCollector  # noqa: E402
from data_collection.sources.llm import QwenClient  # noqa: E402
from data_collection.storage.mysql import MysqlStorage  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="关键催化剂事件采集 (Qwen Max -> MySQL)",
    )
    parser.add_argument(
        "--backfill-prompts", action="store_true",
        help="仅为缺失 ai_prompt 的事件补充 prompt（不重新搜索）",
    )
    parser.add_argument(
        "--search-days", type=int, default=180,
        help="联网搜索的时间窗口（天）",
    )
    parser.add_argument(
        "--prompt-batch-size", type=int, default=20,
        help="每批生成 prompt 的事件数",
    )
    parser.add_argument(
        "--prompts-path", default=None,
        help="prompts.yaml 路径（默认 config/prompts.yaml）",
    )
    return parser


def main() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = _build_parser().parse_args()

    qwen = QwenClient()
    storage = MysqlStorage.from_env()
    collector = CatalystCollector(
        qwen, storage,
        prompts_path=args.prompts_path,
        search_days=args.search_days,
        prompt_batch_size=args.prompt_batch_size,
    )

    try:
        if args.backfill_prompts:
            updated = collector.run_backfill()
            logger.info("催化剂回填完成: updated={}", updated)
        else:
            report = collector.run()
            logger.info(
                "催化剂采集完成: found={} prompts={} saved={} elapsed={:.1f}s",
                report.events_found, report.prompts_generated,
                report.saved, report.elapsed,
            )
    finally:
        storage.close()


if __name__ == "__main__":
    main()