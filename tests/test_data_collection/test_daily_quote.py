"""``DailyQuoteCollector`` 的单元测试。

``xtquant`` 与 MySQL 都通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_collection.collectors.daily_quote import (
    INSERT_SQL,
    CollectReport,
    DailyQuoteCollector,
)


def _make_df(rows: list[tuple[str, dict]]) -> pd.DataFrame:
    """构造 xtquant 风格的 DataFrame：index 为 'YYYYMMDD' 字符串。"""
    idx = [r[0] for r in rows]
    data: dict[str, list[float]] = {}
    for _, payload in rows:
        for k, v in payload.items():
            data.setdefault(k, []).append(v)
    return pd.DataFrame(data, index=idx)


def test_get_existing_latest_dates() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        {"stock_code": "600519.SH", "max_date": date(2026, 1, 15)},
        {"stock_code": "000001.SZ", "max_date": None},
    ]
    collector = DailyQuoteCollector(MagicMock(), storage)
    assert collector.get_existing_latest_dates() == {"600519.SH": "20260115"}
    storage.fetch_all.assert_called_once()


def test_download_and_save_turnover() -> None:
    source = MagicMock()
    source.get_market_data.return_value = _make_df([
        ("20260115", {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                      "volume": 1000, "amount": 100500.0}),
        ("20260116", {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5,
                      "volume": 0, "amount": 0.0}),  # 边界：volume=0
    ])
    source.get_float_shares.return_value = 100_000_000
    storage = MagicMock()
    storage.executemany.return_value = 2

    collector = DailyQuoteCollector(source, storage)
    code, count = collector.download_and_save("600519.SH", "20260101")

    assert code == "600519.SH"
    assert count == 2
    storage.executemany.assert_called_once()
    sql, rows = storage.executemany.call_args.args
    assert sql.strip() == INSERT_SQL.strip()
    # 第一行换手率：1000 手 * 100 股 / 1e8 股 * 100 = 0.1%
    assert rows[0][8] == pytest.approx(0.1, rel=1e-4)
    # 第二行 volume=0，turnover 应为 None
    assert rows[1][8] is None


def test_collect_skips_up_to_date_stocks() -> None:
    """DB 中已有今日数据的股票应跳过下载。"""
    source = MagicMock()
    source.list_stocks.return_value = ["600519.SH", "000001.SZ"]
    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_existing_latest_dates（两只都已是最今日）
        [{"stock_code": "600519.SH", "max_date": date.today()},
         {"stock_code": "000001.SZ", "max_date": date.today()}],
        # _print_summary
        [{"stock_cnt": 2, "row_cnt": 2, "min_date": date.today(),
          "max_date": date.today()}],
    ]

    collector = DailyQuoteCollector(source, storage)
    report = collector.collect(mode="full")

    assert report.total == 0
    assert report.success == 0
    source.download_history.assert_not_called()


def test_insert_sql_has_unique_key_upsert() -> None:
    """ON DUPLICATE KEY UPDATE 必须保留以实现增量 upsert。"""
    assert "ON DUPLICATE KEY UPDATE" in INSERT_SQL
    for col in ("open_price", "high_price", "low_price", "close_price",
                "volume", "amount", "turnover_rate"):
        assert f"{col}=VALUES({col})" in INSERT_SQL


def test_collect_full_processes_all_stocks() -> None:
    """股票数超过阈值时所有股票均应被处理。"""
    source = MagicMock()
    codes = [f"60000{i}.SH" for i in range(6)]
    source.list_stocks.return_value = codes
    source.get_market_data.return_value = _make_df([
        ("20260115", {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
                      "volume": 100, "amount": 150.0}),
    ])
    source.get_float_shares.return_value = 1_000_000
    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_existing_latest_dates -> 空
        [],
        # _print_summary
        [{"stock_cnt": 6, "row_cnt": 6, "min_date": date.today(),
          "max_date": date.today()}],
    ]
    storage.executemany.return_value = 1

    collector = DailyQuoteCollector(source, storage, workers=4)
    report = collector.collect(mode="full")

    assert report.total == 6
    assert report.success == 6
    assert source.download_history.call_count == 6
    assert storage.executemany.call_count == 6


def test_collect_report_default_values() -> None:
    """CollectReport 应有合理的默认值，便于 partial 结果使用。"""
    r = CollectReport()
    assert r.total == 0
    assert r.success == 0
    assert r.rows == 0
    assert r.failed == []
    assert r.elapsed == 0.0