"""``CatalystCollector`` 单元测试。

Qwen 与 MySQL 都通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, mock_open, patch

import pytest

from data_collection.collectors.catalyst import (
    INSERT_SQL,
    CatalystCollector,
    CatalystReport,
    _normalize_title,
    _parse_json_array,
)


# ---------- 工具函数 ----------

class TestParseJsonArray:
    def test_extracts_array_from_text(self):
        content = '前导文字 [{"date": "2024-01-01", "title": "X"}] 尾部'
        result = _parse_json_array(content)
        assert len(result) == 1
        assert result[0]["title"] == "X"

    def test_handles_nested_brackets(self):
        content = '[{"x": [{"y": 1}]}]'
        result = _parse_json_array(content)
        assert len(result) == 1
        assert result[0]["x"][0]["y"] == 1

    def test_returns_empty_when_no_brackets(self):
        assert _parse_json_array("no array here") == []

    def test_returns_empty_when_invalid_json(self):
        assert _parse_json_array("[not valid json]") == []

    def test_returns_empty_when_not_list(self):
        # json 解析出 dict 而非 list
        assert _parse_json_array('{"foo": 1}') == []


class TestNormalizeTitle:
    def test_strips_separators(self):
        assert _normalize_title("FOMC 议息会议") == "FOMC议息会议"
        # 「/」和两侧空格都被去掉 → 「CPI」+「/」去 +「PPI」 → CPIPPI
        assert _normalize_title("CPI / PPI 数据") == "CPIPPI数据"
        assert _normalize_title("美联储-议息会议") == "美联储议息会议"
        assert _normalize_title("非农就业（美国）") == "非农就业美国"
        assert _normalize_title("全国两会 — 开幕") == "全国两会开幕"

    def test_empty(self):
        assert _normalize_title("") == ""


# ---------- prompts.yaml 加载 ----------

def test_load_prompts_config_reads_yaml(tmp_path) -> None:
    yaml_path = tmp_path / "prompts.yaml"
    yaml_path.write_text(
        "calendar:\n  search_catalysts: 'A'\n  generate_prompts: 'B'\n",
        encoding="utf-8",
    )
    qwen = MagicMock()
    storage = MagicMock()
    collector = CatalystCollector(qwen, storage, prompts_path=yaml_path)
    cfg = collector.load_prompts_config()
    assert cfg["calendar"]["search_catalysts"] == "A"


# ---------- search_catalysts ----------

def test_search_catalysts_calls_qwen_with_dates() -> None:
    qwen = MagicMock()
    qwen.search.return_value = '[{"date": "2024-06-01", "title": "FOMC"}]'

    storage = MagicMock()
    cfg = {
        "calendar": {
            "search_catalysts": "搜索 {start_date} 到 {end_date}",
            "generate_prompts": "...",
        }
    }
    collector = CatalystCollector(qwen, storage, search_days=180)

    with patch.object(collector, "load_prompts_config", return_value=cfg):
        events = collector.search_catalysts()

    assert len(events) == 1
    assert events[0]["title"] == "FOMC"
    # prompt 中包含日期
    called_prompt = qwen.search.call_args.args[0]
    assert date.today().isoformat() in called_prompt
    assert qwen.search.call_args.kwargs == {"enable_search": True}


def test_search_catalysts_returns_empty_on_no_json() -> None:
    qwen = MagicMock()
    qwen.search.return_value = "LLM 输出未含 JSON"

    storage = MagicMock()
    collector = CatalystCollector(qwen, storage)
    cfg = {
        "calendar": {
            "search_catalysts": "{start_date} {end_date}",
            "generate_prompts": "...",
        }
    }
    with patch.object(collector, "load_prompts_config", return_value=cfg):
        assert collector.search_catalysts() == []


# ---------- generate_prompts ----------

def test_generate_prompts_batches_by_20() -> None:
    qwen = MagicMock()
    qwen.search.side_effect = [
        '[{"title": "E0", "prompt": "P0"}, {"title": "E1", "prompt": "P1"}]',
        '[{"title": "E20", "prompt": "P20"}]',
    ]

    storage = MagicMock()
    collector = CatalystCollector(qwen, storage, prompt_batch_size=20)

    events = [{"date": "2024-01-01", "title": f"E{i}", "country": "中国"} for i in range(21)]
    cfg = {"calendar": {"generate_prompts": "{events_json}"}}

    with patch.object(collector, "load_prompts_config", return_value=cfg):
        prompts = collector.generate_prompts(events)

    assert len(prompts) == 3  # 2 + 1
    assert prompts["E0"] == "P0"
    assert prompts["E1"] == "P1"
    assert prompts["E20"] == "P20"
    # 21 个事件 / 20 每批 = 2 次调用
    assert qwen.search.call_count == 2


# ---------- save_events ----------

def test_save_events_calls_executemany_rows() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    storage.execute.return_value = 1
    # 没有已有事件
    storage.fetch_all.return_value = []

    collector = CatalystCollector(qwen, storage)

    events = [
        {"date": "2024-06-15", "title": "FOMC议息会议", "country": "美国",
         "category": "interest_rate", "importance": 3},
    ]
    saved = collector.save_events(events, prompts_map={
        "FOMC议息会议": "提问 prompt...",
    })
    assert saved == 1
    sql, params = storage.execute.call_args.args
    assert sql.strip() == INSERT_SQL.strip()
    assert params[0] == "2024-06-15"
    assert params[2] == "FOMC议息会议"
    assert params[3] == "美国"
    assert params[4] == "interest_rate"
    assert params[5] == 3
    assert params[6] == "qwen_search"
    assert params[7] == "提问 prompt..."


def test_save_events_skips_invalid_date() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    collector = CatalystCollector(qwen, storage)
    events = [{"date": "not-a-date", "title": "X", "country": "中国"}]
    assert collector.save_events(events) == 0
    storage.execute.assert_not_called()


def test_save_events_skips_fuzzy_match_within_5_days() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    # 已有事件：归一化标题 = "FOMC议息会议"，日期 = 2024-06-15
    storage.fetch_all.return_value = [
        {"id": 1, "event_date": date(2024, 6, 15), "title": "FOMC 议息会议"},
    ]

    collector = CatalystCollector(qwen, storage)
    events = [
        {"date": "2024-06-18", "title": "FOMC议息会议", "country": "美国",
         "category": "interest_rate", "importance": 3},
    ]
    assert collector.save_events(events) == 0
    storage.execute.assert_not_called()


def test_save_events_keeps_match_outside_5_days() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    storage.execute.return_value = 1
    storage.fetch_all.return_value = [
        {"id": 1, "event_date": date(2024, 6, 15), "title": "FOMC 议息会议"},
    ]

    collector = CatalystCollector(qwen, storage)
    events = [
        # 相差 30 天 > 5 天，应保留
        {"date": "2024-07-15", "title": "FOMC议息会议", "country": "美国",
         "category": "interest_rate", "importance": 3},
    ]
    assert collector.save_events(events) == 1


def test_save_events_clamps_importance() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    storage.execute.return_value = 1
    storage.fetch_all.return_value = []

    collector = CatalystCollector(qwen, storage)

    cases = [
        (1, 2),   # 钳位下限
        (4, 3),   # 钳位上限
        ("bad", 2),  # 非数字 → 钳位下限
        (2, 2),   # 合法
        (3, 3),   # 合法
    ]
    for raw_imp, expected in cases:
        events = [{
            "date": "2024-06-15", "title": f"E-{raw_imp}",
            "country": "中国", "category": "policy", "importance": raw_imp,
        }]
        storage.reset_mock()
        storage.fetch_all.return_value = []
        collector.save_events(events)
        assert storage.execute.call_args.args[1][5] == expected


# ---------- backfill_prompts ----------

def test_backfill_prompts_updates_missing() -> None:
    qwen = MagicMock()
    qwen.search.return_value = '[{"title": "FOMC议息会议", "prompt": "新 prompt"}]'

    storage = MagicMock()
    storage.execute.return_value = 1
    # 第一次 fetch_all（backfill 查询）
    storage.fetch_all.side_effect = [
        [
            {"id": 42, "event_date": date(2024, 6, 15),
             "title": "FOMC议息会议", "country": "美国"},
        ],
    ]

    collector = CatalystCollector(qwen, storage)
    cfg = {"calendar": {"generate_prompts": "{events_json}"}}

    with patch.object(collector, "load_prompts_config", return_value=cfg):
        updated = collector.backfill_prompts()

    assert updated == 1
    # UPDATE 语句：UPDATE trade_calendar_event SET ai_prompt = %s WHERE id = %s
    last_call_args = storage.execute.call_args.args
    assert "UPDATE" in last_call_args[0]
    assert last_call_args[1] == ("新 prompt", 42)


def test_backfill_prompts_returns_zero_when_no_missing() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    storage.fetch_all.return_value = []  # 没有缺失 prompt 的事件

    collector = CatalystCollector(qwen, storage)
    assert collector.backfill_prompts() == 0


# ---------- run / run_backfill 调度 ----------

def test_run_orchestrates_full_flow() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    storage.execute.return_value = 1
    storage.fetch_all.side_effect = [
        # _load_existing（save_events 里的查询）
        [],
        # _print_summary（按重要性分组）
        [{"importance": 3, "cnt": 1}],
    ]

    cfg = {
        "calendar": {
            "search_catalysts": "{start_date}{end_date}",
            "generate_prompts": "{events_json}",
        }
    }

    events = [
        {"date": "2024-06-15", "title": "FOMC议息会议", "country": "美国",
         "category": "interest_rate", "importance": 3},
    ]
    prompts = {"FOMC议息会议": "提问 prompt..."}

    with patch.object(CatalystCollector, "load_prompts_config", return_value=cfg), \
         patch.object(CatalystCollector, "search_catalysts", return_value=events), \
         patch.object(CatalystCollector, "generate_prompts", return_value=prompts):
        collector = CatalystCollector(qwen, storage)
        report = collector.run()

    assert report.events_found == 1
    assert report.prompts_generated == 1
    assert report.saved == 1
    # INSERT + 至少 1 次
    assert storage.execute.call_count >= 1


def test_run_handles_missing_yaml() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    collector = CatalystCollector(qwen, storage, prompts_path="nonexistent.yaml")
    report = collector.run()
    assert report.events_found == 0


def test_run_backfill_delegates_to_backfill() -> None:
    qwen = MagicMock()
    storage = MagicMock()
    storage.fetch_all.return_value = []
    collector = CatalystCollector(qwen, storage)
    with patch.object(collector, "backfill_prompts", return_value=3) as mock_bf:
        result = collector.run_backfill()
    assert result == 3
    mock_bf.assert_called_once_with()


# ---------- CatalystReport 默认值 ----------

def test_catalyst_report_defaults() -> None:
    r = CatalystReport()
    assert r.events_found == 0
    assert r.prompts_generated == 0
    assert r.saved == 0
    assert r.elapsed == 0.0