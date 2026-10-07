"""``ScoreThresholdFilter`` 单元测试。"""
from __future__ import annotations

import pandas as pd
import pytest

from selection.filters.score_threshold import (
    FilterResult,
    ScoreThresholdFilter,
)


def _scored_df() -> pd.DataFrame:
    return pd.DataFrame({
        "stock_code": ["A", "B", "C", "D", "E"],
        "industry_score": [25, 20, 18, 15, None],
    })


class TestScoreThresholdFilter:
    def test_apply_keeps_rows_above_threshold(self) -> None:
        flt = ScoreThresholdFilter(min_score=18)
        out, result = flt.apply(_scored_df())
        assert len(out) == 3  # A(25), B(20), C(18)
        assert result.passed == 3
        assert result.total == 5
        assert result.min_score == 18

    def test_apply_sorts_descending_by_score(self) -> None:
        flt = ScoreThresholdFilter(min_score=18)
        out, _ = flt.apply(_scored_df())
        # 排序后前 3 个应为 A=25, B=20, C=18
        assert out["stock_code"].tolist() == ["A", "B", "C"]

    def test_apply_drops_nan_scores(self) -> None:
        flt = ScoreThresholdFilter(min_score=1)
        out, result = flt.apply(_scored_df())
        # E 是 NaN，不应通过
        assert "E" not in out["stock_code"].tolist()
        assert result.passed == 4

    def test_apply_empty_input(self) -> None:
        flt = ScoreThresholdFilter(min_score=18)
        empty = pd.DataFrame(columns=["stock_code", "industry_score"])
        out, result = flt.apply(empty)
        assert out.empty
        assert result.passed == 0
        assert result.total == 0

    def test_apply_missing_industry_score_column(self) -> None:
        flt = ScoreThresholdFilter(min_score=18)
        df = pd.DataFrame({"stock_code": ["A", "B"]})
        out, result = flt.apply(df)
        assert out.empty
        assert result.passed == 0

    def test_min_score_property(self) -> None:
        assert ScoreThresholdFilter(20).min_score == 20

    def test_min_score_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError):
            ScoreThresholdFilter(-1)