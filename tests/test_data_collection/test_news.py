"""``NewsCollector`` 单元测试。

AkShare 与 MySQL 都通过 ``unittest.mock`` 替换。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pymysql
import pytest

from data_collection.collectors.news import (
    INSERT_NEWS_SQL,
    NewsCollector,
    NewsReport,
)


def _mock_news_df() -> pd.DataFrame:
    """模拟 ak.stock_news_em() 返回格式。"""
    return pd.DataFrame({
        "新闻标题": ["公司业绩预增", "涨停！", "日常公告"],
        "新闻内容": ["内容1", "内容2", "内容3"],
        "新闻链接": ["http://a", "http://b", "http://c"],
        "发布时间": ["2024-01-15 10:00:00", "2024-01-15 11:00:00", "2024-01-15 12:00:00"],
        "文章来源": ["东方财富", "新浪财经", ""],
    })


# ---------- 辅助查询 ----------

def test_get_all_stocks() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        {"stock_code": "600519.SH"},
        {"stock_code": "000001.SZ"},
    ]
    collector = NewsCollector(MagicMock(), storage)
    assert collector.get_all_stocks() == ["600519.SH", "000001.SZ"]


def test_get_today_collected() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        {"stock_code": "600519.SH"},
        {"stock_code": "000001.SZ"},
    ]
    collector = NewsCollector(MagicMock(), storage)
    assert collector.get_today_collected() == {"600519.SH", "000001.SZ"}


def test_load_existing_titles() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = [
        {"title": "A"}, {"title": "B"}, {"title": "A"},  # 重复标题
    ]
    collector = NewsCollector(MagicMock(), storage)
    titles = collector.load_existing_titles()
    assert titles == {"A", "B"}  # set 去重


# ---------- 单只股票 ----------

def test_fetch_news_parses_correctly() -> None:
    source = MagicMock()
    source.get_stock_news.return_value = _mock_news_df()
    collector = NewsCollector(source, MagicMock())

    items = collector.fetch_news("600519.SH")
    assert len(items) == 3

    # "公司业绩预增" → sentiment=positive（命中 POSITIVE 列表）
    assert items[0]["sentiment"] == "positive"
    # "涨停！" → sentiment=positive, is_important=True（涨停在 POSITIVE 列表，且命中 IMPORTANT 列表中的"涨停"）

    # 实际上"涨停"不在 IMPORTANT_WORDS 中，让我重新确认
    # IMPORTANT_WORDS: 资产重组, 业绩预增, 业绩预减, 高送转, 股权激励, 定向增发, 股东减持, 股东增持, 重大合同, 中标, 收购, 并购, 停牌, 复牌, 退市, 回购
    # "涨停" 不在 IMPORTANT，所以 is_important=False
    assert items[0]["is_important"] is True  # "业绩预增" 在 IMPORTANT
    assert items[1]["sentiment"] == "positive"
    assert items[1]["is_important"] is False  # "涨停" 不在 IMPORTANT
    assert items[2]["sentiment"] == "neutral"

    # 默认 source
    assert items[2]["source"] == "eastmoney"


def test_fetch_news_truncates_content() -> None:
    source = MagicMock()
    source.get_stock_news.return_value = pd.DataFrame({
        "新闻标题": ["title"],
        "新闻内容": ["x" * 5000],  # 超过 2000
        "新闻链接": [""],
        "发布时间": [""],
        "文章来源": [""],
    })
    collector = NewsCollector(source, MagicMock())
    items = collector.fetch_news("600519.SH")
    assert len(items[0]["content"]) == 2000


def test_fetch_news_strips_code_to_digits() -> None:
    """stock_news_em 需要纯数字代码。"""
    source = MagicMock()
    source.get_stock_news.return_value = pd.DataFrame()
    collector = NewsCollector(source, MagicMock())
    collector.fetch_news("600519.SH")
    source.get_stock_news.assert_called_once_with("600519")


def test_fetch_news_handles_empty() -> None:
    source = MagicMock()
    source.get_stock_news.return_value = pd.DataFrame()
    collector = NewsCollector(source, MagicMock())
    assert collector.fetch_news("600519.SH") == []


def test_save_news_dedup_in_memory() -> None:
    """已在内存集合中的标题应跳过。"""
    source = MagicMock()
    storage = MagicMock()
    storage.execute.return_value = 1

    collector = NewsCollector(source, storage)
    collector._existing_titles.add("duplicate title")

    news = [{"title": "duplicate title", "content": "", "link": "",
             "published_at": None, "sentiment": "neutral", "is_important": False,
             "source": "eastmoney", "news_type": "news"}]
    saved = collector.save_news("600519.SH", news)

    assert saved == 0
    storage.execute.assert_not_called()


def test_save_news_inserts_new_titles() -> None:
    storage = MagicMock()
    storage.execute.return_value = 1
    collector = NewsCollector(MagicMock(), storage)

    news = [
        {"title": "A", "content": "content_A", "link": "url_A",
         "published_at": "2024-01-15 10:00:00", "sentiment": "positive",
         "is_important": True, "source": "eastmoney", "news_type": "news"},
        {"title": "B", "content": "content_B", "link": "url_B",
         "published_at": "2024-01-15 11:00:00", "sentiment": "neutral",
         "is_important": False, "source": "eastmoney", "news_type": "news"},
    ]
    saved = collector.save_news("600519.SH", news)
    assert saved == 2
    assert storage.execute.call_count == 2
    sql, params = storage.execute.call_args_list[0].args
    assert sql.strip() == INSERT_NEWS_SQL.strip()
    # 第一条：sentiment=positive, is_important=1
    assert params[6] == "positive"
    assert params[7] == 1


def test_save_news_catches_integrity_error() -> None:
    """race condition 下其他线程已写入同标题 → IntegrityError 应静默跳过。"""
    storage = MagicMock()
    storage.execute.side_effect = pymysql.err.IntegrityError(1062, "Duplicate")
    collector = NewsCollector(MagicMock(), storage)

    news = [{"title": "A", "content": "", "link": "",
             "published_at": None, "sentiment": "neutral", "is_important": False,
             "source": "eastmoney", "news_type": "news"}]
    saved = collector.save_news("600519.SH", news)
    assert saved == 0
    # 标题仍然加入集合（防止后续重试）
    assert "A" in collector._existing_titles


# ---------- 主流程 ----------

def test_collect_skips_today_collected() -> None:
    """当日已采集过的股票应跳过。"""
    source = MagicMock()
    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_all_stocks
        [{"stock_code": "600519.SH"}, {"stock_code": "000001.SZ"}],
        # get_today_collected
        [{"stock_code": "600519.SH"}],
        # load_existing_titles
        [],
        # _print_summary
        [{"cnt": 0, "stock_cnt": 0}],
    ]
    source.get_stock_news.return_value = pd.DataFrame()  # 空新闻

    collector = NewsCollector(source, storage)
    report = collector.collect()

    assert report.total == 1  # 只剩 000001.SZ
    assert report.skipped_today == 1
    # 600519.SH 不应该被调用 stock_news_em
    source.get_stock_news.assert_called_once_with("000001")


def test_collect_skips_all_when_today_full() -> None:
    """全部股票当日已采集 → 直接退出。"""
    source = MagicMock()
    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_all_stocks
        [{"stock_code": "600519.SH"}, {"stock_code": "000001.SZ"}],
        # get_today_collected
        [{"stock_code": "600519.SH"}, {"stock_code": "000001.SZ"}],
        # _print_summary
        [{"cnt": 0, "stock_cnt": 0}],
    ]

    collector = NewsCollector(source, storage)
    report = collector.collect()

    assert report.total == 0
    source.get_stock_news.assert_not_called()


def test_collect_full_flow() -> None:
    """端到端：并行采集、内存去重、写入。"""
    source = MagicMock()
    source.get_stock_news.return_value = _mock_news_df()

    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_all_stocks
        [{"stock_code": "600519.SH"}, {"stock_code": "000001.SZ"}],
        # get_today_collected（空，无跳过）
        [],
        # load_existing_titles
        [{"title": "日常公告"}],  # 预存一个标题去重
        # _print_summary
        [{"cnt": 5, "stock_cnt": 2}],
    ]
    storage.execute.return_value = 1

    collector = NewsCollector(source, storage, workers=2)
    report = collector.collect()

    assert report.total == 2
    assert report.processed == 2
    # 两只股票都拿到 3 条新闻
    assert report.fetched == 6
    # 全局标题去重：先跑完的那个写入 2 条，后跑的那个看到的都是已存在标题，saved=0
    assert report.saved == 2
    assert "日常公告" in collector._existing_titles
    # 两份新闻的标题都进了内存集合
    for title in ("公司业绩预增", "涨停！", "日常公告"):
        assert title in collector._existing_titles


def test_collect_with_explicit_stocks() -> None:
    """传入 stocks 时跳过 get_all_stocks。"""
    source = MagicMock()
    source.get_stock_news.return_value = pd.DataFrame()

    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # get_today_collected
        [],
        # load_existing_titles
        [],
        # _print_summary
        [{"cnt": 0, "stock_cnt": 0}],
    ]

    collector = NewsCollector(source, storage)
    report = collector.collect(stocks=["600519.SH"])

    assert report.total == 1
    # 没调用 get_all_stocks 的 SQL（"SELECT DISTINCT stock_code FROM trade_stock_daily"）
    fetch_calls = storage.fetch_all.call_args_list
    sqls = [c.args[0] for c in fetch_calls]
    assert not any("trade_stock_daily" in s for s in sqls)


# ---------- INSERT_SQL 与默认值 ----------

def test_insert_news_sql_columns() -> None:
    """INSERT 必须包含表 trade_stock_news 的所有字段。"""
    cols = ("stock_code", "news_type", "title", "content", "source",
            "source_url", "sentiment", "is_important", "published_at")
    for col in cols:
        assert col in INSERT_NEWS_SQL


def test_news_report_defaults() -> None:
    r = NewsReport()
    assert r.total == 0
    assert r.processed == 0
    assert r.fetched == 0
    assert r.saved == 0
    assert r.skipped_today == 0
    assert r.elapsed == 0.0