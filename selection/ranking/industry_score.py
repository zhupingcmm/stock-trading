"""行业排名打分器。

把参考脚本 ``多因子选股-筛选2.py`` 中的 ``add_industry_percentile`` 与
``add_industry_score`` 整合为 ``IndustryScoreRanker``：

1. 每个指标按行业内排名换算为 0~1 的百分比（高更好；debt_to_assets 取 1-pct）。
2. 把 0~1 映射为 1~5 分（前 20% → 5 分，依此类推）。
3. 5 项分数求和得到 ``industry_score``，范围 5~25。

降级策略：当 ``industry`` 列全空时，按全市场排名计算（与原脚本语义一致）。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


# 指标列表：(列名, 高更好)
_METRICS: list[tuple[str, bool]] = [
    ("roe", True),
    ("netprofit_yoy", True),
    ("grossprofit_margin", True),
    ("ocf_to_revenue", True),
    ("debt_to_assets", False),
]

# _pct 列 → _score 列 后缀
_PCT_SUFFIX = "_industry_pct"
_SCORE_SUFFIX = "_industry_score"


@dataclass
class IndustryScoreResult:
    """``IndustryScoreRanker.rank()`` 的返回结果。"""

    df: pd.DataFrame
    used_industry: bool
    n_with_industry: int


def pct_to_score(x: float | None) -> int | None:
    """``0~1`` 排名百分比 → ``1~5`` 分数。

    公式 ``min(5, max(1, int(x * 5) + 1))``：
    - x ∈ [0.0, 0.2)  → 1 分
    - x ∈ [0.2, 0.4)  → 2 分
    - x ∈ [0.4, 0.6)  → 3 分
    - x ∈ [0.6, 0.8)  → 4 分
    - x ∈ [0.8, 1.0]  → 5 分（含 1.0）
    """
    if x is None or pd.isna(x):
        return None
    try:
        v = float(x)
    except (ValueError, TypeError):
        return None
    if v != v:  # NaN
        return None
    return min(5, max(1, int(v * 5) + 1))


class IndustryScoreRanker:
    """行业排名打分（贴参考脚本 ``add_industry_percentile`` + ``add_industry_score``）。"""

    METRICS = _METRICS
    PCT_SUFFIX = _PCT_SUFFIX
    SCORE_SUFFIX = _SCORE_SUFFIX

    def add_percentiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """为 ``_METRICS`` 中的 5 个指标计算 ``<col>_industry_pct``。

        - 当存在有效 industry 时按 industry 分组排名；
        - 否则降级为全市场排名（与原脚本语义一致）。
        """
        df = df.copy()

        has_industry_col = "industry" in df.columns
        valid_mask = None
        used_industry = False

        if has_industry_col:
            valid_mask = (
                df["industry"].notna()
                & (df["industry"].astype(str) != "")
            )
            used_industry = bool(valid_mask.any())

        if used_industry and valid_mask is not None:
            for col, higher_better in _METRICS:
                if col not in df.columns:
                    continue
                pct_col = f"{col}{_PCT_SUFFIX}"
                ranked = (
                    df.loc[valid_mask]
                    .groupby("industry")[col]
                    .rank(pct=True, method="average")
                )
                if not higher_better:
                    ranked = 1 - ranked
                df.loc[valid_mask, pct_col] = ranked
        else:
            for col, higher_better in _METRICS:
                if col not in df.columns:
                    continue
                pct_col = f"{col}{_PCT_SUFFIX}"
                ranked = df[col].rank(pct=True, method="average")
                if not higher_better:
                    ranked = 1 - ranked
                df[pct_col] = ranked

        return df

    def add_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """把 5 个 ``_industry_pct`` 列换算为 ``_industry_score`` 列并求和。"""
        df = df.copy()
        score_cols: list[str] = []
        for col, _ in _METRICS:
            pct_col = f"{col}{_PCT_SUFFIX}"
            if pct_col not in df.columns:
                continue
            score_col = pct_col.replace("_pct", "_score")
            df[score_col] = df[pct_col].apply(pct_to_score)
            score_cols.append(score_col)

        if score_cols:
            df["industry_score"] = df[score_cols].sum(axis=1, min_count=1)
        else:
            # 兜底：保证下游不 KeyError
            df["industry_score"] = pd.NA

        return df

    def rank(self, df: pd.DataFrame) -> IndustryScoreResult:
        """一站式：percentile + score，返回带 ``used_industry`` 标记的结果。"""
        has_industry_col = "industry" in df.columns
        n_with_industry = 0
        if has_industry_col:
            n_with_industry = int(
                (df["industry"].notna() & (df["industry"].astype(str) != "")).sum()
            )

        with_pct = self.add_percentiles(df)
        with_score = self.add_scores(with_pct)
        return IndustryScoreResult(
            df=with_score,
            used_industry=n_with_industry > 0,
            n_with_industry=n_with_industry,
        )