"""宏观经济数据采集器。

把参考脚本 ``3-宏观数据采集.py`` 的逻辑整合为 ``MacroCollector``：
- 月度指标（CPI/PPI/PMI/M2/社融/LPR）→ ``trade_macro_indicator``
- 日频利率（中/美 10Y 国债）→ ``trade_rate_daily``
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from data_collection.sources.akshare import AkshareDataSource
from data_collection.storage.mysql import MysqlStorage
from config.settings import (
    MACRO_DATA_SOURCE_LABEL,
    MACRO_RATE_HISTORY_YEARS,
    MACRO_RETENTION_YEARS,
)


# ============================================================
# 数据规范化工具（与原脚本同名同语义）
# ============================================================

def _parse_cn_date(series: pd.Series) -> pd.Series:
    """解析中文/数字日期字符串为 ``Timestamp``。

    支持：
    - ``2026年01月份`` / ``2026年01月`` / ``2026.01``
    - ``202601``
    """
    def _parse_one(s: Any) -> pd.Timestamp:
        if pd.isna(s):
            return pd.NaT
        s = str(s).strip()
        m = re.match(r"(\d{4})\D+(\d{1,2})", s)
        if m:
            return pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
        m = re.match(r"^(\d{4})(\d{2})$", s)
        if m:
            return pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
        return pd.NaT

    return series.apply(_parse_one)


def _find_col(columns: pd.Index, keywords: list[str]) -> str | None:
    """在列名中按关键词顺序查找第一个匹配列。"""
    for kw in keywords:
        for col in columns:
            if kw in str(col):
                return col
    return None


# ============================================================
# INSERT SQL（COALESCE 语义：仅在新值非 NULL 时覆盖）
# ============================================================

INSERT_MONTHLY_SQL = """
    INSERT INTO trade_macro_indicator
    (indicator_date, cpi_yoy, ppi_yoy, pmi, m2_yoy, shrzgm, lpr_1y, lpr_5y, data_source)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    cpi_yoy=COALESCE(VALUES(cpi_yoy), cpi_yoy),
    ppi_yoy=COALESCE(VALUES(ppi_yoy), ppi_yoy),
    pmi=COALESCE(VALUES(pmi), pmi),
    m2_yoy=COALESCE(VALUES(m2_yoy), m2_yoy),
    shrzgm=COALESCE(VALUES(shrzgm), shrzgm),
    lpr_1y=COALESCE(VALUES(lpr_1y), lpr_1y),
    lpr_5y=COALESCE(VALUES(lpr_5y), lpr_5y)
"""


INSERT_DAILY_RATES_SQL = """
    INSERT INTO trade_rate_daily
    (rate_date, cn_bond_10y, us_bond_10y, data_source)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    cn_bond_10y=COALESCE(VALUES(cn_bond_10y), cn_bond_10y),
    us_bond_10y=COALESCE(VALUES(us_bond_10y), us_bond_10y)
"""


# ============================================================
# 报表
# ============================================================

@dataclass
class MonthlyReport:
    """月度宏观指标采集结果。"""

    indicators_ok: dict[str, int] = field(default_factory=dict)
    rows_written: int = 0


@dataclass
class DailyRateReport:
    """日频利率采集结果。"""

    rows_written: int = 0


# ============================================================
# 采集器
# ============================================================

class MacroCollector:
    """宏观经济指标采集（CPI/PPI/PMI/M2/社融/LPR/国债收益率）。"""

    DATA_SOURCE_LABEL = MACRO_DATA_SOURCE_LABEL

    def __init__(
        self,
        source: AkshareDataSource,
        storage: MysqlStorage,
        retention_years: int | None = None,
        rate_history_years: int | None = None,
    ) -> None:
        self._source = source
        self._storage = storage
        self._retention_years = retention_years or MACRO_RETENTION_YEARS
        self._rate_history_years = rate_history_years or MACRO_RATE_HISTORY_YEARS

    # ============================================================
    # 月度指标
    # ============================================================

    def collect_monthly(self) -> MonthlyReport:
        """采集并写入 ``trade_macro_indicator``。"""
        print("\n[1/2] 采集月度宏观指标...")

        indicator_frames: dict[str, pd.DataFrame] = {
            "CPI": self._fetch_cpi(),
            "PPI": self._fetch_ppi(),
            "PMI": self._fetch_pmi(),
            "M2": self._fetch_m2(),
            "社融": self._fetch_shrzgm(),
            "LPR": self._fetch_lpr(),
        }

        report = MonthlyReport()
        for name, df in indicator_frames.items():
            report.indicators_ok[name] = len(df)
            print(f"  {name}: {len(df)} 条")

        ok_count = sum(1 for v in report.indicators_ok.values() if v > 0)
        print(f"\n采集结果: {ok_count}/{len(indicator_frames)} 项成功")

        print("\n合并并写入MySQL...")
        merged = self._merge_monthly(indicator_frames)
        if not merged.empty:
            report.rows_written = self._save_monthly(merged)
        print(f"写入 {report.rows_written} 条月度宏观指标")
        return report

    # ----- 各指标抽取 -----

    def _fetch_cpi(self) -> pd.DataFrame:
        print("  采集CPI...")
        df = self._source.get_cpi()
        if df is None or df.empty:
            return pd.DataFrame()
        date_col = df.columns[0]
        value_col = _find_col(df.columns, ["全国-同比增长", "同比增长", "同比"])
        if value_col is None:
            value_col = df.columns[2] if len(df.columns) > 2 else df.columns[1]
        return pd.DataFrame({
            "date": _parse_cn_date(df[date_col]),
            "cpi_yoy": pd.to_numeric(df[value_col], errors="coerce"),
        }).dropna()

    def _fetch_ppi(self) -> pd.DataFrame:
        print("  采集PPI...")
        df = self._source.get_ppi()
        if df is None or df.empty:
            return pd.DataFrame()
        date_col = df.columns[0]
        value_col = _find_col(df.columns, ["当月同比增长", "同比增长", "同比"])
        if value_col is None:
            value_col = df.columns[2] if len(df.columns) > 2 else df.columns[1]
        return pd.DataFrame({
            "date": _parse_cn_date(df[date_col]),
            "ppi_yoy": pd.to_numeric(df[value_col], errors="coerce"),
        }).dropna()

    def _fetch_pmi(self) -> pd.DataFrame:
        print("  采集PMI...")
        df = self._source.get_pmi()
        if df is None or df.empty:
            return pd.DataFrame()
        date_col = df.columns[0]
        value_col = _find_col(df.columns, ["制造业-指标", "制造业", "PMI"])
        if value_col is None:
            value_col = df.columns[1]
        return pd.DataFrame({
            "date": _parse_cn_date(df[date_col]),
            "pmi": pd.to_numeric(df[value_col], errors="coerce"),
        }).dropna()

    def _fetch_m2(self) -> pd.DataFrame:
        print("  采集M2...")
        df = self._source.get_m2()
        if df is None or df.empty:
            return pd.DataFrame()
        date_col = df.columns[0]
        # 原脚本里的关键词包含完整角括号字符
        value_col = _find_col(
            df.columns,
            ["M2）同比增长", "M2）同比", "M2同比"],
        )
        if value_col is None:
            value_col = df.columns[2] if len(df.columns) > 2 else df.columns[1]
        return pd.DataFrame({
            "date": _parse_cn_date(df[date_col]),
            "m2_yoy": pd.to_numeric(df[value_col], errors="coerce"),
        }).dropna()

    def _fetch_shrzgm(self) -> pd.DataFrame:
        print("  采集社融...")
        df = self._source.get_shrzgm()
        if df is None or df.empty:
            return pd.DataFrame()
        date_col = df.columns[0]
        total_col = df.columns[1]
        return pd.DataFrame({
            "date": _parse_cn_date(df[date_col]),
            "shrzgm": pd.to_numeric(df[total_col], errors="coerce"),
        }).dropna()

    def _fetch_lpr(self) -> pd.DataFrame:
        print("  采集LPR...")
        df = self._source.get_lpr()
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df["date"] = pd.to_datetime(df["TRADE_DATE"])
        df["lpr_1y"] = pd.to_numeric(df["LPR1Y"], errors="coerce")
        df["lpr_5y"] = pd.to_numeric(df["LPR5Y"], errors="coerce")
        return df[["date", "lpr_1y", "lpr_5y"]].dropna()

    # ----- 月度合并与写入 -----

    def _merge_monthly(self, dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """把 6 个指标的 DataFrame 合并为月度序列。"""
        result: pd.DataFrame | None = None
        for df in dfs.values():
            if df is None or df.empty:
                continue
            df = df.copy()
            # 统一到月末时间戳，便于跨指标对齐
            df["month"] = df["date"].dt.to_period("M").dt.to_timestamp("M")
            df = df.drop(columns=["date"]).groupby("month").last().reset_index()
            if result is None:
                result = df
            else:
                result = pd.merge(result, df, on="month", how="outer")

        if result is None or result.empty:
            return pd.DataFrame()

        result = result.sort_values("month").reset_index(drop=True)
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=self._retention_years)
        return result[result["month"] >= cutoff]

    def _save_monthly(self, merged: pd.DataFrame) -> int:
        """把合并后的月度数据写入 ``trade_macro_indicator``。"""
        def _val(row: pd.Series, col: str) -> float | None:
            v = row.get(col)
            return float(v) if pd.notna(v) else None

        rows: list[tuple] = []
        for _, row in merged.iterrows():
            rows.append((
                row["month"].strftime("%Y-%m-%d"),
                _val(row, "cpi_yoy"), _val(row, "ppi_yoy"),
                _val(row, "pmi"), _val(row, "m2_yoy"),
                _val(row, "shrzgm"), _val(row, "lpr_1y"), _val(row, "lpr_5y"),
                self.DATA_SOURCE_LABEL,
            ))

        if not rows:
            return 0
        return self._storage.executemany(INSERT_MONTHLY_SQL, rows)

    # ============================================================
    # 日频利率
    # ============================================================

    def collect_daily_rates(self) -> DailyRateReport:
        """采集并写入 ``trade_rate_daily``。"""
        print(f"\n[2/2] 采集日频利率指标...")
        start_date = (
            pd.Timestamp.now() - pd.DateOffset(years=self._rate_history_years)
        ).strftime("%Y%m%d")
        df = self._source.get_bond_yield(start_date=start_date)
        report = DailyRateReport()
        if df is None or df.empty:
            print("  国债收益率: 无数据")
            return report

        rows = self._transform_bond_yield(df)
        if rows:
            report.rows_written = self._storage.executemany(
                INSERT_DAILY_RATES_SQL, rows
            )
        print(f"  国债收益率: {report.rows_written} 条写入 trade_rate_daily")
        return report

    def _transform_bond_yield(self, df: pd.DataFrame) -> list[tuple]:
        """把国债收益率 DataFrame 转换为 ``(date, cn, us, source)`` 行。"""
        cols = df.columns.tolist()
        date_col = cols[0]
        cn10_col = cols[3]   # 中国国债 10Y
        us10_col = cols[9]   # 美国国债 10Y

        rows: list[tuple] = []
        for _, row in df.iterrows():
            d = row[date_col]
            if pd.isna(d):
                continue
            cn = float(row[cn10_col]) if pd.notna(row[cn10_col]) else None
            us = float(row[us10_col]) if pd.notna(row[us10_col]) else None
            if cn is None and us is None:
                continue
            rows.append((
                pd.Timestamp(d).strftime("%Y-%m-%d"),
                cn, us, self.DATA_SOURCE_LABEL,
            ))
        return rows

    # ============================================================
    # 一站式
    # ============================================================

    def collect(self) -> tuple[MonthlyReport, DailyRateReport]:
        """同时执行月度与日频采集，返回两个 report。"""
        monthly = self.collect_monthly()
        daily = self.collect_daily_rates()
        return monthly, daily

    # ============================================================
    # 摘要
    # ============================================================

    def print_summary(self) -> None:
        """打印 ``trade_macro_indicator`` 与 ``trade_rate_daily`` 概况。"""
        for table, label in [
            ("trade_macro_indicator", "月度"),
            ("trade_rate_daily", "日频"),
        ]:
            date_col = "indicator_date" if "macro" in table else "rate_date"
            row = self._storage.fetch_all(
                f"SELECT COUNT(*) AS cnt, "
                f"MIN({date_col}) AS min_date, MAX({date_col}) AS max_date "
                f"FROM {table}"
            )
            if row:
                r = row[0]
                print(f"{table}: {r['cnt']} {label}期 ({r['min_date']} ~ {r['max_date']})")