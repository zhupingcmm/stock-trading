"""打分排序层。

- :class:`~selection.ranking.industry_score.IndustryScoreRanker`：
  按行业排名百分比换算为 1~5 分，并汇总为 ``industry_score``。
"""
from selection.ranking.industry_score import (
    IndustryScoreRanker,
    IndustryScoreResult,
    pct_to_score,
)

__all__ = ["IndustryScoreRanker", "IndustryScoreResult", "pct_to_score"]