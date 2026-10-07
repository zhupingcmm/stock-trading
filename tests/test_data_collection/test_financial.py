"""``FinancialCollector`` 单元测试。

xtquant 与 MySQL 通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from data_collection.collectors.financial import (
    INSERT_SQL,
    FinancialCollector,
    FinancialReport,
    _normalize_timetag,
    _safe_divide,
    _safe_float,
)


# ---------- 工具函数测试 ----------

class TestNormalizeTimetag:
    def test_already_yyyymmdd(self):
        assert _normalize_timetag("20231231") == "20231231"

    def test_none(self):
        assert _normalize_timetag(None) is None

    def test_zero_string(self):
        assert _normalize_timetag("0") is None

    def test_seconds_timestamp(self):
        # 2024-01-15 00:00:00 UTC = 1705276800
        assert _normalize_timetag(1705276800) == "20240115"

    def test_milliseconds_timestamp(self):
        # 同样日期的毫秒表示
        assert _normalize_timetag(1705276800000) == "20240115"

    def test_invalid(self):
        assert _normalize_timetag("not a number") is None


class TestSafeFloat:
    def test_none(self):
        assert _safe_float(None) is None

    def test_valid(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_invalid(self):
        assert _safe_float("abc") is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None


class TestSafeDivide:
    def test_normal(self):
        assert _safe_divide(10, 2) == 5.0

    def test_pct(self):
        assert _safe_divide(1, 4, pct=True) == 25.0

    def test_div_zero(self):
        assert _safe_divide(10, 0) is None

    def test_none_inputs(self):
        assert _safe_divide(None, 1) is None
        assert _safe_divide(1, None) is None

    def test_clamp_positive(self):
        assert _safe_divide(1e10, 1) == 999999.9999

    def test_clamp_negative(self):
        assert _safe_divide(-1e10, 1) == -999999.9999

    def test_round_4(self):
        # 1/3 → 0.3333
        assert _safe_divide(1, 3) == pytest.approx(0.3333, abs=1e-4)


# ---------- 提取记录测试 ----------

def _make_period_row(period_yyyymmdd: str, **fields) -> dict:
    """构造单期财务记录，``m_timetag`` 已规范为字符串。"""
    row = {"m_timetag": period_yyyymmdd}
    row.update(fields)
    return row


def test_extract_periods_with_full_data() -> None:
    """四张表都有数据时，应能拼出完整指标。"""
    collector = FinancialCollector(MagicMock(), MagicMock())

    pershare = [_make_period_row(
        "20240630",
        s_fa_eps_basic=10.0,
        du_return_on_equity=15.0,
        sales_gross_profit=45.0,
    )]
    income = [_make_period_row(
        "20240630",
        revenue=1000.0,
        net_profit_incl_min_int_inc=200.0,
    )]
    balance = [_make_period_row(
        "20240630",
        tot_assets=5000.0,
        tot_liab=2000.0,
        total_equity=3000.0,
        total_current_assets=1500.0,
        total_current_liability=800.0,
    )]
    cashflow = [_make_period_row(
        "20240630",
        net_cash_flows_oper_act=180.0,
    )]

    data = {"600519.SH": {
        "PershareIndex": pershare,
        "Income": income,
        "Balance": balance,
        "CashFlow": cashflow,
    }}

    records = collector.extract_periods(data, "600519.SH")
    assert len(records) == 1
    r = records[0]
    assert r["report_date"] == "20240630"
    assert r["eps"] == 10.0
    assert r["revenue"] == 1000.0
    assert r["net_profit"] == 200.0
    # roe 直接来自字段
    assert r["roe"] == 15.0
    # gross_margin 直接来自字段
    assert r["gross_margin"] == 45.0
    # roa = 200 / 5000 * 100 = 4.0
    assert r["roa"] == pytest.approx(4.0)
    # net_margin = 200 / 1000 * 100 = 20.0
    assert r["net_margin"] == pytest.approx(20.0)
    # debt_ratio = 2000 / 5000 * 100 = 40.0
    assert r["debt_ratio"] == pytest.approx(40.0)
    # current_ratio = 1500 / 800 = 1.875
    assert r["current_ratio"] == pytest.approx(1.875)
    assert r["operating_cashflow"] == 180.0
    assert r["total_assets"] == 5000.0
    assert r["total_equity"] == 3000.0


def test_extract_periods_falls_back_for_gross_margin() -> None:
    """无 sales_gross_profit 时应能用 revenue - cost 推算毛利率。"""
    collector = FinancialCollector(MagicMock(), MagicMock())
    data = {"600519.SH": {
        "PershareIndex": [_make_period_row("20240630", s_fa_eps_basic=10.0)],
        "Income": [_make_period_row("20240630", revenue=1000.0, net_profit=200.0,
                                    cost_of_goods_sold=600.0)],
        "Balance": [],
        "CashFlow": [],
    }}
    records = collector.extract_periods(data, "600519.SH")
    # gross_margin = (1000 - 600) / 1000 * 100 = 40.0
    assert records[0]["gross_margin"] == pytest.approx(40.0)


def test_extract_periods_computes_roe_when_missing() -> None:
    """无 ROE 直接字段时，应用 net_profit / total_equity * 100 推算。"""
    collector = FinancialCollector(MagicMock(), MagicMock())
    data = {"600519.SH": {
        "PershareIndex": [_make_period_row("20240630", s_fa_eps_basic=10.0)],
        "Income": [_make_period_row("20240630", revenue=1000.0,
                                    net_profit_incl_min_int_inc=300.0)],
        "Balance": [_make_period_row("20240630", tot_assets=5000.0, total_equity=2000.0)],
        "CashFlow": [],
    }}
    records = collector.extract_periods(data, "600519.SH")
    # roe = 300 / 2000 * 100 = 15.0
    assert records[0]["roe"] == pytest.approx(15.0)


def test_extract_periods_empty_stock_returns_empty() -> None:
    collector = FinancialCollector(MagicMock(), MagicMock())
    assert collector.extract_periods({}, "600519.SH") == []
    assert collector.extract_periods({"600519.SH": {}}, "600519.SH") == []


# ---------- 批量与主流程测试 ----------

def test_get_existing_stocks() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        {"stock_code": "600519.SH"},
        {"stock_code": "000001.SZ"},
    ]
    collector = FinancialCollector(MagicMock(), storage)
    assert collector.get_existing_stocks() == {"600519.SH", "000001.SZ"}


def test_process_batch_calls_source_and_storage() -> None:
    """单批处理：source 应被以正确参数调用，storage.executemany 接收行。"""
    # download callback 立即触发，get_financial_data 返回一只股票一期的数据
    source = MagicMock()

    def fake_download(stocks, tables, start_time, end_time, callback):
        callback({"data": {}})

    source.download_financial_data.side_effect = fake_download
    source.get_financial_data.return_value = {
        "600519.SH": {
            "PershareIndex": [],
            "Income": [_make_period_row("20240630", revenue=1000.0,
                                        net_profit_incl_min_int_inc=200.0)],
            "Balance": [_make_period_row("20240630", tot_assets=5000.0,
                                         total_equity=3000.0)],
            "CashFlow": [],
        },
    }
    storage = MagicMock()
    storage.executemany.return_value = 1

    collector = FinancialCollector(source, storage, batch_size=50, post_download_sleep=0)
    rows, stocks_ok = collector.process_batch(["600519.SH"])

    assert rows == 1
    assert stocks_ok == 1
    source.download_financial_data.assert_called_once()
    source.get_financial_data.assert_called_once()
    args, kwargs = storage.executemany.call_args
    sql, row_list = args
    assert sql.strip() == INSERT_SQL.strip()
    assert len(row_list) == 1
    # row 字段顺序：code, date, revenue, net_profit, eps, roe, roa,
    # gross_margin, net_margin, debt_ratio, current_ratio, ocf,
    # total_assets, total_equity, data_source
    assert row_list[0][0] == "600519.SH"
    assert row_list[0][1] == "2024-06-30"
    assert row_list[0][2] == 1000.0
    assert row_list[0][3] == 200.0
    assert row_list[0][14] == "qmt"


def test_collect_skips_existing_stocks() -> None:
    """已有数据的股票应被跳过，不进入 process_batch。"""
    source = MagicMock()
    source.list_stocks.return_value = ["600519.SH", "000001.SZ"]
    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_existing_stocks（两只都已采集过）
        [{"stock_code": "600519.SH"}, {"stock_code": "000001.SZ"}],
        # _print_summary
        [{"stock_cnt": 2, "row_cnt": 8, "min_date": "2024-06-30",
          "max_date": "2024-06-30"}],
    ]

    collector = FinancialCollector(source, storage, post_download_sleep=0)
    report = collector.collect(mode="full")

    # 全部跳过 → 不应进入 process_batch
    assert report.total_stocks == 0
    assert report.batches == 0
    source.download_financial_data.assert_not_called()
    source.get_financial_data.assert_not_called()


def test_collect_full_with_batches() -> None:
    """全量模式下，按 batch_size 分批，且每批都应被处理。"""
    source = MagicMock()
    codes = [f"60000{i}.SH" for i in range(7)]
    source.list_stocks.return_value = codes
    source.get_financial_data.return_value = {
        code: {
            "PershareIndex": [],
            "Income": [_make_period_row("20240630", revenue=1000.0,
                                        net_profit=200.0)],
            "Balance": [_make_period_row("20240630", tot_assets=5000.0)],
            "CashFlow": [],
        } for code in codes
    }

    def fake_download(stocks, tables, start_time, end_time, callback):
        callback({"data": {}})

    source.download_financial_data.side_effect = fake_download

    storage = MagicMock()
    storage.fetch_all.side_effect = [
        [],  # get_existing_stocks
        [{"stock_cnt": 7, "row_cnt": 7, "min_date": "2024-06-30",
          "max_date": "2024-06-30"}],  # _print_summary
    ]
    storage.executemany.return_value = 1

    collector = FinancialCollector(source, storage, batch_size=3, post_download_sleep=0)
    report = collector.collect(mode="full")

    # 7 只股票，batch_size=3 → 3 批（3+3+1）
    assert report.total_stocks == 7
    assert report.batches == 3
    assert source.download_financial_data.call_count == 3


def test_insert_sql_upsert_columns() -> None:
    """ON DUPLICATE KEY UPDATE 必须覆盖所有写入字段（除 data_source）。"""
    assert "ON DUPLICATE KEY UPDATE" in INSERT_SQL
    for col in ("revenue", "net_profit", "eps", "roe", "roa",
                "gross_margin", "net_margin", "debt_ratio", "current_ratio",
                "operating_cashflow", "total_assets", "total_equity"):
        assert f"{col}=VALUES({col})" in INSERT_SQL


def test_financial_report_defaults() -> None:
    r = FinancialReport()
    assert r.total_stocks == 0
    assert r.success == 0
    assert r.rows == 0
    assert r.batches == 0
    assert r.elapsed == 0.0