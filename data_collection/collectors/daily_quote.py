"""日线行情采集器。

把参考脚本 ``1-行情数据采集.py`` 的核心函数
（增量查询、单只下载、主流程）整合为 ``DailyQuoteCollector``。
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Literal

from data_collection.sources.xtquant import XtQuantDataSource
from data_collection.storage.mysql import MysqlStorage


# UPSERT SQL：与参考脚本字段一一对应，依赖 (stock_code, trade_date) UNIQUE KEY。
INSERT_SQL = """
    INSERT INTO trade_stock_daily
    (stock_code, trade_date, open_price, high_price, low_price, close_price,
     volume, amount, turnover_rate)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    open_price=VALUES(open_price),
    high_price=VALUES(high_price),
    low_price=VALUES(low_price),
    close_price=VALUES(close_price),
    volume=VALUES(volume),
    amount=VALUES(amount),
    turnover_rate=VALUES(turnover_rate)
"""


@dataclass
class CollectReport:
    """采集结果汇总。"""

    total: int = 0
    success: int = 0
    rows: int = 0
    failed: list[str] = field(default_factory=list)
    elapsed: float = 0.0


class DailyQuoteCollector:
    """沪深 A 股日线行情增量采集。"""

    # 任务数较少时改为串行，便于调试
    SERIAL_THRESHOLD = 5

    def __init__(
        self,
        source: XtQuantDataSource,
        storage: MysqlStorage,
        workers: int = 8,
    ) -> None:
        self._source = source
        self._storage = storage
        self._workers = workers

    # ----- 增量查询 -----
    def get_existing_latest_dates(self) -> dict[str, str]:
        """查询 DB 中每只股票的最大交易日，返回 ``{code: 'YYYYMMDD'}``。"""
        rows = self._storage.fetch_all(
            "SELECT stock_code, MAX(trade_date) AS max_date "
            "FROM trade_stock_daily GROUP BY stock_code"
        )
        out: dict[str, str] = {}
        for r in rows:
            if r["max_date"]:
                out[r["stock_code"]] = r["max_date"].strftime("%Y%m%d")
        return out

    # ----- 单只下载 -----
    def download_and_save(self, code: str, start_date: str) -> tuple[str, int]:
        """增量下载单只股票并写入 MySQL，返回 ``(code, rows)``。"""
        self._source.download_history(code, "1d", start_time=start_date)

        df = self._source.get_market_data(
            code,
            "1d",
            start_time=start_date,
            fields=("open", "high", "low", "close", "volume", "amount"),
        )
        if df is None or len(df) == 0:
            return code, 0

        float_shares = self._source.get_float_shares(code)

        rows: list[tuple] = []
        for idx, row in df.iterrows():
            idx_str = str(idx)
            if len(idx_str) < 8:
                continue
            trade_date = f"{idx_str[:4]}-{idx_str[4:6]}-{idx_str[6:8]}"
            vol = int(row["volume"])
            # xtquant volume 单位是手（1 手 = 100 股）
            vol_shares = vol * 100
            if float_shares > 0 and vol > 0:
                turnover = round(vol_shares / float_shares * 100, 4)
            else:
                turnover = None
            rows.append((
                code,
                trade_date,
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                vol,
                float(row["amount"]),
                turnover,
            ))

        if rows:
            self._storage.executemany(INSERT_SQL, rows)

        return code, len(rows)

    # ----- 主流程 -----
    def collect(
        self,
        mode: Literal["test", "full"] = "test",
        test_stock: str = "600519.SH",
        sector: str = "沪深A股",
        data_start: str = "20230101",
        stocks: Iterable[str] | None = None,
    ) -> CollectReport:
        """执行采集。

        ``mode='test'`` 只采集 ``test_stock``；
        ``mode='full'`` 拉取整个 ``sector``；
        ``stocks`` 显式传入时覆盖 ``mode`` 的默认行为。
        """
        report = CollectReport()
        start_ts = time.time()

        print("=" * 60)
        print("行情数据采集 (MiniQMT -> MySQL)")
        if mode == "test":
            print(f"[测试模式] 只采集 {test_stock}")
        else:
            print(f"[全量模式] 采集{sector}, {self._workers} 线程并行")
        print("=" * 60)

        # 1) 股票列表
        if stocks is not None:
            all_codes = list(stocks)
        elif mode == "test":
            all_codes = [test_stock]
            print(f"\n[测试模式] 只采集 {test_stock}")
        else:
            print(f"\n获取 {sector} 股票列表...")
            all_codes = self._source.list_stocks(sector)
            print(f"  共 {len(all_codes)} 只股票")

        # 2) 增量裁剪
        print("查询数据库已有数据...")
        existing = self.get_existing_latest_dates()
        cutoff = date.today().strftime("%Y%m%d")

        tasks: list[tuple[str, str]] = []
        skip_count = 0
        for code in all_codes:
            latest = existing.get(code)
            if latest and latest >= cutoff:
                skip_count += 1
                continue
            start = latest if latest else data_start
            tasks.append((code, start))

        print(f"  需更新: {len(tasks)} 只, 跳过(今日已有数据): {skip_count} 只")

        if not tasks:
            print("\n全部已是最新，无需更新")
            report.elapsed = time.time() - start_ts
            self._print_summary()
            return report

        report.total = len(tasks)

        # 3) 执行
        if report.total <= self.SERIAL_THRESHOLD:
            for i, (code, start) in enumerate(tasks, 1):
                print(f"\n[{i}/{report.total}] {code} (从 {start} 开始)")
                try:
                    _, count = self.download_and_save(code, start)
                except Exception:
                    report.failed.append(code)
                    print("  失败")
                    continue
                if count >= 0:
                    report.success += 1
                    report.rows += max(count, 0)
                    print(f"  写入 {count} 条")
                else:
                    report.failed.append(code)
                    print("  失败")
        else:
            print(f"\n并行下载（{self._workers} 线程）...")

            def _worker(args: tuple[str, str]) -> tuple[str, int]:
                code, start = args
                try:
                    return self.download_and_save(code, start)
                except Exception:
                    return code, -1

            with ThreadPoolExecutor(max_workers=self._workers) as executor:
                futures = {executor.submit(_worker, t): t[0] for t in tasks}
                done = 0
                for future in as_completed(futures):
                    code, count = future.result()
                    done += 1

                    if count >= 0:
                        report.success += 1
                        report.rows += max(count, 0)
                    else:
                        report.failed.append(code)

                    elapsed = time.time() - start_ts
                    speed = done / elapsed if elapsed > 0 else 0
                    eta = (report.total - done) / speed if speed > 0 else 0
                    sys.stdout.write(
                        f"\r  进度 {done}/{report.total} "
                        f"({done * 100 / report.total:.1f}%) | "
                        f"{speed:.1f} 只/秒 | 剩余约 {eta:.0f}秒 | "
                        f"成功 {report.success} 失败 {len(report.failed)}    "
                    )
                    sys.stdout.flush()
            print()

        report.elapsed = time.time() - start_ts
        self._print_summary(report)
        return report

    # ----- 摘要 -----
    def _print_summary(self, report: CollectReport | None = None) -> None:
        summary = self._storage.fetch_all(
            "SELECT COUNT(DISTINCT stock_code) AS stock_cnt, COUNT(*) AS row_cnt, "
            "MIN(trade_date) AS min_date, MAX(trade_date) AS max_date "
            "FROM trade_stock_daily"
        )
        if summary:
            row = summary[0]
            print("\n数据库 trade_stock_daily 概况:")
            print(
                f"  {row['stock_cnt']} 只股票, {row['row_cnt']:,} 条记录\n"
                f"  日期范围: {row['min_date']} ~ {row['max_date']}"
            )
        if report is not None:
            print("=" * 60)
            print(f"采集完成! 耗时 {report.elapsed:.1f} 秒")
            print(f"  成功: {report.success}/{report.total} 只股票")
            print(f"  总写入: {report.rows:,} 条记录")
            if report.failed:
                head = report.failed[:20]
                tail = "..." if len(report.failed) > 20 else ""
                print(f"  失败 {len(report.failed)} 只: {head}{tail}")
            print("=" * 60)