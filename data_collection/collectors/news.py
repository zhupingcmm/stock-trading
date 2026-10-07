"""个股新闻采集器。

把参考脚本 ``4-新闻事件采集.py`` 的逻辑整合为 ``NewsCollector``：
- 股票列表从 MySQL ``trade_stock_daily`` 取（已经采过行情的股票）
- 跳过当日已采集过任何新闻的股票
- 一次性把 ``trade_stock_news.title`` 加载到内存做去重
- 8 线程并行采集 ``ak.stock_news_em(symbol)``
"""
from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd
import pymysql

from config.settings import (
    NEWS_CONTENT_MAX_LEN,
    NEWS_DEFAULT_SOURCE,
    NEWS_DEFAULT_TYPE,
    NEWS_NUM_WORKERS,
)
from data_collection.sources.akshare import AkshareDataSource
from data_collection.storage.mysql import MysqlStorage
from data_collection.utils.sentiment import analyze_sentiment, check_important


# 新闻表 INSERT：无 ON DUPLICATE KEY，靠内存 + IntegrityError 容错
INSERT_NEWS_SQL = """
    INSERT INTO trade_stock_news
    (stock_code, news_type, title, content, source, source_url,
     sentiment, is_important, published_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


@dataclass
class NewsReport:
    """新闻采集结果汇总。"""

    total: int = 0
    processed: int = 0
    fetched: int = 0
    saved: int = 0
    skipped_today: int = 0
    elapsed: float = 0.0


_print_lock = threading.Lock()


def _safe_print(msg: str) -> None:
    """多线程安全打印。"""
    with _print_lock:
        print(msg)


class NewsCollector:
    """沪深 A 股个股新闻采集。"""

    def __init__(
        self,
        source: AkshareDataSource,
        storage: MysqlStorage,
        workers: int | None = None,
    ) -> None:
        self._source = source
        self._storage = storage
        self._workers = workers or NEWS_NUM_WORKERS
        # 内存中的「已知标题」集合，启动时由 ``load_existing_titles`` 填充
        self._existing_titles: set[str] = set()

    # ============================================================
    # 辅助查询
    # ============================================================

    def get_all_stocks(self) -> list[str]:
        """从 ``trade_stock_daily`` 拿所有出现过行情的股票。"""
        rows = self._storage.fetch_all(
            "SELECT DISTINCT stock_code FROM trade_stock_daily"
        )
        return [r["stock_code"] for r in rows]

    def get_today_collected(self) -> set[str]:
        """当日 ``trade_stock_news`` 里出现过的股票集合。"""
        rows = self._storage.fetch_all(
            "SELECT DISTINCT stock_code FROM trade_stock_news "
            "WHERE DATE(created_at) = CURDATE()"
        )
        return {r["stock_code"] for r in rows}

    def load_existing_titles(self) -> set[str]:
        """一次性加载所有已有新闻标题到内存，用于去重。"""
        rows = self._storage.fetch_all("SELECT title FROM trade_stock_news")
        return {r["title"] for r in rows}

    # ============================================================
    # 单只股票
    # ============================================================

    def fetch_news(self, stock_code: str) -> list[dict]:
        """通过 Akshare 采集 ``stock_code`` 的新闻。"""
        code_num = stock_code.split(".")[0]
        df = self._source.get_stock_news(code_num)
        if df is None or df.empty:
            return []

        items: list[dict] = []
        for _, row in df.iterrows():
            title = str(row.get("新闻标题", "")).strip()
            if not title:
                continue
            content = str(row.get("新闻内容", "")).strip()
            url = str(row.get("新闻链接", "")).strip()
            pub_time = str(row.get("发布时间", "")).strip()
            source = str(row.get("文章来源", "")).strip()

            items.append({
                "title": title,
                "content": content[:NEWS_CONTENT_MAX_LEN] if content else "",
                "link": url,
                "published_at": pub_time if pub_time else None,
                "sentiment": analyze_sentiment(title),
                "is_important": check_important(title),
                "source": source or NEWS_DEFAULT_SOURCE,
                "news_type": NEWS_DEFAULT_TYPE,
            })
        return items

    def save_news(self, stock_code: str, news_list: list[dict]) -> int:
        """内存去重后逐条写入，靠 ``IntegrityError`` 防 race condition。"""
        if not news_list:
            return 0

        new_items = [n for n in news_list if n["title"] not in self._existing_titles]
        if not new_items:
            return 0

        saved = 0
        for news in new_items:
            try:
                self._storage.execute(INSERT_NEWS_SQL, (
                    stock_code, news["news_type"], news["title"],
                    news["content"], news["source"], news["link"],
                    news["sentiment"],
                    1 if news["is_important"] else 0,
                    news["published_at"],
                ))
            except pymysql.err.IntegrityError:
                # race condition：其他线程已写入同标题 → 静默跳过
                pass
            else:
                saved += 1
            # 无论是否写入成功，都把标题加入集合，避免后续重试同一标题
            self._existing_titles.add(news["title"])
        return saved

    def process_one_stock(self, stock_code: str) -> tuple[str, int, int]:
        """采集单只股票并写入，返回 ``(code, fetched, saved)``。"""
        news = self.fetch_news(stock_code)
        saved = self.save_news(stock_code, news)
        return stock_code, len(news), saved

    # ============================================================
    # 主流程
    # ============================================================

    def collect(self, stocks: Iterable[str] | None = None) -> NewsReport:
        """执行新闻采集。

        ``stocks=None`` 时从 ``trade_stock_daily`` 自动发现；
        传入列表则跳过发现步骤（依然会当日跳过）。
        """
        report = NewsReport()
        start_ts = time.time()

        print("=" * 60)
        print("新闻事件采集（全量A股）")
        print("=" * 60)

        # 1) 股票列表
        all_stocks = list(stocks) if stocks is not None else self.get_all_stocks()
        print(f"全量股票: {len(all_stocks)} 只")

        # 2) 当日跳过
        today_collected = self.get_today_collected()
        if today_collected:
            all_stocks = [c for c in all_stocks if c not in today_collected]
            print(
                f"跳过当日已采集: {len(today_collected)} 只, "
                f"待采集: {len(all_stocks)} 只"
            )
            report.skipped_today = len(today_collected)

        if not all_stocks:
            print("全部股票当日已采集，无需再跑")
            report.elapsed = time.time() - start_ts
            self._print_summary()
            return report

        # 3) 加载已有标题到内存
        print("加载已有标题用于去重...")
        self._existing_titles = self.load_existing_titles()
        print(f"  已有 {len(self._existing_titles)} 条标题")

        report.total = len(all_stocks)
        done = 0

        print(f"\n开始采集 ({self._workers} 线程)...")

        with ThreadPoolExecutor(max_workers=self._workers) as executor:
            futures = {
                executor.submit(self.process_one_stock, code): code
                for code in all_stocks
            }
            for future in as_completed(futures):
                done += 1
                try:
                    _code, fetched, saved = future.result()
                    report.fetched += fetched
                    report.saved += saved
                except Exception:
                    pass

                if done % 200 == 0 or done == report.total:
                    elapsed = time.time() - start_ts
                    speed = done / elapsed if elapsed > 0 else 0
                    eta = (report.total - done) / speed if speed > 0 else 0
                    sys.stdout.write(
                        f"\r  [{done}/{report.total}] {done * 100 / report.total:.1f}% "
                        f"| {speed:.1f}/s | ETA {eta:.0f}s "
                        f"| fetched {report.fetched} saved {report.saved}    "
                    )
                    sys.stdout.flush()
        print()

        report.processed = done
        report.elapsed = time.time() - start_ts
        self._print_summary(report)
        return report

    # ============================================================
    # 摘要
    # ============================================================

    def _print_summary(self, report: NewsReport | None = None) -> None:
        rows = self._storage.fetch_all(
            "SELECT COUNT(*) AS cnt, COUNT(DISTINCT stock_code) AS stock_cnt "
            "FROM trade_stock_news"
        )
        if rows:
            r = rows[0]
            print(f"\ntrade_stock_news 总计 {r['cnt']:,} 条 "
                  f"({r['stock_cnt']} 只股票)")

        if report is not None:
            print("=" * 60)
            print(f"新闻采集完成! 耗时 {report.elapsed:.1f} 秒")
            print(f"  处理: {report.processed}/{report.total} 只股票")
            print(f"  采集: {report.fetched:,} 条, 新增: {report.saved:,} 条")
            print("=" * 60)