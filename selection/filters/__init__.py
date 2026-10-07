"""过滤层：基于打分 / 阈值 / 业务规则筛除股票。

- :class:`~selection.filters.score_threshold.ScoreThresholdFilter`：
  ``industry_score >= min_score`` 的简单阈值过滤。
"""
from selection.filters.score_threshold import FilterResult, ScoreThresholdFilter

__all__ = ["FilterResult", "ScoreThresholdFilter"]