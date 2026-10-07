"""研报数据采集器。

把参考脚本 ``5-研报数据采集.py`` 的逻辑整合为 ``ReportCollector``：
- 东方财富机构评级明细（``ak.stock_institute_recommend_detail``）
  → ``trade_report_consensus``（source_file='eastmoney'）
- 同花顺盈利预测一致预期（``ak.stock_profit_forecast_ths``）
  → ``trade_report_consensus``（source_file='ths_consensus'）

核心去重策略：
  同一券商仅在「评级」或「目标价」发生变化时才视为新观点并写入。
  这种「只保留观点变化」的做法与参考脚本语义一致。
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

from config.settings import (
    REPORT_MAX_RECOMMEND_ROWS,
    REPORT_NUM_WORKERS,
    REPORT_RECENT_DAYS,
    REPORT_SOURCE_EASTMONEY,
    REPORT_SOURCE_THS,
)
from data_collection.sources.akshare import AkshareDataSource
from data_collection.storage.mysql import MysqlStorage


# 研报表 UPSERT：评级/目标价总是用新值覆盖
INSERT_RECOMMEND_SQL = """
    INSERT INTO trade_report_consensus
    (stock_code, broker, report_date, rating, target_price,
     eps_forecast_current, eps_forecast_next, revenue_forecast, source_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    rating=VALUES(rating), target_price=VALUES(target_price)
"""

# 盈利预测一致预期 UPSERT：覆盖 EPS / 净利润预测
INSERT_FORECAST_SQL = """
    INSERT INTO trade_report_consensus
    (stock_code, broker, report_date, rating, target_price,
     eps_forecast_current, eps_forecast_next, revenue_forecast, source_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    eps_forecast_current=VALUES(eps_forecast_current),
    eps_forecast_next=VALUES(eps_forecast_next),
    revenue_forecast=VALUES(revenue_forecast)
"""

# 东方财富原始列名 → 内部字段名映射
_RECOMMEND_COLUMNS = [
    "stock_code_raw", "stock_name", "target_price", "rating",
    "broker", "analyst", "industry", "report_date",
]


@dataclass
class ReportReport:
    """研报采集结果汇总。"""

    total: int = 0
    processed: int = 0
    recommend_saved: int = 0
    forecast_saved: int = 0
    skipped_recent: int = 0
    elapsed: float = 0.0


class ReportCollector:
    """沪深 A 股研报数据采集。"""

    RECOMMEND_COLUMNS = _RECOMMEND_COLUMNS

    def __init__(
        self,
        source: AkshareDataSource,
        storage: MysqlStorage,
        workers: int | None = None,
        recent_days: int | None = None,
        max_recommend_rows: int | None = None,
    ) -> None:
        self._source = source
        self._storage = storage
        self._workers = workers or REPORT_NUM_WORKERS
        self._recent_days = recent_days if recent_days is not None else REPORT_RECENT_DAYS
        self._max_recommend_rows = (
            max_recommend_rows if max_recommend_rows is not None else REPORT_MAX_RECOMMEND_ROWS
        )

    # ============================================================
    # 辅助查询
    # ============================================================

    def get_all_stocks(self) -> list[str]:
        """从 ``trade_stock_daily`` 拿所有出现过行情的股票。"""
        rows = self._storage.fetch_all(
            "SELECT DISTINCT stock_code FROM trade_stock_daily"
        )
        return [r["stock_code"] for r in rows]

    def get_recently_collected(self) -> set[str]:
        """返回 ``recent_days`` 天内已有研报记录的股票集合。"""
        rows = self._storage.fetch_all(
            "SELECT DISTINCT stock_code FROM trade_report_consensus "
            "WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)",
            (self._recent_days,),
        )
        return {r["stock_code"] for r in rows}

    def get_existing_opinions(self, stock_code: str) -> dict[str, dict]:
        """读取该股票各券商的「最新观点」，用于增量去重。"""
        rows = self._storage.fetch_all(
            "SELECT broker, rating, target_price "
            "FROM trade_report_consensus "
            "WHERE stock_code=%s AND source_file=%s "
            "ORDER BY report_date DESC",
            (stock_code, REPORT_SOURCE_EASTMONEY),
        )
        existing: dict[str, dict] = {}
        for r in rows:
            b = r["broker"]
            if b not in existing:
                existing[b] = {
                    "rating": r["rating"],
                    "target_price": r["target_price"],
                }
        return existing

    # ============================================================
    # 单只股票
    # ============================================================

    def fetch_institute_recommend(self, stock_code: str) -> pd.DataFrame:
        """从 AkShare 拉取该股票的机构评级明细，做列名规整。"""
        code_num = stock_code.split(".")[0]
        try:
            df = self._source.get_institute_recommend(code_num)
        except Exception:
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()

        # 部分 akshare 列返回顺序可能变化，按实际列数安全截取
        if len(df.columns) < len(self.RECOMMEND_COLUMNS):
            return pd.DataFrame()
        df = df.iloc[:, : len(self.RECOMMEND_COLUMNS)].copy()
        df.columns = self.RECOMMEND_COLUMNS
        df = df.head(self._max_recommend_rows)
        df["target_price"] = pd.to_numeric(df["target_price"], errors="coerce")
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
        df["stock_code"] = stock_code
        return df

    def deduplicate_recommend(self, df: pd.DataFrame) -> pd.DataFrame:
        """「只保留观点变化」：同一券商仅在评级/目标价与上一条不同时保留。"""
        if df is None or df.empty:
            return pd.DataFrame()

        df_sorted = df.sort_values("report_date", ascending=True).reset_index(drop=True)

        last_opinion: dict[str, dict] = {}
        keep_indices: list[int] = []

        for idx, row in df_sorted.iterrows():
            broker = str(row["broker"])
            rating = str(row["rating"])
            tp_raw = row["target_price"]
            tp = float(tp_raw) if pd.notna(tp_raw) else None

            prev = last_opinion.get(broker)
            if prev is None or prev["rating"] != rating or prev["target_price"] != tp:
                keep_indices.append(idx)
                last_opinion[broker] = {"rating": rating, "target_price": tp}

        return df_sorted.loc[keep_indices]

    def save_recommend(
        self,
        stock_code: str,
        recommend_df: pd.DataFrame,
        existing_opinions: dict[str, dict] | None = None,
    ) -> int:
        """去重后写入 ``trade_report_consensus``（source_file='eastmoney'）。

        ``existing_opinions`` 提供 DB 中各券商的最新观点；
        当新行的 (rating, target_price) 与已有完全相同时跳过（避免冗余 UPDATE）。
        """
        if recommend_df is None or recommend_df.empty:
            return 0

        existing_opinions = existing_opinions or {}
        saved = 0

        for _, row in recommend_df.iterrows():
            broker = str(row["broker"])[:50]
            rating = str(row["rating"])[:20]
            report_date = (
                row["report_date"].strftime("%Y-%m-%d")
                if pd.notna(row["report_date"])
                else None
            )
            tp_raw = row["target_price"]
            target_price = float(tp_raw) if pd.notna(tp_raw) else None

            # 增量去重：与 DB 已有最新观点相同则跳过
            prev = existing_opinions.get(broker)
            if prev:
                prev_tp = float(prev["target_price"]) if prev["target_price"] is not None else None
                if prev["rating"] == rating and prev_tp == target_price:
                    continue

            self._storage.execute(INSERT_RECOMMEND_SQL, (
                stock_code, broker, report_date, rating, target_price,
                None, None, None, REPORT_SOURCE_EASTMONEY,
            ))
            saved += 1
            existing_opinions[broker] = {
                "rating": rating,
                "target_price": target_price,
            }

        return saved

    def fetch_profit_forecast(self, stock_code: str) -> dict[str, pd.DataFrame]:
        """从同花顺拉取盈利预测一致预期（EPS + 净利润）。"""
        code_num = stock_code.split(".")[0]
        forecasts: dict[str, pd.DataFrame] = {}
        for indicator in ("预测年报每股收益", "预测年报净利润"):
            try:
                df = self._source.get_profit_forecast_ths(code_num, indicator)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            try:
                df = df.copy()
                df.columns = ["year", "analyst_count", "min_val", "mean_val", "max_val", "industry_avg"]
            except Exception:
                continue
            forecasts[indicator] = df
        return forecasts

    def save_forecast(
        self,
        stock_code: str,
        forecasts: dict[str, pd.DataFrame],
    ) -> int:
        """将一致预期写入 ``trade_report_consensus``（source_file='ths_consensus'）。

        一致预期作为「一行特殊记录」：broker="一致预期(N家)" + report_date=today。
        依赖 (stock_code, broker, report_date) UNIQUE KEY。
        """
        if not forecasts:
            return 0

        eps_df = forecasts.get("预测年报每股收益")
        if eps_df is None or eps_df.empty:
            return 0

        profit_df = forecasts.get("预测年报净利润")

        try:
            analyst_count = int(eps_df.iloc[0]["analyst_count"])
            eps_current = float(eps_df.iloc[0]["mean_val"])
        except (ValueError, TypeError, KeyError):
            return 0

        eps_next: float | None = None
        if len(eps_df) > 1:
            try:
                eps_next = float(eps_df.iloc[1]["mean_val"])
            except (ValueError, TypeError):
                eps_next = None

        profit_current: float | None = None
        if profit_df is not None and not profit_df.empty:
            try:
                profit_current = float(profit_df.iloc[0]["mean_val"])
            except (ValueError, TypeError):
                profit_current = None

        today = date.today().strftime("%Y-%m-%d")
        self._storage.execute(INSERT_FORECAST_SQL, (
            stock_code,
            f"一致预期({analyst_count}家)",
            today, None, None,
            eps_current, eps_next, profit_current,
            REPORT_SOURCE_THS,
        ))
        return 1

    def process_one_stock(self, stock_code: str) -> tuple[str, int, int]:
        """采集单只股票的评级 + 一致预期，返回 (code, recommend_saved, forecast_saved)。"""
        recommend_count = 0
        forecast_count = 0

        raw_df = self.fetch_institute_recommend(stock_code)
        if not raw_df.empty:
            existing = self.get_existing_opinions(stock_code)
            deduped = self.deduplicate_recommend(raw_df)
            recommend_count = self.save_recommend(stock_code, deduped, existing)

        # 与参考脚本一致：两个采集之间留 0.5s 间隔
        time.sleep(0.5)

        forecasts = self.fetch_profit_forecast(stock_code)
        if forecasts:
            forecast_count = self.save_forecast(stock_code, forecasts)

        return stock_code, recommend_count, forecast_count

    # ============================================================
    # 主流程
    # ============================================================

    def collect(
        self,
        mode: str = "full",
        test_stock: str = "600519.SH",
        stocks: Iterable[str] | None = None,
    ) -> ReportReport:
        """执行研报采集。

        ``mode='test'`` 仅采集 ``test_stock``；``mode='full'`` 从
        ``trade_stock_daily`` 拉全量股票列表，并跳过近 ``recent_days`` 天已采过的。
        """
        report = ReportReport()
        start_ts = time.time()

        print("=" * 60)
        print("研报数据采集 (AkShare -> MySQL)")
        if mode == "test":
            print("[测试模式] 只采集贵州茅台")
        else:
            print(f"[全量模式] 采集全A股, {self._workers} 线程并行")
        print("=" * 60)

        # 1) 股票列表
        if stocks is not None:
            all_codes = list(stocks)
            report.skipped_recent = 0
            print(f"\n使用传入的股票池: {len(all_codes)} 只")
        elif mode == "test":
            all_codes = [test_stock]
            report.skipped_recent = 0
            print(f"\n[测试模式] 只采集 {test_stock}")
        else:
            all_codes = self.get_all_stocks()
            print(f"\n全量股票: {len(all_codes)} 只")

            collected = self.get_recently_collected()
            if collected:
                all_codes = [c for c in all_codes if c not in collected]
                report.skipped_recent = len(collected)
                print(
                    f"跳过近 {self._recent_days} 天已采集: "
                    f"{report.skipped_recent} 只, 待采集: {len(all_codes)} 只"
                )

        if not all_codes:
            print("无股票需要采集")
            report.elapsed = time.time() - start_ts
            self._print_summary(report)
            return report

        report.total = len(all_codes)
        done = 0

        print(f"\n开始采集 ({self._workers} 线程)...")

        with ThreadPoolExecutor(max_workers=self._workers) as executor:
            futures = {
                executor.submit(self.process_one_stock, code): code
                for code in all_codes
            }

            for future in as_completed(futures):
                try:
                    _,  rec, fct = future.result()
                    report.recommend_saved += rec
                    report.forecast_saved += fct
                except Exception:
                    pass
                done += 1

                if done % 100 == 0 or done == report.total:
                    elapsed = time.time() - start_ts
                    speed = done / elapsed if elapsed > 0 else 0
                    eta = (report.total - done) / speed if speed > 0 else 0
                    sys.stdout.write(
                        f"\r  [{done}/{report.total}] {done * 100 / report.total:.1f}% "
                        f"| {speed:.1f}/s | ETA {eta:.0f}s "
                        f"| recommend {report.recommend_saved} "
                        f"forecast {report.forecast_saved}    "
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

    def _print_summary(self, report: ReportReport | None = None) -> None:
        rows = self._storage.fetch_all(
            "SELECT source_file, COUNT(*) AS cnt "
            "FROM trade_report_consensus GROUP BY source_file"
        )
        if rows:
            print("\ntrade_report_consensus 概况:")
            for r in rows:
                print(f"  {r['source_file']}: {r['cnt']} 条")
        if report is not None:
            print("=" * 60)
            print(f"研报采集完成! 耗时 {report.elapsed:.1f} 秒")
            print(
                f"  处理: {report.processed}/{report.total} 只股票 "
                f"(跳过近 {self._recent_days} 天已采集 {report.skipped_recent} 只)"
            )
            print(
                f"  评级: {report.recommend_saved} 条(去重后新增), "
                f"一致预期: {report.forecast_saved} 条"
            )
            print("=" * 60)