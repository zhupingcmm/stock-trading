"""``StockMetaCollector`` 单元测试。

``XtQuantDataSource`` 与 ``MysqlStorage`` 都通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from data_collection.collectors.stock_meta import (
    INSERT_SQL,
    StockMetaCollector,
    StockMetaReport,
)


def _make_collector() -> tuple[StockMetaCollector, MagicMock, MagicMock]:
    source = MagicMock()
    storage = MagicMock()
    collector = StockMetaCollector(source, storage, workers=4)
    return collector, source, storage


# ---------- INSERT_SQL 结构 ----------

def test_insert_sql_has_unique_key_upsert() -> None:
    """ON DUPLICATE KEY UPDATE 必须保留以实现 UPSERT。"""
    assert "ON DUPLICATE KEY UPDATE" in INSERT_SQL
    assert "VALUES(stock_name)" in INSERT_SQL
    assert "VALUES(industry)" in INSERT_SQL
    assert "VALUES(data_source)" in INSERT_SQL


# ---------- StockMetaReport ----------

def test_stock_meta_report_defaults() -> None:
    """StockMetaReport 应有合理的默认值，便于 partial 结果使用。"""
    r = StockMetaReport()
    assert r.total == 0
    assert r.success == 0
    assert r.failed == []
    assert r.n_with_industry == 0
    assert r.elapsed == 0.0


# ---------- get_listed_stocks ----------

def test_listed_stocks_uses_xtquant() -> None:
    collector, source, _storage = _make_collector()
    source.list_stocks.return_value = ["600519.SH", "000001.SZ"]
    codes = collector.get_listed_stocks("沪深A股")
    assert codes == ["600519.SH", "000001.SZ"]
    source.list_stocks.assert_called_once_with("沪深A股")


# ---------- fetch_industry_map ----------

def test_fetch_industry_map_returns_xtquant_dict() -> None:
    collector, source, _storage = _make_collector()
    mapping = {"600519.SH": "SW1食品饮料", "000001.SZ": "SW1银行"}
    source.get_stock_industry_map.return_value = mapping
    assert collector.fetch_industry_map() is mapping


# ---------- fetch_meta ----------

def test_fetch_meta_composes_name_and_industry() -> None:
    collector, source, _storage = _make_collector()
    source.get_stock_name.return_value = "贵州茅台"
    industry_map = {"600519.SH": "SW1食品饮料"}
    meta = collector.fetch_meta("600519.SH", industry_map)
    assert meta == {
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
        "industry": "SW1食品饮料",
    }


def test_fetch_meta_handles_missing_industry() -> None:
    """industry_map 缺该 code → industry 留空字符串。"""
    collector, source, _storage = _make_collector()
    source.get_stock_name.return_value = "未知股"
    meta = collector.fetch_meta("999999.SH", {})
    assert meta["industry"] == ""
    assert meta["stock_name"] == "未知股"


def test_fetch_meta_handles_empty_name() -> None:
    """stock_name 失败 / 空 → 仍返回空字符串。"""
    collector, source, _storage = _make_collector()
    source.get_stock_name.return_value = ""
    meta = collector.fetch_meta("600519.SH", {"600519.SH": "SW1食品饮料"})
    assert meta["stock_name"] == ""
    assert meta["industry"] == "SW1食品饮料"


# ---------- save_one ----------

def test_save_one_executes_upsert_sql() -> None:
    collector, _source, storage = _make_collector()
    storage.execute.return_value = 1
    rc = collector.save_one("600519.SH", "贵州茅台", "SW1食品饮料")
    assert rc == 1
    storage.execute.assert_called_once()
    sql, params = storage.execute.call_args.args
    assert sql.strip() == INSERT_SQL.strip()
    assert params == ("600519.SH", "贵州茅台", "SW1食品饮料", "qmt")


# ---------- collect 流程 ----------

def test_collect_test_mode_runs_one_stock() -> None:
    """test 模式只采 1 只股票。"""
    collector, source, storage = _make_collector()
    source.list_stocks.return_value = []
    source.get_stock_industry_map.return_value = {"600519.SH": "SW1食品饮料"}
    source.get_stock_name.return_value = "贵州茅台"
    storage.execute.return_value = 1
    storage.fetch_all.return_value = []

    report = collector.collect(mode="test", test_stock="600519.SH")

    assert report.total == 1
    assert report.success == 1
    assert report.failed == []
    # 一次写入
    assert storage.execute.call_count == 1


def test_collect_full_flow_writes_all() -> None:
    """全量模式：N 只股票全写入（n < SERIAL_THRESHOLD → 串行）。"""
    collector, source, storage = _make_collector()
    source.list_stocks.return_value = ["A.SH", "B.SZ", "C.SH"]
    source.get_stock_industry_map.return_value = {
        "A.SH": "SW1银行",
        "B.SZ": "SW1房地产",
        "C.SH": "SW1食品饮料",
    }
    source.get_stock_name.side_effect = ["A 股", "B 股", "C 股"]
    storage.execute.return_value = 1
    storage.fetch_all.return_value = []

    report = collector.collect(mode="full")

    assert report.total == 3
    assert report.success == 3
    assert report.failed == []
    assert storage.execute.call_count == 3
    # 每个 call 应包含 industry（来自 industry_map）
    params_list = [call.args[1] for call in storage.execute.call_args_list]
    assert ("A.SH", "A 股", "SW1银行", "qmt") in params_list
    assert ("B.SZ", "B 股", "SW1房地产", "qmt") in params_list


def test_collect_records_failed_stocks() -> None:
    """单只拉取失败 → 计入 failed，整体流程不中断。"""
    collector, source, storage = _make_collector()
    source.list_stocks.return_value = ["A.SH", "B.SZ"]
    source.get_stock_industry_map.return_value = {}
    # A 成功，B 失败
    source.get_stock_name.side_effect = ["A 股", Exception("qmt 断线")]
    storage.execute.return_value = 1
    storage.fetch_all.return_value = []

    report = collector.collect(mode="full")

    assert report.total == 2
    assert report.success == 1
    assert report.failed == ["B.SZ"]


def test_collect_records_explicit_stocks() -> None:
    """显式传入 stocks 列表 → 覆盖 mode 默认。"""
    collector, source, storage = _make_collector()
    source.get_stock_industry_map.return_value = {}
    source.get_stock_name.side_effect = ["X 股", "Y 股"]
    storage.execute.return_value = 1
    storage.fetch_all.return_value = []

    report = collector.collect(mode="test", stocks=["X.SH", "Y.SZ"])

    assert report.total == 2
    assert report.success == 2
    # mode=test 不应自动追加默认 test_stock
    assert len(report.failed) == 0


def test_collect_progress_bar_calls_when_done() -> None:
    """股票数 > SERIAL_THRESHOLD 时走并行路径，所有股票仍被处理。"""
    collector, source, storage = _make_collector()
    codes = [f"{i:06d}.SH" for i in range(1, 7)]  # 6 只，超过 SERIAL_THRESHOLD=5
    source.list_stocks.return_value = codes
    source.get_stock_industry_map.return_value = {c: "SW1银行" for c in codes}
    source.get_stock_name.side_effect = [f"{c} 股" for c in codes]
    storage.execute.return_value = 1
    storage.fetch_all.return_value = []

    report = collector.collect(mode="full", sector="沪深A股")

    assert report.total == 6
    assert report.success == 6
    assert len(report.failed) == 0
    assert storage.execute.call_count == 6


def test_constructor_signature_does_not_take_workers_default() -> None:
    """workers 默认为 ``STOCK_META_NUM_WORKERS``。"""
    sig = inspect.signature(StockMetaCollector.__init__)
    params = sig.parameters
    assert "source" in params
    assert "storage" in params
    assert "workers" in params
    # workers 应有默认值（None 或具体 int）
    assert params["workers"].default is not inspect.Parameter.empty


def test_collect_empty_stocks_returns_early() -> None:
    """空股票列表 → 提前返回，不写库、不调 xtquant。"""
    collector, source, storage = _make_collector()
    report = collector.collect(mode="full", stocks=[])
    assert report.total == 0
    assert report.success == 0
    source.get_stock_name.assert_not_called()
    storage.execute.assert_not_called()
