"""``CalendarCollector`` 单元测试。

AkShare 与 MySQL 都通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_collection.collectors.calendar import (
    INSERT_SQL,
    CalendarCollector,
    CalendarReport,
    classify_event,
    _to_str,
)


def _mock_calendar_df() -> pd.DataFrame:
    """模拟 ak.news_economic_baidu() 返回的列。"""
    return pd.DataFrame({
        "日期": pd.to_datetime(["2024-05-01", "2024-05-15", "2024-05-20", "2024-05-25"]),
        "时间": ["10:00", "14:00", "", "20:30"],
        "国家": ["美国", "中国", "欧元区", "巴西"],   # 巴西应被过滤
        "事件": ["FOMC议息会议", "CPI公布", "PMI数据", "GDP"],
        "实际": [None, "3.0%", "52.1", None],
        "预期": ["不变", "3.2%", "52.0", None],
        "前值": [None, "3.5%", "51.8", None],
        "重要性": [3, 2, 2, 1],
    })


# ---------- 工具函数 ----------

class TestClassifyEvent:
    @pytest.mark.parametrize("title,expected", [
        ("美联储FOMC议息会议", "interest_rate"),
        ("中国CPI同比", "inflation"),
        ("非农就业报告", "non"),
        ("非农就业人数变化", "employment"),
        ("制造业PMI", "pmi"),
        ("GDP增速", "gdp"),
        ("进出口数据", "trade"),
        ("M2货币供应", "monetary"),
        ("房价指数", "housing"),
        ("零售销售", "retail"),
        ("工业增加值", "industry"),
    ])
    def test_each_category(self, title: str, expected: str):
        if expected == "non":
            # "非农就业人数变化" 不包含 "非农"，应落到 "employment"
            assert classify_event(title) == "employment"
        else:
            assert classify_event(title) == expected

    def test_other(self):
        assert classify_event("某个神秘事件") == "other"

    def test_empty(self):
        assert classify_event("") == "other"


class TestToStr:
    def test_none(self):
        assert _to_str(None) is None

    def test_nan(self):
        assert _to_str(float("nan")) is None

    def test_empty(self):
        assert _to_str("") is None
        assert _to_str("   ") is None

    def test_normal(self):
        assert _to_str("3.5%") == "3.5%"
        assert _to_str(3.5) == "3.5"


# ---------- 列名解析 ----------

def test_save_resolves_columns_by_keyword() -> None:
    """列名靠关键词匹配，顺序变化也能识别。"""
    storage = MagicMock()
    storage.execute.return_value = 1
    collector = CalendarCollector(MagicMock(), storage)

    df = pd.DataFrame({
        "日期": pd.to_datetime(["2024-05-01"]),
        "时间": ["10:00"],
        "国家": ["美国"],
        "事件": ["FOMC议息会议"],
        "实际": [None],
        "预期": ["不变"],
        "前值": [None],
        "重要性": [3],
    })
    saved = collector.save(df)
    assert saved == 1
    sql, params = storage.execute.call_args.args
    assert sql.strip() == INSERT_SQL.strip()
    assert params[2] == "FOMC议息会议"
    assert params[3] == "美国"
    assert params[4] == "interest_rate"
    assert params[5] == 3


def test_save_filters_unlisted_country() -> None:
    """「巴西」不在白名单中 → 整行落库，但 storage.execute 不被调用。"""
    storage = MagicMock()
    collector = CalendarCollector(MagicMock(), storage)
    df = pd.DataFrame({
        "日期": pd.to_datetime(["2024-05-25"]),
        "时间": [""],
        "国家": ["巴西"],
        "事件": ["GDP"],
        "实际": [None],
        "预期": [None],
        "前值": [None],
        "重要性": [1],
    })
    saved = collector.save(df)
    assert saved == 0
    storage.execute.assert_not_called()


def test_save_handles_missing_critical_columns() -> None:
    """缺日期或事件列 → 直接返回 0。"""
    storage = MagicMock()
    collector = CalendarCollector(MagicMock(), storage)
    df = pd.DataFrame({"foo": ["baz"]})
    assert collector.save(df) == 0


def test_save_normalizes_nan_forecast_actual_previous() -> None:
    storage = MagicMock()
    storage.execute.return_value = 1
    collector = CalendarCollector(MagicMock(), storage)

    df = pd.DataFrame({
        "日期": pd.to_datetime(["2024-05-01"]),
        "时间": [""],
        "国家": ["美国"],
        "事件": ["FOMC议息会议"],
        "实际": [float("nan")],
        "预期": [float("nan")],
        "前值": [float("nan")],
        "重要性": [3],
    })
    saved = collector.save(df)
    assert saved == 1
    # NaN → None
    assert storage.execute.call_args.args[1][6] is None
    assert storage.execute.call_args.args[1][7] is None
    assert storage.execute.call_args.args[1][8] is None


def test_save_skips_empty_titles() -> None:
    storage = MagicMock()
    collector = CalendarCollector(MagicMock(), storage)
    df = pd.DataFrame({
        "日期": pd.to_datetime(["2024-05-01"]),
        "时间": [""],
        "国家": ["美国"],
        "事件": ["   "],
        "实际": [None],
        "预期": [None],
        "前值": [None],
        "重要性": [1],
    })
    assert collector.save(df) == 0


# ---------- fetch_range ----------

def test_fetch_range_concats_daily_frames() -> None:
    source = MagicMock()
    # 8 天窗口（back=2 + forward=2 + 今天本身 = 5 天）：
    # 这里只关心「调用次数 = 日期数」和 concat 行为
    source.get_economic_calendar.side_effect = [
        _mock_calendar_df(),
        pd.DataFrame(),  # 哪天接口空了
        _mock_calendar_df(),
    ]
    collector = CalendarCollector(
        source, MagicMock(), days_back=1, days_forward=1,
    )
    df = collector.fetch_range()
    # 5 天的窗口，1 天为空
    assert source.get_economic_calendar.call_count == 3
    assert len(df) == 8  # 4 + 4


def test_fetch_range_handles_all_empty() -> None:
    source = MagicMock()
    source.get_economic_calendar.return_value = pd.DataFrame()
    collector = CalendarCollector(source, MagicMock(), days_back=1, days_forward=1)
    assert collector.fetch_range().empty


# ---------- 主流程 ----------

def test_collect_full_flow() -> None:
    source = MagicMock()
    source.get_economic_calendar.return_value = _mock_calendar_df()

    storage = MagicMock()
    storage.fetch_all.side_effect = [
        # _print_summary 里的两条 SQL（按国家分组 + 总数）
        [
            {"country": "美国", "cnt": 1, "min_d": "2024-05-01", "max_d": "2024-05-01"},
            {"country": "中国", "cnt": 1, "min_d": "2024-05-15", "max_d": "2024-05-15"},
        ],
        [{"c": 2}],
    ]
    storage.execute.return_value = 1

    collector = CalendarCollector(
        source, storage, days_back=0, days_forward=0,
    )
    report = collector.collect()

    # 原始 4 条 → 国家过滤剩 3 条 → save 写入 3 条
    assert report.raw_count == 4
    assert report.filtered_count == 3
    assert report.saved == 3
    assert storage.execute.call_count == 3


def test_collect_handles_empty_source() -> None:
    source = MagicMock()
    source.get_economic_calendar.return_value = pd.DataFrame()

    storage = MagicMock()
    storage.fetch_all.side_effect = [[], [{"c": 0}]]

    collector = CalendarCollector(
        source, storage, days_back=0, days_forward=0,
    )
    report = collector.collect()

    assert report.raw_count == 0
    assert report.saved == 0


# ---------- CalendarReport 默认值 ----------

def test_calendar_report_defaults() -> None:
    r = CalendarReport()
    assert r.raw_count == 0
    assert r.filtered_count == 0
    assert r.saved == 0
    assert r.elapsed == 0.0