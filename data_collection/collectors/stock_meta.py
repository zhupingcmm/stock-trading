"""股票元数据采集器（名称 + 行业）。

把股票名 / 申万一级行业映射从「选股阶段连 xtquant」下沉到「采集阶段一次性写入
``trade_stock_meta``」。这样选股阶段只需读 MySQL，无需 MiniQMT 在线。

采集流程（与 ``DailyQuoteCollector`` 同风格）：
1. 调 ``XtQuantDataSource.get_stock_industry_map()`` 一次性拿全量 ``{code: industry}``；
2. 调 ``XtQuantDataSource.list_stocks(sector)`` 拿股票列表；
3. 对每只股票调 ``XtQuantDataSource.get_stock_name(code)`` 拿名称；
4. 并行 UPSERT 到 ``trade_stock_meta``。
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Iterable, Literal

from config.settings import STOCK_META_NUM_WORKERS, STOCK_META_SOURCE_LABEL
from data_collection.sources.xtquant import XtQuantDataSource
from data_collection.storage.mysql import MysqlStorage


# 单条 UPSERT：依赖 (stock_code) PRIMARY KEY
INSERT_SQL = """
    INSERT INTO trade_stock_meta (stock_code, stock_name, industry, data_source)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      stock_name  = VALUES(stock_name),
      industry    = VALUES(industry),
      data_source = VALUES(data_source)
"""


@dataclass
class StockMetaReport:
    """股票元数据采集结果汇总。"""

    total: int = 0
    success: int = 0
    failed: list[str] = field(default_factory=list)
    n_with_industry: int = 0
    elapsed: float = 0.0


class StockMetaCollector:
    """股票名 + 行业一次性采集（MiniQMT -> MySQL）。"""

    # 任务数较少时改为串行，便于调试
    SERIAL_THRESHOLD = 5

    def __init__(
        self,
        source: XtQuantDataSource,
        storage: MysqlStorage,
        workers: int | None = None,
        source_label: str | None = None,
    ) -> None:
        self._source = source
        self._storage = storage
        self._workers = workers if workers is not None else STOCK_META_NUM_WORKERS
        self._source_label = (
            source_label if source_label is not None else STOCK_META_SOURCE_LABEL
        )

    # ----- 股票列表 -----
    def get_listed_stocks(self, sector: str) -> list[str]:
        """获取板块下的股票代码列表。"""
        return self._source.list_stocks(sector)

    # ----- 行业映射（一次性） -----
    def fetch_industry_map(self) -> dict[str, str]:
        """一次性拉取 ``{stock_code: industry}``，写入内存供单只补齐使用。"""
        return self._source.get_stock_industry_map()

    # ----- 单只 -----
    def fetch_meta(self, code: str, industry_map: dict[str, str]) -> dict[str, str]:
        """拉取单只股票的 ``{stock_name, industry}``。

        - ``stock_name`` 来自 xtquant，失败/缺失 → 空字符串；
        - ``industry`` 来自 ``industry_map``，缺该 code → 空字符串。
        """
        name = self._source.get_stock_name(code)
        industry = industry_map.get(code, "")
        return {
            "stock_code": code,
            "stock_name": (name or "").strip(),
            "industry": (industry or "").strip(),
        }

    def save_one(self, code: str, stock_name: str, industry: str) -> int:
        """单条 UPSERT，返回受影响行数。"""
        return self._storage.execute(
            INSERT_SQL, (code, stock_name, industry, self._source_label),
        )

    # ----- 主流程 -----
    def collect(
        self,
        mode: Literal["test", "full"] = "test",
        test_stock: str = "600519.SH",
        sector: str = "沪深A股",
        stocks: Iterable[str] | None = None,
    ) -> StockMetaReport:
        """执行采集。

        - ``mode='test'`` 只采集 ``test_stock``；
        - ``mode='full'`` 拉取整个 ``sector``；
        - ``stocks`` 显式传入时覆盖 ``mode`` 的默认行为。
        """
        report = StockMetaReport()
        start_ts = time.time()

        print("=" * 60)
        print("股票元数据采集 (MiniQMT -> MySQL)")
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
            all_codes = self.get_listed_stocks(sector)
            print(f"  共 {len(all_codes)} 只股票")

        report.total = len(all_codes)
        if not all_codes:
            print("\n无股票可采集")
            report.elapsed = time.time() - start_ts
            return report

        # 2) 一次性行业映射
        print("\n拉取申万一级行业映射...")
        industry_map = self.fetch_industry_map()
        report.n_with_industry = len(industry_map)
        print(f"  行业映射覆盖 {len(industry_map)} 只股票")

        # 3) 执行
        if report.total <= self.SERIAL_THRESHOLD:
            for i, code in enumerate(all_codes, 1):
                print(f"\n[{i}/{report.total}] {code}")
                try:
                    meta = self.fetch_meta(code, industry_map)
                    self.save_one(meta["stock_code"], meta["stock_name"], meta["industry"])
                except Exception as exc:
                    report.failed.append(code)
                    print(f"  失败: {type(exc).__name__}: {exc}")
                    continue
                report.success += 1
                print(f"  name='{meta['stock_name']}' industry='{meta['industry']}'")
        else:
            print(f"\n并行采集（{self._workers} 线程）...")

            def _worker(code: str) -> tuple[str, dict | None, str | None]:
                try:
                    meta = self.fetch_meta(code, industry_map)
                    return code, meta, None
                except Exception as exc:
                    return code, None, f"{type(exc).__name__}: {exc}"

            with ThreadPoolExecutor(max_workers=self._workers) as executor:
                futures = {executor.submit(_worker, c): c for c in all_codes}
                done = 0
                for future in as_completed(futures):
                    code, meta, err = future.result()
                    done += 1

                    if err:
                        report.failed.append(code)
                        if len(report.failed) <= 5:
                            print(f"\n  [失败样本] {code}: {err}")
                    else:
                        try:
                            self.save_one(meta["stock_code"], meta["stock_name"], meta["industry"])
                            report.success += 1
                        except Exception as exc:
                            report.failed.append(code)
                            if len(report.failed) <= 5:
                                print(f"\n  [写入失败] {code}: {exc}")

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
    def _print_summary(self, report: StockMetaReport) -> None:
        rows = self._storage.fetch_all(
            "SELECT COUNT(*) AS cnt, "
            "SUM(CASE WHEN industry IS NOT NULL AND industry != '' THEN 1 ELSE 0 END) AS ind_cnt "
            "FROM trade_stock_meta"
        )
        if rows:
            row = rows[0]
            print("\n数据库 trade_stock_meta 概况:")
            print(
                f"  {row['cnt']:,} 条记录，"
                f"其中 {row['ind_cnt'] or 0:,} 条带行业"
            )
        print("=" * 60)
        print(f"采集完成! 耗时 {report.elapsed:.1f} 秒")
        print(f"  成功: {report.success}/{report.total} 只股票")
        print(f"  行业映射覆盖: {report.n_with_industry} 只")
        if report.failed:
            head = report.failed[:20]
            tail = "..." if len(report.failed) > 20 else ""
            print(f"  失败 {len(report.failed)} 只: {head}{tail}")
        print("=" * 60)
