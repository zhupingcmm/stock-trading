"""``MacroCollector`` 单元测试。

AkShare 与 MySQL 都通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_collection.collectors.macro import (
    INSERT_DAILY_RATES_SQL,
    INSERT_MONTHLY_SQL,
    DailyRateReport,
    MacroCollector,
    MonthlyReport,
    _find_col,
    _parse_cn_date,
)


# ---------- 工具函数测试 ----------

class TestParseCnDate:
    def test_chinese_year_month(self):
        s = pd.Series(["2026年02月份", "2025年12月份"])
        result = _parse_cn_date(s)
        assert result.iloc[0] == pd.Timestamp("2026-02-01")
        assert result.iloc[1] == pd.Timestamp("2025-12-01")

    def test_pure_digits(self):
        s = pd.Series(["202602", "202601"])
        result = _parse_cn_date(s)
        assert result.iloc[0] == pd.Timestamp("2026-02-01")
        assert result.iloc[1] == pd.Timestamp("2026-01-01")

    def test_dot_separator(self):
        s = pd.Series(["2026.02"])
        result = _parse_cn_date(s)
        assert result.iloc[0] == pd.Timestamp("2026-02-01")

    def test_nan(self):
        s = pd.Series([None, float("nan")])
        result = _parse_cn_date(s)
        assert result.isna().all()

    def test_invalid(self):
        s = pd.Series(["not a date"])
        result = _parse_cn_date(s)
        assert result.isna().all()


class TestFindCol:
    def test_finds_first_keyword_match(self):
        cols = pd.Index(["date_col", "全国-同比增长", "其他"])
        assert _find_col(cols, ["全国-同比增长", "同比增长"]) == "全国-同比增长"

    def test_falls_back_to_next_keyword(self):
        cols = pd.Index(["date_col", "同比增长", "其他"])
        # 第一个关键词没匹配，第二个匹配到
        assert _find_col(cols, ["全国-同比增长", "同比增长"]) == "同比增长"

    def test_returns_none(self):
        cols = pd.Index(["date_col", "其他"])
        assert _find_col(cols, ["全国-同比增长", "同比增长"]) is None

    def test_priority_among_keywords(self):
        cols = pd.Index(["制造业-指标值", "制造业"])
        assert _find_col(cols, ["制造业-指标", "制造业"]) == "制造业-指标值"


# ---------- 单指标抽取测试 ----------

def _mock_cpi_df() -> pd.DataFrame:
    """模拟 akshare macro_china_cpi() 返回格式。"""
    return pd.DataFrame({
        "日期": ["2026年02月份", "2026年01月份"],
        "全国-同比增长": [102.5, 102.1],
    })


def test_fetch_cpi_parses_correctly() -> None:
    source = MagicMock()
    source.get_cpi.return_value = _mock_cpi_df()
    collector = MacroCollector(source, MagicMock())

    result = collector._fetch_cpi()
    assert len(result) == 2
    assert "cpi_yoy" in result.columns
    assert "date" in result.columns
    assert result["cpi_yoy"].iloc[0] == 102.5
    assert result["date"].iloc[0] == pd.Timestamp("2026-02-01")


def test_fetch_lpr_uses_trade_date_columns() -> None:
    source = MagicMock()
    source.get_lpr.return_value = pd.DataFrame({
        "TRADE_DATE": ["2026-02-20", "2026-01-20"],
        "LPR1Y": [3.45, 3.45],
        "LPR5Y": [3.95, 3.95],
    })
    collector = MacroCollector(source, MagicMock())
    result = collector._fetch_lpr()
    assert len(result) == 2
    assert "lpr_1y" in result.columns
    assert "lpr_5y" in result.columns
    assert result["lpr_1y"].iloc[0] == 3.45


def test_fetch_returns_empty_on_empty_source() -> None:
    source = MagicMock()
    source.get_cpi.return_value = pd.DataFrame()
    collector = MacroCollector(source, MagicMock())
    assert collector._fetch_cpi().empty


# ---------- 合并与写入测试 ----------

def test_merge_monthly_combines_on_month_end() -> None:
    """两个指标的日期略有差异，应按月末时间戳对齐。"""
    source = MagicMock()
    storage = MagicMock()
    storage.executemany.return_value = 1
    collector = MacroCollector(source, storage, retention_years=10)

    indicator_frames = {
        "CPI": pd.DataFrame({
            "date": [pd.Timestamp("2026-02-15"), pd.Timestamp("2026-01-15")],
            "cpi_yoy": [102.5, 102.1],
        }),
        "PMI": pd.DataFrame({
            "date": [pd.Timestamp("2026-02-28"), pd.Timestamp("2026-01-31")],
            "pmi": [50.5, 50.0],
        }),
    }
    merged = collector._merge_monthly(indicator_frames)
    assert len(merged) == 2
    # 月末对齐：两个 2 月份合并成一行
    assert list(merged.columns) == ["month", "cpi_yoy", "pmi"]
    feb_row = merged[merged["month"] == pd.Timestamp("2026-02-28")].iloc[0]
    assert feb_row["cpi_yoy"] == 102.5
    assert feb_row["pmi"] == 50.5


def test_merge_monthly_respects_retention_years() -> None:
    source = MagicMock()
    collector = MacroCollector(source, MagicMock(), retention_years=2)
    indicator_frames = {
        "CPI": pd.DataFrame({
            "date": [pd.Timestamp("2020-01-15"), pd.Timestamp.now()],
            "cpi_yoy": [100.0, 102.0],
        }),
    }
    merged = collector._merge_monthly(indicator_frames)
    # 2020 的数据应被剔除
    assert len(merged) == 1
    assert merged["cpi_yoy"].iloc[0] == 102.0


def test_save_monthly_uses_coalesce_upsert() -> None:
    """UPSERT 必须使用 COALESCE 语义，保留现有值当新值为 NULL。"""
    assert "ON DUPLICATE KEY UPDATE" in INSERT_MONTHLY_SQL
    for col in ("cpi_yoy", "ppi_yoy", "pmi", "m2_yoy",
                "shrzgm", "lpr_1y", "lpr_5y"):
        assert f"{col}=COALESCE(VALUES({col}), {col})" in INSERT_MONTHLY_SQL


# ---------- 日频利率测试 ----------

def _mock_bond_yield_df() -> pd.DataFrame:
    """模拟 ak.bond_zh_us_rate() 的返回：多列，第 0 列是日期，第 3 列是 CN 10Y，第 9 列是 US 10Y。"""
    cols = [f"col_{i}" for i in range(12)]
    cols[0] = "date"
    cols[3] = "中国国债收益率10年"
    cols[9] = "美国国债收益率10年"
    return pd.DataFrame([
        ["2026-02-10", None, None, 2.50, None, None, None, None, None, 4.25, None, None],
        ["2026-02-11", None, None, 2.48, None, None, None, None, None, 4.30, None, None],
        ["2026-02-12", None, None, None, None, None, None, None, None, None, None, None],  # 全空应跳过
    ], columns=cols)


def test_transform_bond_yield_skips_empty_rows() -> None:
    source = MagicMock()
    collector = MacroCollector(source, MagicMock(), rate_history_years=3)
    rows = collector._transform_bond_yield(_mock_bond_yield_df())
    assert len(rows) == 2  # 第三行 cn 和 us 都为 None，应被跳过
    assert rows[0] == ("2026-02-10", 2.50, 4.25, "akshare")
    assert rows[1] == ("2026-02-11", 2.48, 4.30, "akshare")


def test_collect_daily_rates_calls_source_and_storage() -> None:
    source = MagicMock()
    source.get_bond_yield.return_value = _mock_bond_yield_df()
    storage = MagicMock()
    storage.executemany.return_value = 2

    collector = MacroCollector(source, storage, rate_history_years=3)
    report = collector.collect_daily_rates()

    assert report.rows_written == 2
    source.get_bond_yield.assert_called_once()
    sql, rows = storage.executemany.call_args.args
    assert sql.strip() == INSERT_DAILY_RATES_SQL.strip()
    assert len(rows) == 2


def test_collect_daily_rates_handles_empty_source() -> None:
    source = MagicMock()
    source.get_bond_yield.return_value = pd.DataFrame()
    storage = MagicMock()
    collector = MacroCollector(source, storage, rate_history_years=3)
    report = collector.collect_daily_rates()
    assert report.rows_written == 0
    storage.executemany.assert_not_called()


def test_insert_daily_rates_sql_uses_coalesce() -> None:
    """日频利率 UPSERT 也使用 COALESCE 语义。"""
    assert "ON DUPLICATE KEY UPDATE" in INSERT_DAILY_RATES_SQL
    assert "cn_bond_10y=COALESCE(VALUES(cn_bond_10y), cn_bond_10y)" in INSERT_DAILY_RATES_SQL
    assert "us_bond_10y=COALESCE(VALUES(us_bond_10y), us_bond_10y)" in INSERT_DAILY_RATES_SQL


# ---------- 端到端 ----------

def test_collect_full_flow() -> None:
    """collect() 应同时调用月度与日频采集。"""
    source = MagicMock()
    # 月度
    source.get_cpi.return_value = _mock_cpi_df()
    source.get_ppi.return_value = pd.DataFrame()
    source.get_pmi.return_value = pd.DataFrame()
    source.get_m2.return_value = pd.DataFrame()
    source.get_shrzgm.return_value = pd.DataFrame()
    source.get_lpr.return_value = pd.DataFrame()
    # 日频
    source.get_bond_yield.return_value = _mock_bond_yield_df()

    storage = MagicMock()
    # 按实际行数返回 rowcount
    storage.executemany.side_effect = lambda sql, rows: len(rows)

    collector = MacroCollector(source, storage)
    monthly, daily = collector.collect()

    # CPI 拿到 2 条，PPI/PMI/M2/社融/LPR 都是空 → 月度合并后只有 1 行（仅 CPI 列有值）
    assert monthly.indicators_ok["CPI"] == 2
    # 国债收益率 mock 含 2 行有效数据
    assert daily.rows_written == 2


# ---------- 报表默认值 ----------

def test_monthly_report_defaults() -> None:
    r = MonthlyReport()
    assert r.indicators_ok == {}
    assert r.rows_written == 0


def test_daily_rate_report_defaults() -> None:
    r = DailyRateReport()
    assert r.rows_written == 0