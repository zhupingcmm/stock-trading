"""财务数据采集器。

把参考脚本 ``2-财务数据采集.py`` 的逻辑（断点续传、批量下载、
跨表指标抽取、UPSERT 写入）整合为 ``FinancialCollector``。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

from data_collection.sources.xtquant import XtQuantDataSource
from data_collection.storage.mysql import MysqlStorage
from config.settings import (
    FINANCIAL_BATCH_SIZE,
    FINANCIAL_DATA_START,
    FINANCIAL_DOWNLOAD_TIMEOUT,
    FINANCIAL_TABLE_LIST,
)


# ---------- 指标提取时引用的 xtquant 表名 ----------
TABLE_LIST = list(FINANCIAL_TABLE_LIST)


# ---------- 字段映射（与原脚本完全一致） ----------
_EPS_FIELDS = ["s_fa_eps_basic"]
_REVENUE_FIELDS = ["revenue", "operating_revenue"]
_NET_PROFIT_FIELDS = ["net_profit_incl_min_int_inc", "net_profit_excl_min_int_inc"]
_OPERATING_COST_FIELDS = ["cost_of_goods_sold", "total_operating_cost"]
_ROE_FIELDS = ["du_return_on_equity", "equity_roe", "net_roe"]
_GROSS_MARGIN_FIELDS = ["sales_gross_profit"]
_TOTAL_ASSETS_FIELDS = ["tot_assets"]
_TOTAL_LIAB_FIELDS = ["tot_liab"]
_TOTAL_EQUITY_FIELDS = ["total_equity", "tot_shrhldr_eqy_incl_min_int"]
_CURRENT_ASSETS_FIELDS = ["total_current_assets"]
_CURRENT_LIAB_FIELDS = ["total_current_liability"]
_CASHFLOW_FIELDS = ["net_cash_flows_oper_act"]


INSERT_SQL = """
    INSERT INTO trade_stock_financial
    (stock_code, report_date, revenue, net_profit, eps, roe, roa,
     gross_margin, net_margin, debt_ratio, current_ratio,
     operating_cashflow, total_assets, total_equity, data_source)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    revenue=VALUES(revenue), net_profit=VALUES(net_profit), eps=VALUES(eps),
    roe=VALUES(roe), roa=VALUES(roa), gross_margin=VALUES(gross_margin),
    net_margin=VALUES(net_margin), debt_ratio=VALUES(debt_ratio),
    current_ratio=VALUES(current_ratio), operating_cashflow=VALUES(operating_cashflow),
    total_assets=VALUES(total_assets), total_equity=VALUES(total_equity)
"""


@dataclass
class FinancialReport:
    """财务采集结果汇总。"""

    total_stocks: int = 0
    success: int = 0
    rows: int = 0
    batches: int = 0
    elapsed: float = 0.0


# ============================================================
# 工具函数（与原脚本同名同语义）
# ============================================================

def _normalize_timetag(ts_val: Any) -> str | None:
    """将 xtquant 的 m_timetag 转换为 ``YYYYMMDD`` 字符串。"""
    if ts_val is None:
        return None
    s = str(ts_val).strip()
    if len(s) == 8 and s.isdigit():
        return s
    try:
        v = float(s)
        if v == 0:
            return None
        if v > 1e12:  # 毫秒时间戳
            v = v / 1000
        return datetime.fromtimestamp(v).strftime("%Y%m%d")
    except (OSError, ValueError, TypeError):
        return None


def _get_field(record: dict | None, field_names: list[str], default: Any = None) -> Any:
    """从记录中按候选字段名取值。"""
    if not record:
        return default
    for name in field_names:
        val = record.get(name)
        if val is not None:
            return val
    return default


def _safe_float(val: Any) -> float | None:
    """安全转 float；NaN 视为 None。"""
    if val is None:
        return None
    try:
        v = float(val)
        return v if v == v else None  # NaN 校验
    except (ValueError, TypeError):
        return None


def _safe_divide(a: Any, b: Any, pct: bool = False) -> float | None:
    """安全除法，结果钳位到 DECIMAL(10,4) 范围（±999999.9999）。"""
    if a is None or b is None:
        return None
    a, b = float(a), float(b)
    if b == 0:
        return None
    result = a / b
    if pct:
        result *= 100
    result = round(result, 4)
    if result > 999999.9999:
        return 999999.9999
    if result < -999999.9999:
        return -999999.9999
    return result


def _build_period_map(data_list: Any) -> dict[str, dict]:
    """将 xtquant 返回的财务数据转换为 ``{报告期YYYYMMDD: 记录}``。"""
    period_map: dict[str, dict] = {}
    if isinstance(data_list, pd.DataFrame):
        for _, row in data_list.iterrows():
            period = _normalize_timetag(row.get("m_timetag"))
            if period:
                period_map[period] = row.to_dict()
    elif isinstance(data_list, list):
        for rec in data_list:
            if isinstance(rec, dict):
                period = _normalize_timetag(rec.get("m_timetag"))
                if period:
                    period_map[period] = rec
    return period_map


# ============================================================
# 采集器
# ============================================================

class FinancialCollector:
    """沪深 A 股财务数据增量采集。"""

    BATCH_SIZE = FINANCIAL_BATCH_SIZE
    DATA_START = FINANCIAL_DATA_START
    DATA_END = date.today().strftime("%Y%m%d")
    TABLE_LIST = TABLE_LIST
    DOWNLOAD_TIMEOUT = FINANCIAL_DOWNLOAD_TIMEOUT

    DATA_SOURCE_LABEL = "qmt"  # 与原脚本保持一致

    def __init__(
        self,
        source: XtQuantDataSource,
        storage: MysqlStorage,
        batch_size: int | None = None,
        data_start: str | None = None,
        post_download_sleep: float | None = None,
    ) -> None:
        self._source = source
        self._storage = storage
        self._batch_size = batch_size or self.BATCH_SIZE
        self._data_start = data_start or self.DATA_START
        self._data_end = self.DATA_END
        # ``time.sleep(1)`` 是给真实 QMT 缓存写入留的等待窗口；测试时可设为 0
        self._post_download_sleep = (
            post_download_sleep
            if post_download_sleep is not None
            else 1.0
        )

    # ----- 断点续传 -----
    def get_existing_stocks(self) -> set[str]:
        """查询 DB 中已有财务数据的股票集合。"""
        rows = self._storage.fetch_all(
            "SELECT DISTINCT stock_code FROM trade_stock_financial"
        )
        return {r["stock_code"] for r in rows}

    # ----- 单只提取 -----
    def extract_periods(self, data: dict, stock_code: str) -> list[dict]:
        """从 xtquant 财务数据中提取所有报告期的综合财务指标。"""
        stock_data = data.get(stock_code, {})
        if not stock_data:
            return []

        pershare_map = _build_period_map(stock_data.get("PershareIndex", []))
        balance_map = _build_period_map(stock_data.get("Balance", []))
        income_map = _build_period_map(stock_data.get("Income", []))
        cashflow_map = _build_period_map(stock_data.get("CashFlow", []))

        all_periods = sorted(
            set(
                list(pershare_map.keys())
                + list(balance_map.keys())
                + list(income_map.keys())
                + list(cashflow_map.keys())
            )
        )

        records: list[dict] = []
        for period in all_periods:
            ps = pershare_map.get(period, {})
            bal = balance_map.get(period, {})
            inc = income_map.get(period, {})
            cf = cashflow_map.get(period, {})

            eps = _get_field(ps, _EPS_FIELDS)
            revenue = _get_field(inc, _REVENUE_FIELDS)
            net_profit = _get_field(inc, _NET_PROFIT_FIELDS)
            operating_cost = _get_field(inc, _OPERATING_COST_FIELDS)

            roe = _get_field(ps, _ROE_FIELDS)
            gross_margin = _get_field(ps, _GROSS_MARGIN_FIELDS)
            if gross_margin is None and revenue and operating_cost:
                r, c = float(revenue), float(operating_cost)
                if r > 0:
                    gross_margin = round((r - c) / r * 100, 4)

            total_assets = _get_field(bal, _TOTAL_ASSETS_FIELDS)
            total_liab = _get_field(bal, _TOTAL_LIAB_FIELDS)
            total_equity = _get_field(bal, _TOTAL_EQUITY_FIELDS)
            current_assets = _get_field(bal, _CURRENT_ASSETS_FIELDS)
            current_liab = _get_field(bal, _CURRENT_LIAB_FIELDS)

            roa = _safe_divide(net_profit, total_assets, pct=True)
            if roe is None and net_profit and total_equity:
                roe = _safe_divide(net_profit, total_equity, pct=True)

            net_margin = _safe_divide(net_profit, revenue, pct=True)
            debt_ratio = _safe_divide(total_liab, total_assets, pct=True)
            current_ratio = _safe_divide(current_assets, current_liab)

            operating_cashflow = _get_field(cf, _CASHFLOW_FIELDS)

            records.append({
                "report_date": period,
                "revenue": _safe_float(revenue),
                "net_profit": _safe_float(net_profit),
                "eps": _safe_float(eps),
                "roe": _safe_float(roe),
                "roa": _safe_float(roa),
                "gross_margin": _safe_float(gross_margin),
                "net_margin": _safe_float(net_margin),
                "debt_ratio": _safe_float(debt_ratio),
                "current_ratio": _safe_float(current_ratio),
                "operating_cashflow": _safe_float(operating_cashflow),
                "total_assets": _safe_float(total_assets),
                "total_equity": _safe_float(total_equity),
            })

        return records

    # ----- 批量下载与写入 -----
    def process_batch(self, batch_codes: list[str]) -> tuple[int, int]:
        """批量下载并写入，返回 ``(rows_written, stocks_processed)``。"""
        done = [False]

        def on_done(_data: dict) -> None:
            done[0] = True

        self._source.download_financial_data(
            stocks=batch_codes,
            tables=self.TABLE_LIST,
            start_time=self._data_start,
            end_time=self._data_end,
            callback=on_done,
        )

        # 等待回调，最长 self.DOWNLOAD_TIMEOUT 秒
        deadline = time.time() + self.DOWNLOAD_TIMEOUT
        while not done[0] and time.time() < deadline:
            time.sleep(0.5)
        # 多等一拍，确保 QMT 把数据写入本地缓存（生产环境需要，测试可关）
        if self._post_download_sleep > 0:
            time.sleep(self._post_download_sleep)

        data = self._source.get_financial_data(
            stocks=batch_codes,
            tables=self.TABLE_LIST,
            start_time=self._data_start,
            end_time=self._data_end,
            report_type="report_time",
        )
        if not data:
            return 0, 0

        batch_rows = 0
        all_rows: list[tuple] = []
        for code in batch_codes:
            records = self.extract_periods(data, code)
            for rec in records:
                p = rec["report_date"]
                report_date = f"{p[:4]}-{p[4:6]}-{p[6:8]}"
                all_rows.append((
                    code, report_date,
                    rec["revenue"], rec["net_profit"], rec["eps"],
                    rec["roe"], rec["roa"],
                    rec["gross_margin"], rec["net_margin"],
                    rec["debt_ratio"], rec["current_ratio"],
                    rec["operating_cashflow"],
                    rec["total_assets"], rec["total_equity"],
                    self.DATA_SOURCE_LABEL,
                ))

        if all_rows:
            batch_rows = self._storage.executemany(INSERT_SQL, all_rows)

        return batch_rows, len(batch_codes)

    # ----- 主流程 -----
    def collect(
        self,
        mode: str = "test",
        test_stock: str = "600519.SH",
        sector: str = "沪深A股",
        data_start: str | None = None,
        stocks: Iterable[str] | None = None,
    ) -> FinancialReport:
        """执行财务数据采集。

        ``mode='test'`` 只采集 ``test_stock``；``mode='full'`` 拉整个 ``sector``。
        """
        report = FinancialReport()
        start_ts = time.time()

        data_start = data_start or self._data_start

        print("=" * 60)
        print("财务数据采集 (MiniQMT -> MySQL)")
        if mode == "test":
            print("[测试模式] 只采集贵州茅台")
        else:
            print(f"[全量模式] 采集{sector}, 每批{self._batch_size}只")
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

        # 2) 断点续传
        print("查询数据库已有数据...")
        existing = self.get_existing_stocks()
        pending = [c for c in all_codes if c not in existing]
        print(f"  已采集: {len(existing)} 只, 待采集: {len(pending)} 只")

        if not pending:
            print("\n全部已采集完成，无需下载")
            report.elapsed = time.time() - start_ts
            self._print_summary()
            return report

        # 3) 分批
        batches = [
            pending[i : i + self._batch_size]
            for i in range(0, len(pending), self._batch_size)
        ]
        report.batches = len(batches)
        report.total_stocks = len(pending)

        print(
            f"\n开始批量下载（共 {report.batches} 批, "
            f"每批最多 {self._batch_size} 只）..."
        )

        total_rows = 0
        total_done_stocks = 0

        for i, batch in enumerate(batches):
            sys.stdout.write(
                f"\r  批次 {i + 1}/{report.batches} 下载中... "
                f"({total_done_stocks}/{report.total_stocks})    "
            )
            sys.stdout.flush()

            batch_rows, _batch_ok = self.process_batch(batch)
            total_rows += batch_rows
            total_done_stocks += len(batch)

            elapsed = time.time() - start_ts
            speed = total_done_stocks / elapsed if elapsed > 0 else 0
            eta = (report.total_stocks - total_done_stocks) / speed if speed > 0 else 0
            sys.stdout.write(
                f"\r  批次 {i + 1}/{report.batches} 完成 | "
                f"进度 {total_done_stocks}/{report.total_stocks} "
                f"({total_done_stocks * 100 / report.total_stocks:.1f}%) | "
                f"{speed:.1f} 只/秒 | 剩余约 {eta:.0f}秒 | "
                f"写入 {total_rows:,} 条    "
            )
            sys.stdout.flush()
        print()

        report.elapsed = time.time() - start_ts
        report.rows = total_rows
        report.success = total_done_stocks
        self._print_summary(report)
        return report

    # ----- 摘要 -----
    def _print_summary(self, report: FinancialReport | None = None) -> None:
        summary = self._storage.fetch_all(
            "SELECT COUNT(DISTINCT stock_code) AS stock_cnt, COUNT(*) AS row_cnt, "
            "MIN(report_date) AS min_date, MAX(report_date) AS max_date "
            "FROM trade_stock_financial"
        )
        if summary:
            row = summary[0]
            print("\n数据库 trade_stock_financial 概况:")
            print(
                f"  {row['stock_cnt']} 只股票, {row['row_cnt']:,} 条记录\n"
                f"  日期范围: {row['min_date']} ~ {row['max_date']}"
            )
        if report is not None:
            print("=" * 60)
            print(f"财务数据采集完成! 耗时 {report.elapsed:.1f} 秒")
            print(f"  本次处理: {report.success}/{report.total_stocks} 只股票")
            print(f"  总写入: {report.rows:,} 条记录")
            print("=" * 60)