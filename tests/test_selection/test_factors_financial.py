"""``FinancialFactorComputer`` 单元测试。

MySQL 通过 ``unittest.mock`` 替换，无需真实环境。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from selection.factors.financial import (
    FactorPoolSummary,
    FinancialFactorComputer,
)


def _mock_latest_rows() -> list[dict]:
    """3 只股票最新一期，混合有效/缺失字段。"""
    return [
        {
            "stock_code": "000001.SZ",
            "end_date": "2025-03-31",
            "roe": 12.0,
            "grossprofit_margin": None,
            "debt_to_assets": 90.0,
            "operating_cashflow": 100.0,
            "revenue": 1000.0,
            "net_profit": 200.0,
        },
        {
            "stock_code": "600519.SH",
            "end_date": "2025-03-31",
            "roe": 30.0,
            "grossprofit_margin": 90.0,
            "debt_to_assets": 20.0,
            "operating_cashflow": 500.0,
            "revenue": 2000.0,
            "net_profit": 800.0,
        },
        {
            "stock_code": "000002.SZ",
            "end_date": "2024-12-31",
            "roe": None,
            "grossprofit_margin": 25.0,
            "debt_to_assets": 80.0,
            "operating_cashflow": 50.0,
            "revenue": 0.0,  # 除零应返回 None
            "net_profit": 100.0,
        },
    ]


def _mock_meta_rows() -> list[dict]:
    """``trade_stock_meta`` 模拟：含全部 3 只股票。"""
    return [
        {"stock_code": "000001.SZ", "stock_name": "平安银行", "industry": "SW1银行"},
        {"stock_code": "600519.SH", "stock_name": "贵州茅台", "industry": "SW1食品饮料"},
        {"stock_code": "000002.SZ", "stock_name": "万科A", "industry": "SW1房地产"},
    ]


def _mock_annual_rows() -> list[dict]:
    """年报历史：000001 有 2024/2023 两年；600519 有 2024/2023；000002 仅 1 年。"""
    return [
        # 000001.SZ — 两年
        {"stock_code": "000001.SZ", "report_date": "2024-12-31", "net_profit": 200.0},
        {"stock_code": "000001.SZ", "report_date": "2023-12-31", "net_profit": 100.0},
        # 600519.SH — 两年
        {"stock_code": "600519.SH", "report_date": "2024-12-31", "net_profit": 800.0},
        {"stock_code": "600519.SH", "report_date": "2023-12-31", "net_profit": 600.0},
        # 000002.SZ — 仅 1 年（不足以算同比）
        {"stock_code": "000002.SZ", "report_date": "2023-12-31", "net_profit": 100.0},
    ]


def _mock_storage_with_meta(meta_rows: list[dict] | None) -> MagicMock:
    """构造一个能按顺序返回 3 次查询的 MagicMock。

    调用顺序：_fetch_latest -> _fetch_annual_history -> _fetch_meta。
    优化后：年报历史只查 1 次（之前是 N+1），按 stock_code 建内存索引。
    """
    storage = MagicMock()
    side_effect = [
        _mock_latest_rows(),  # _fetch_latest
        _mock_annual_rows(),  # _fetch_annual_history (一次性)
        meta_rows if meta_rows is not None else [],  # _fetch_meta
    ]
    storage.fetch_all.side_effect = side_effect
    return storage


# ---------- build_pool ----------

def test_build_pool_returns_one_row_per_stock() -> None:
    computer = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows()))
    df = computer.build_pool()
    assert len(df) == 3
    assert set(df.columns) >= {
        "stock_code", "stock_name", "industry",
        "end_date", "roe", "netprofit_yoy",
        "grossprofit_margin", "debt_to_assets", "ocf_to_revenue",
    }


def test_build_pool_maps_db_columns_correctly() -> None:
    df = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows())).build_pool()
    # 600519.SH: roe=30 → roe=30; gross_margin=90 → grossprofit_margin=90
    maotai = df[df["stock_code"] == "600519.SH"].iloc[0]
    assert maotai["roe"] == pytest.approx(30.0)
    assert maotai["grossprofit_margin"] == pytest.approx(90.0)
    assert maotai["debt_to_assets"] == pytest.approx(20.0)


def test_build_pool_fills_stock_name_and_industry_from_meta() -> None:
    df = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows())).build_pool()
    maotai = df[df["stock_code"] == "600519.SH"].iloc[0]
    assert maotai["stock_name"] == "贵州茅台"
    assert maotai["industry"] == "SW1食品饮料"
    pingan = df[df["stock_code"] == "000001.SZ"].iloc[0]
    assert pingan["stock_name"] == "平安银行"
    assert pingan["industry"] == "SW1银行"


def test_build_pool_handles_stock_not_in_meta() -> None:
    """meta 不含某只股票 → stock_name/industry 留空字符串。"""
    partial_meta = [
        {"stock_code": "600519.SH", "stock_name": "贵州茅台", "industry": "SW1食品饮料"},
        # 000001 / 000002 缺失
    ]
    df = FinancialFactorComputer(_mock_storage_with_meta(partial_meta)).build_pool()
    pingan = df[df["stock_code"] == "000001.SZ"].iloc[0]
    assert pingan["stock_name"] == ""
    assert pingan["industry"] == ""
    vanke = df[df["stock_code"] == "000002.SZ"].iloc[0]
    assert vanke["stock_name"] == ""
    assert vanke["industry"] == ""


def test_build_pool_handles_empty_meta_table() -> None:
    """``trade_stock_meta`` 为空 → 仍能 build_pool，所有 stock_name/industry 留空。"""
    df = FinancialFactorComputer(_mock_storage_with_meta([])).build_pool()
    assert len(df) == 3
    for code in ("000001.SZ", "600519.SH", "000002.SZ"):
        row = df[df["stock_code"] == code].iloc[0]
        assert row["stock_name"] == ""
        assert row["industry"] == ""


def test_ocf_to_revenue_computed_on_the_fly() -> None:
    df = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows())).build_pool()
    maotai = df[df["stock_code"] == "600519.SH"].iloc[0]
    # 500/2000 * 100 = 25
    assert maotai["ocf_to_revenue"] == pytest.approx(25.0)


def test_ocf_to_revenue_returns_none_on_zero_revenue() -> None:
    df = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows())).build_pool()
    vanke = df[df["stock_code"] == "000002.SZ"].iloc[0]
    assert pd.isna(vanke["ocf_to_revenue"]) or vanke["ocf_to_revenue"] is None


def test_netprofit_yoy_uses_last_two_annual_reports() -> None:
    df = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows())).build_pool()
    # 000001: (200 - 100) / 100 * 100 = 100%
    pingan = df[df["stock_code"] == "000001.SZ"].iloc[0]
    assert pingan["netprofit_yoy"] == pytest.approx(100.0)
    # 600519: (800 - 600) / 600 * 100 ≈ 33.33%
    maotai = df[df["stock_code"] == "600519.SH"].iloc[0]
    assert maotai["netprofit_yoy"] == pytest.approx(33.33, abs=0.01)


def test_netprofit_yoy_returns_none_for_only_one_year() -> None:
    df = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows())).build_pool()
    vanke = df[df["stock_code"] == "000002.SZ"].iloc[0]
    assert vanke["netprofit_yoy"] is None or pd.isna(vanke["netprofit_yoy"])


def test_build_pool_returns_empty_when_no_data() -> None:
    storage = MagicMock()
    storage.fetch_all.return_value = []
    df = FinancialFactorComputer(storage).build_pool()
    assert df.empty
    # 列结构应仍然存在
    assert "stock_code" in df.columns
    assert "industry_score" not in df.columns


def test_summary_counts_non_null_fields() -> None:
    computer = FinancialFactorComputer(_mock_storage_with_meta(_mock_meta_rows()))
    df = computer.build_pool()
    s = computer.summarize(df)
    assert s.n_stocks == 3
    # 000002.roe = None → 应被剔除
    assert s.n_with_roe == 2
    # 000002 只有 1 年报 → n_with_yoy == 2
    assert s.n_with_yoy == 2


# ---------- 性能：N+1 查询防护 ----------

def test_build_pool_calls_db_only_three_times() -> None:
    """回归保护：build_pool 必须只调用 3 次 DB（latest + annual + meta）。

    旧实现每只股票一次 _compute_netprofit_yoy → N+1，
    5000 只股票 = 5002 次往返，慢得不可接受。
    """
    storage = _mock_storage_with_meta(_mock_meta_rows())
    FinancialFactorComputer(storage).build_pool()
    # _fetch_latest + _fetch_annual_history + _fetch_meta = 3
    assert storage.fetch_all.call_count == 3


def test_verbose_false_silences_progress_logs(capsys) -> None:
    """``verbose=False`` 时不打印内部进度（用于程序化调用）。"""
    storage = _mock_storage_with_meta(_mock_meta_rows())
    FinancialFactorComputer(storage, verbose=False).build_pool()
    captured = capsys.readouterr()
    assert "[1/5]" not in captured.out
    assert "build_pool" not in captured.out


def test_verbose_true_emits_progress_logs(capsys) -> None:
    """``verbose=True`` 时打印每个步骤的进度与耗时。"""
    storage = _mock_storage_with_meta(_mock_meta_rows())
    FinancialFactorComputer(storage, verbose=True).build_pool()
    captured = capsys.readouterr()
    assert "[1/5]" in captured.out
    assert "[5/5]" in captured.out
    assert "总耗时" in captured.out
