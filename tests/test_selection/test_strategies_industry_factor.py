"""``IndustryFactorStrategy`` 单元测试。

所有依赖（XtQuantDataSource 已移除、MysqlStorage、matplotlib）都通过
``unittest.mock`` 替换，无需真实环境。测试默认 ``enable_viz=False``
以避开 matplotlib 副作用。

数据源约束：策略只读 MySQL，pool 的 ``stock_name/industry`` 由
``FinancialFactorComputer.build_pool()``（已 mock）回填。
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from selection.strategies.industry_factor import (
    IndustryFactorReport,
    IndustryFactorStrategy,
)


# ---------- 工具 fixture ----------

def _mock_pool() -> pd.DataFrame:
    """3 只股票：含 industry 用于触发行业内排名。

    注意：industry 字段由 ``FinancialFactorComputer.build_pool()`` 从
    ``trade_stock_meta`` 回填，这里模拟的就是回填后的最终 pool。
    """
    return pd.DataFrame({
        "stock_code": ["000001.SZ", "600519.SH", "000002.SZ"],
        "stock_name": ["平安银行", "贵州茅台", "万科A"],
        "industry": ["SW1银行", "SW1食品饮料", "SW1房地产"],
        "end_date": ["2025-03-31", "2025-03-31", "2024-12-31"],
        "roe": [10.0, 30.0, 15.0],
        "netprofit_yoy": [5.0, 25.0, 10.0],
        "grossprofit_margin": [40.0, 90.0, 25.0],
        "debt_to_assets": [90.0, 20.0, 80.0],
        "ocf_to_revenue": [8.0, 25.0, 12.0],
    })


def _make_strategy(tmp_path: Path, *, enable_viz: bool = False, min_score: int = 18):
    storage = MagicMock()
    strategy = IndustryFactorStrategy(
        storage,
        min_score=min_score,
        output_dir=tmp_path,
        enable_viz=enable_viz,
    )
    return strategy, storage


# ---------- 架构约束：构造函数不再接受 XtQuantDataSource ----------

def test_constructor_signature_has_no_xtquant() -> None:
    """选股策略只依赖 MySQL；构造器不应接受 ``XtQuantDataSource`` 参数。"""
    sig = inspect.signature(IndustryFactorStrategy)
    params = list(sig.parameters.keys())
    # 第一个非 self 参数应是 storage
    assert params[0] == "storage"
    # 不应出现 XtQuantDataSource 相关类型
    for p in params:
        assert "XtQuant" not in p, f"策略不应依赖 xtquant: {p}"


# ---------- run() 主流程 ----------

def test_run_full_flow_with_industry(tmp_path: Path) -> None:
    """端到端：pool 含 industry，3 只股票，应有股票达标。"""
    strategy, _storage = _make_strategy(tmp_path, min_score=18)

    with pytest.MonkeyPatch.context() as mp:
        # mock factor computer，避免真实拉数
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.build_pool",
            lambda self: _mock_pool(),
        )
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.summarize",
            lambda self, df: MagicMock(n_stocks=3, n_with_roe=3, n_with_yoy=3),
        )
        report = strategy.run()

    assert isinstance(report, IndustryFactorReport)
    assert report.pool_size == 3
    assert report.n_with_industry == 3
    assert report.used_industry is True
    assert report.passed >= 1
    assert Path(report.output_dir).exists()
    assert Path(report.output_csv).exists()


def test_run_writes_output_csv(tmp_path: Path) -> None:
    strategy, _storage = _make_strategy(tmp_path, min_score=10)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.build_pool",
            lambda self: _mock_pool(),
        )
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.summarize",
            lambda self, df: MagicMock(n_stocks=3, n_with_roe=3, n_with_yoy=3),
        )
        report = strategy.run()

    out_csv = Path(report.output_csv)
    assert out_csv.exists()
    # 写出的 CSV 应能读回
    df = pd.read_csv(out_csv, encoding="utf-8-sig")
    assert "stock_code" in df.columns
    assert "industry_score" in df.columns


def test_run_handles_industry_empty_in_pool(tmp_path: Path) -> None:
    """pool 中 industry 全为空 → 降级为全市场排名。"""
    strategy, _storage = _make_strategy(tmp_path, min_score=10)
    pool_no_industry = _mock_pool()
    pool_no_industry["industry"] = ""

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.build_pool",
            lambda self: pool_no_industry,
        )
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.summarize",
            lambda self, df: MagicMock(n_stocks=3, n_with_roe=3, n_with_yoy=3),
        )
        report = strategy.run()

    # 降级路径
    assert report.used_industry is False or report.n_with_industry == 0
    # pool 里的 industry 仍来自 _mock_pool（merge 不覆盖已有值），但 rank 应已处理
    assert report.output_csv != ""


def test_run_skips_viz_when_disabled(tmp_path: Path) -> None:
    strategy, _storage = _make_strategy(tmp_path, min_score=10, enable_viz=False)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.build_pool",
            lambda self: _mock_pool(),
        )
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.summarize",
            lambda self, df: MagicMock(n_stocks=3, n_with_roe=3, n_with_yoy=3),
        )
        strategy.run()

    viz_dir = Path(tmp_path) / "2025-01-01" / "industry_viz"
    # viz 关闭 → 目录不应创建
    assert not viz_dir.exists()


def test_run_with_empty_pool_returns_early(tmp_path: Path) -> None:
    strategy, _storage = _make_strategy(tmp_path, min_score=10)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.build_pool",
            lambda self: pd.DataFrame(),
        )
        mp.setattr(
            "selection.strategies.industry_factor.FinancialFactorComputer.summarize",
            lambda self, df: MagicMock(n_stocks=0, n_with_roe=0, n_with_yoy=0),
        )
        report = strategy.run()

    assert report.pool_size == 0
    assert report.passed == 0


# ---------- _save_visualization 单测 ----------

def test_save_visualization_skipped_when_no_industry(tmp_path: Path) -> None:
    strategy, _ = _make_strategy(tmp_path, enable_viz=True)
    df = pd.DataFrame({
        "stock_code": ["A"],
        "industry": [""],
        "roe": [10.0],
        "grossprofit_margin": [20.0],
        "debt_to_assets": [50.0],
    })
    # 不应抛错
    strategy._save_visualization(df, tmp_path / "viz")
    assert not (tmp_path / "viz").exists()


def test_save_visualization_skipped_when_industry_below_min_count(tmp_path: Path) -> None:
    """行业样本数 < 3 → 不画图。"""
    strategy, _ = _make_strategy(tmp_path, enable_viz=True)
    df = pd.DataFrame({
        "stock_code": ["A1", "A2"],
        "industry": ["bank", "bank"],
        "roe": [10.0, 20.0],
        "grossprofit_margin": [40.0, 50.0],
        "debt_to_assets": [90.0, 50.0],
    })
    viz_dir = tmp_path / "viz"
    strategy._save_visualization(df, viz_dir)
    # 行业样本不足 → 不应生成任何 PNG
    assert not viz_dir.exists() or list(viz_dir.glob("*.png")) == []


# ---------- __init__ 边界 ----------

def test_default_min_score_from_settings(tmp_path: Path) -> None:
    """不传 min_score 时使用 ``config.settings.INDUSTRY_FACTOR_SCORE_MIN``。"""
    strategy = IndustryFactorStrategy(MagicMock(), output_dir=tmp_path)
    assert strategy._min_score == 18
