"""分数阈值过滤器。

按 ``industry_score`` 阈值筛掉不达标的股票，按分数降序排序。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class FilterResult:
    """过滤器输出摘要。"""

    passed: int
    total: int
    min_score: int


class ScoreThresholdFilter:
    """``industry_score >= min_score`` 的简单过滤器。"""

    def __init__(self, min_score: int) -> None:
        if min_score < 0:
            raise ValueError(f"min_score 必须 >= 0，得到 {min_score}")
        self._min_score = min_score

    @property
    def min_score(self) -> int:
        return self._min_score

    def apply(self, df: pd.DataFrame) -> tuple[pd.DataFrame, FilterResult]:
        """过滤 + 排序。

        返回 ``(filtered_df, FilterResult)``：
        - ``filtered_df`` 是按 industry_score 降序的子集；
        - ``FilterResult`` 包含 ``passed`` / ``total`` / ``min_score``。
        """
        total = len(df)
        if df.empty or "industry_score" not in df.columns:
            empty = df.iloc[:0].copy()
            return empty, FilterResult(passed=0, total=total, min_score=self._min_score)

        mask = (
            df["industry_score"].notna()
            & (df["industry_score"] >= self._min_score)
        )
        passed_df = df[mask].copy()
        passed_df = passed_df.sort_values(
            "industry_score", ascending=False,
        ).reset_index(drop=True)

        return passed_df, FilterResult(
            passed=len(passed_df),
            total=total,
            min_score=self._min_score,
        )