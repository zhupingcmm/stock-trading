"""``IndustryScoreRanker`` 单元测试。"""
from __future__ import annotations

import pandas as pd
import pytest

from selection.ranking.industry_score import (
    IndustryScoreRanker,
    pct_to_score,
)


# ---------- pct_to_score ----------

class TestPctToScore:
    @pytest.mark.parametrize("x,expected", [
        (0.0, 1),
        (0.1, 1),
        (0.2, 2),
        (0.4, 3),
        (0.5, 3),
        (0.6, 4),
        (0.79, 4),
        (0.8, 5),
        (0.99, 5),
        (1.0, 5),
    ])
    def test_boundaries(self, x: float, expected: int) -> None:
        assert pct_to_score(x) == expected

    def test_handles_nan(self) -> None:
        assert pct_to_score(None) is None
        assert pct_to_score(float("nan")) is None

    def test_handles_invalid_string(self) -> None:
        assert pct_to_score("abc") is None


# ---------- add_percentiles ----------

def _two_industry_df() -> pd.DataFrame:
    """2 个行业 × 3 只股票，便于验证独立排名。"""
    return pd.DataFrame({
        "stock_code": ["A1", "A2", "A3", "B1", "B2", "B3"],
        "industry": ["bank", "bank", "bank", "tech", "tech", "tech"],
        "roe": [10.0, 20.0, 30.0, 5.0, 15.0, 25.0],
        "netprofit_yoy": [1.0, 2.0, 3.0, 0.5, 1.5, 2.5],
        "grossprofit_margin": [40.0, 50.0, 60.0, 20.0, 30.0, 40.0],
        "ocf_to_revenue": [8.0, 12.0, 16.0, 4.0, 8.0, 12.0],
        "debt_to_assets": [90.0, 50.0, 30.0, 80.0, 60.0, 40.0],
    })


class TestAddPercentiles:
    def test_groups_by_industry(self) -> None:
        ranker = IndustryScoreRanker()
        df = ranker.add_percentiles(_two_industry_df())
        # bank 行业 A1/A2/A3 的 roe pct: A1=1/3, A2=2/3, A3=3/3(=1.0)
        assert df.loc[df["stock_code"] == "A1", "roe_industry_pct"].iloc[0] == pytest.approx(1 / 3)
        assert df.loc[df["stock_code"] == "A3", "roe_industry_pct"].iloc[0] == pytest.approx(1.0)
        # tech 行业独立排名
        assert df.loc[df["stock_code"] == "B1", "roe_industry_pct"].iloc[0] == pytest.approx(1 / 3)
        assert df.loc[df["stock_code"] == "B3", "roe_industry_pct"].iloc[0] == pytest.approx(1.0)

    def test_flips_debt_to_assets(self) -> None:
        """debt 越低 → pct 越高（因为 higher_better=False）。"""
        ranker = IndustryScoreRanker()
        df = ranker.add_percentiles(_two_industry_df())
        # bank 行业 A3 的 debt=30（最低）→ pct 最高
        a3_debt_pct = df.loc[df["stock_code"] == "A3", "debt_to_assets_industry_pct"].iloc[0]
        a1_debt_pct = df.loc[df["stock_code"] == "A1", "debt_to_assets_industry_pct"].iloc[0]
        assert a3_debt_pct > a1_debt_pct

    def test_falls_back_to_market_rank_when_industry_empty(self) -> None:
        ranker = IndustryScoreRanker()
        df = _two_industry_df().copy()
        df["industry"] = ""  # 全空 → 降级
        out = ranker.add_percentiles(df)
        # 全市场排名 pct 反映绝对位置（tech/bank 共 6 只）
        # roe 值：[10, 20, 30, 5, 15, 25] → 排序后：A1(10) 在第 2 位（5 最小），pct=2/6
        a1_roe_pct = out.loc[out["stock_code"] == "A1", "roe_industry_pct"].iloc[0]
        assert a1_roe_pct == pytest.approx(2 / 6)
        # B1.roe=5 最小 → pct=1/6
        b1_roe_pct = out.loc[out["stock_code"] == "B1", "roe_industry_pct"].iloc[0]
        assert b1_roe_pct == pytest.approx(1 / 6)
        # A3.roe=30 最大 → pct=1.0
        a3_roe_pct = out.loc[out["stock_code"] == "A3", "roe_industry_pct"].iloc[0]
        assert a3_roe_pct == pytest.approx(1.0)

    def test_skips_stocks_without_industry_when_partial(self) -> None:
        """部分股票无 industry → 这些股票不参与打分（保持 NaN）。"""
        ranker = IndustryScoreRanker()
        df = _two_industry_df().copy()
        df.loc[df["stock_code"] == "A1", "industry"] = ""  # A1 无行业
        out = ranker.add_percentiles(df)
        # A1 的 roe_pct 应为 NaN
        a1_pct = out.loc[out["stock_code"] == "A1", "roe_industry_pct"].iloc[0]
        assert pd.isna(a1_pct)
        # A2/A3 仍在 bank 行业排名
        a3_pct = out.loc[out["stock_code"] == "A3", "roe_industry_pct"].iloc[0]
        assert a3_pct == pytest.approx(1.0)


# ---------- add_scores ----------

class TestAddScores:
    def test_sums_5_components(self) -> None:
        ranker = IndustryScoreRanker()
        df = ranker.add_percentiles(_two_industry_df())
        df = ranker.add_scores(df)
        assert "industry_score" in df.columns
        # 5 个 _score 列应被创建
        for col in [
            "roe_industry_score", "netprofit_yoy_industry_score",
            "grossprofit_margin_industry_score", "ocf_to_revenue_industry_score",
            "debt_to_assets_industry_score",
        ]:
            assert col in df.columns
        # industry_score 是 5 项之和，范围 5~25
        valid = df["industry_score"].dropna()
        assert valid.between(5, 25).all()

    def test_creates_na_column_when_no_pct_columns(self) -> None:
        ranker = IndustryScoreRanker()
        empty = pd.DataFrame({"stock_code": ["X"], "industry": ["bank"]})
        out = ranker.add_scores(empty)
        assert "industry_score" in out.columns
        # industry_score 是 NA（兜底）
        assert pd.isna(out["industry_score"].iloc[0])


# ---------- rank() 一站式 ----------

class TestRank:
    def test_returns_used_industry_true(self) -> None:
        ranker = IndustryScoreRanker()
        result = ranker.rank(_two_industry_df())
        assert result.used_industry is True
        assert result.n_with_industry == 6
        assert "industry_score" in result.df.columns

    def test_returns_used_industry_false_when_empty(self) -> None:
        ranker = IndustryScoreRanker()
        df = _two_industry_df().copy()
        df["industry"] = ""
        result = ranker.rank(df)
        assert result.used_industry is False
        assert result.n_with_industry == 0
        # 降级后仍能算出 industry_score
        assert "industry_score" in result.df.columns