"""``ReportCollector`` 单元测试。

AkShare 与 MySQL 都通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_collection.collectors.report import (
    INSERT_FORECAST_SQL,
    INSERT_RECOMMEND_SQL,
    ReportCollector,
    ReportReport,
    _RECOMMEND_COLUMNS,
)


def _mock_recommend_df() -> pd.DataFrame:
    """模拟 ak.stock_institute_recommend_detail() 返回的 8 列 DataFrame。"""
    df = pd.DataFrame({
        "raw0": ["000001", "000001", "000002"],
        "raw1": ["平安银行", "平安银行", "万科A"],
        "raw2": [12.5, 12.5, 20.0],
        "raw3": ["买入", "买入", "增持"],
        "raw4": ["招商证券", "广发证券", "国泰君安"],
        "raw5": ["分析师A", "分析师B", "分析师C"],
        "raw6": ["银行", "银行", "地产"],
        "raw7": ["2024-01-15", "2024-02-20", "2024-03-10"],
    })
    return df


# ---------- 辅助查询 ----------

def test_get_all_stocks() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        {"stock_code": "600519.SH"}, {"stock_code": "000001.SZ"},
    ]
    collector = ReportCollector(MagicMock(), storage)
    assert collector.get_all_stocks() == ["600519.SH", "000001.SZ"]
    sql = storage.fetch_all.call_args.args[0]
    assert "trade_stock_daily" in sql


def test_get_recently_collected() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        {"stock_code": "600519.SH"},
        {"stock_code": "000001.SZ"},
    ]
    collector = ReportCollector(MagicMock(), storage, recent_days=7)
    assert collector.get_recently_collected() == {"600519.SH", "000001.SZ"}
    # SQL 应带 INTERVAL ? DAY 参数
    call_args = storage.fetch_all.call_args
    assert "INTERVAL %" in call_args.args[0]
    assert call_args.args[1] == (7,)


def test_get_existing_opinions_takes_latest_per_broker() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        # 按 ORDER BY report_date DESC，相同 broker 仅保留第一条
        {"broker": "招商证券", "rating": "买入", "target_price": 12.5},
        {"broker": "招商证券", "rating": "中性", "target_price": 10.0},  # 应被忽略
        {"broker": "国泰君安", "rating": "增持", "target_price": 20.0},
    ]
    collector = ReportCollector(MagicMock(), storage)
    opinions = collector.get_existing_opinions("000001.SZ")
    assert opinions["招商证券"]["rating"] == "买入"
    assert opinions["招商证券"]["target_price"] == 12.5
    assert "国泰君安" in opinions


# ---------- 单只股票：fetch + dedup ----------

def test_fetch_institute_recommend_parses_columns() -> None:
    source = MagicMock()
    source.get_institute_recommend.return_value = _mock_recommend_df()
    collector = ReportCollector(source, MagicMock())
    df = collector.fetch_institute_recommend("000001.SZ")
    assert len(df) == 3
    assert list(df.columns[:8]) == _RECOMMEND_COLUMNS
    assert df["target_price"].iloc[0] == 12.5
    # 默认 stock_code 列
    assert (df["stock_code"] == "000001.SZ").all()
    # code_num 应被剥离（不带后缀）
    source.get_institute_recommend.assert_called_once_with("000001")


def test_fetch_institute_recommend_empty_returns_empty() -> None:
    source = MagicMock()
    source.get_institute_recommend.return_value = pd.DataFrame()
    collector = ReportCollector(source, MagicMock())
    assert collector.fetch_institute_recommend("000001.SZ").empty


def test_fetch_institute_recommend_handles_exception() -> None:
    source = MagicMock()
    source.get_institute_recommend.side_effect = RuntimeError("network")
    collector = ReportCollector(source, MagicMock())
    assert collector.fetch_institute_recommend("000001.SZ").empty


def test_deduplicate_recommend_keeps_only_view_changes() -> None:
    """同一券商仅在 rating/tp 变化时才保留。"""
    df = pd.DataFrame({
        "broker": ["A", "A", "A", "B", "B"],
        "rating": ["买入", "买入", "中性", "增持", "增持"],
        "target_price": [10.0, 10.0, 12.0, 20.0, 20.0],
        "report_date": pd.to_datetime([
            "2024-01-01", "2024-01-15", "2024-02-01", "2024-01-05", "2024-01-10",
        ]),
    })
    collector = ReportCollector(MagicMock(), MagicMock())
    out = collector.deduplicate_recommend(df)
    # A: 第1条保留(首次)，第2条跳过(相同)，第3条保留(rating变化) → 2条
    # B: 第1条保留(首次)，第2条跳过(相同) → 1条
    assert len(out) == 3


def test_deduplicate_recommend_handles_empty() -> None:
    collector = ReportCollector(MagicMock(), MagicMock())
    assert collector.deduplicate_recommend(pd.DataFrame()).empty
    assert collector.deduplicate_recommend(None).empty  # type: ignore[arg-type]


# ---------- save_recommend ----------

def test_save_recommend_skips_unchanged_opinions() -> None:
    storage = MagicMock()
    storage.execute.return_value = 1
    collector = ReportCollector(MagicMock(), storage)

    existing = {"A": {"rating": "买入", "target_price": 10.0}}
    df = pd.DataFrame({
        "broker": ["A"],
        "rating": ["买入"],
        "target_price": [10.0],
        "report_date": pd.to_datetime(["2024-02-01"]),
    })
    saved = collector.save_recommend("000001.SZ", df, existing)
    assert saved == 0
    storage.execute.assert_not_called()


def test_save_recommend_inserts_changed_opinion() -> None:
    storage = MagicMock()
    storage.execute.return_value = 1
    collector = ReportCollector(MagicMock(), storage)

    existing = {"A": {"rating": "中性", "target_price": 9.0}}
    df = pd.DataFrame({
        "broker": ["A"],
        "rating": ["买入"],
        "target_price": [10.0],
        "report_date": pd.to_datetime(["2024-02-01"]),
    })
    saved = collector.save_recommend("000001.SZ", df, existing)
    assert saved == 1
    assert storage.execute.call_count == 1
    sql, params = storage.execute.call_args.args
    assert sql.strip() == INSERT_RECOMMEND_SQL.strip()
    assert params[0] == "000001.SZ"
    assert params[1] == "A"
    assert params[3] == "买入"
    assert params[4] == 10.0
    assert params[8] == "eastmoney"


def test_save_recommend_handles_nan_target_price() -> None:
    storage = MagicMock()
    storage.execute.return_value = 1
    collector = ReportCollector(MagicMock(), storage)

    df = pd.DataFrame({
        "broker": ["A"],
        "rating": ["买入"],
        "target_price": [float("nan")],
        "report_date": pd.to_datetime(["2024-02-01"]),
    })
    saved = collector.save_recommend("000001.SZ", df)
    assert saved == 1
    assert storage.execute.call_args.args[1][4] is None


# ---------- 一致预期 ----------

def _mock_eps_forecast_df() -> pd.DataFrame:
    return pd.DataFrame({
        "year": ["2024", "2025"],
        "analyst_count": [12, 10],
        "min_val": [3.5, 4.0],
        "mean_val": [4.2, 4.9],
        "max_val": [5.0, 5.6],
        "industry_avg": [3.8, 4.1],
    })


def _mock_profit_forecast_df() -> pd.DataFrame:
    return pd.DataFrame({
        "year": ["2024"],
        "analyst_count": [12],
        "min_val": [100.0],
        "mean_val": [150.0],
        "max_val": [200.0],
        "industry_avg": [120.0],
    })


def test_fetch_profit_forecast_calls_two_indicators() -> None:
    source = MagicMock()
    source.get_profit_forecast_ths.side_effect = [
        _mock_eps_forecast_df(),
        _mock_profit_forecast_df(),
    ]
    collector = ReportCollector(source, MagicMock())
    result = collector.fetch_profit_forecast("000001.SZ")
    assert "预测年报每股收益" in result
    assert "预测年报净利润" in result
    assert source.get_profit_forecast_ths.call_count == 2


def test_save_forecast_writes_consensus_row() -> None:
    storage = MagicMock()
    storage.execute.return_value = 1
    collector = ReportCollector(MagicMock(), storage)

    forecasts = {
        "预测年报每股收益": _mock_eps_forecast_df(),
        "预测年报净利润": _mock_profit_forecast_df(),
    }
    saved = collector.save_forecast("000001.SZ", forecasts)
    assert saved == 1
    sql, params = storage.execute.call_args.args
    assert sql.strip() == INSERT_FORECAST_SQL.strip()
    assert params[1] == "一致预期(12家)"
    assert params[5] == pytest.approx(4.2)
    assert params[6] == pytest.approx(4.9)
    assert params[7] == pytest.approx(150.0)
    assert params[8] == "ths_consensus"


def test_save_forecast_returns_zero_without_eps() -> None:
    storage = MagicMock()
    collector = ReportCollector(MagicMock(), storage)
    saved = collector.save_forecast("000001.SZ", {})
    assert saved == 0
    storage.execute.assert_not_called()


# ---------- 主流程 ----------

def test_collect_test_mode_runs_one_stock() -> None:
    """mode='test' 时不调用 get_all_stocks/get_recently_collected。"""
    source = MagicMock()
    storage = MagicMock()
    # fetch_institute_recommend + fetch_profit_forecast + save_* 都不再发请求
    source.get_institute_recommend.return_value = pd.DataFrame()
    source.get_profit_forecast_ths.side_effect = [pd.DataFrame(), pd.DataFrame()]

    collector = ReportCollector(source, storage)
    report = collector.collect(mode="test", test_stock="600519.SH")
    assert report.total == 1
    assert report.processed == 1
    assert report.skipped_recent == 0
    # 不应触发 trade_stock_daily / trade_report_consensus 的查询
    sqls = [c.args[0] for c in storage.fetch_all.call_args_list]
    assert not any("trade_stock_daily" in s for s in sqls)


def test_collect_full_skips_recently_collected() -> None:
    source = MagicMock()
    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_all_stocks
        [{"stock_code": "600519.SH"}, {"stock_code": "000001.SZ"}],
        # get_recently_collected
        [{"stock_code": "600519.SH"}],
        # get_existing_opinions × 1（仅 000001 待采集）
        [],
        # 摘要
        [],
    ]
    source.get_institute_recommend.return_value = pd.DataFrame()
    source.get_profit_forecast_ths.side_effect = [pd.DataFrame(), pd.DataFrame()]

    collector = ReportCollector(source, storage)
    report = collector.collect(mode="full")
    assert report.total == 1
    assert report.skipped_recent == 1
    # 600519.SH 被跳过，只剩 000001.SZ 被处理
    assert report.processed == 1


def test_collect_no_pending_returns_immediately() -> None:
    source = MagicMock()
    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_all_stocks
        [{"stock_code": "600519.SH"}],
        # get_recently_collected（已采集）
        [{"stock_code": "600519.SH"}],
        # 摘要
        [],
    ]
    collector = ReportCollector(source, storage)
    report = collector.collect(mode="full")
    assert report.total == 0
    source.get_institute_recommend.assert_not_called()


def test_collect_full_flow_saves_data() -> None:
    """端到端：拉评级 + 一致预期，写入数据库。"""
    source = MagicMock()
    source.get_institute_recommend.return_value = _mock_recommend_df()
    # 2 只股票 × 2 个 indicator = 4 次调用
    source.get_profit_forecast_ths.side_effect = [
        _mock_eps_forecast_df(),
        _mock_profit_forecast_df(),
        _mock_eps_forecast_df(),
        _mock_profit_forecast_df(),
    ]

    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_all_stocks
        [{"stock_code": "000001.SZ"}, {"stock_code": "000002.SZ"}],
        # get_recently_collected
        [],
        # get_existing_opinions × 2
        [], [],
        # 摘要
        [],
    ]
    storage.execute.return_value = 1

    collector = ReportCollector(source, storage, workers=2)
    report = collector.collect(mode="full")
    assert report.total == 2
    assert report.processed == 2
    # 3 条评级 + 2 条一致预期（每只股票 1 行）
    assert report.recommend_saved == 6
    assert report.forecast_saved == 2
    # execute 被调用 8 次（6 评级 + 2 预期）
    assert storage.execute.call_count == 8


# ---------- ReportReport 默认值 ----------

def test_report_report_defaults() -> None:
    r = ReportReport()
    assert r.total == 0
    assert r.processed == 0
    assert r.recommend_saved == 0
    assert r.forecast_saved == 0
    assert r.skipped_recent == 0
    assert r.elapsed == 0.0