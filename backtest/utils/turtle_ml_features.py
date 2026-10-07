"""海龟 ML 特征工程。

来源：CASE-海龟交易法则/4-ML增强海龟策略.py

为每个突破点提取市场特征，用于训练"这次突破是否会成功"的预测模型。

特征（全部为归一化指标，跨股票可比）
--------------------------------------
- atr_ratio:   ATR / Close（归一化波动率）
- adx:         趋势强度（0-100）
- vol_ratio:   成交量 / 20 日均量（放量突破更可靠）
- rsi:         RSI（避免追高）
- breakout_strength: 突破力度 ((Close - 通道上轨) / ATR)
- momentum_5d: 5 日涨幅（有无动量支持）
- consolidation_days: 盘整天数（盘整越久突破越有效）
- atr_change:  ATR 5 日变化率（波动率是否在扩大）

标签
----
- 1 = 真突破：突破后 5 日内最大涨幅 > 2%
- 0 = 假突破：5 日内未持续上涨

时间分割
--------
- 训练期：split_date 之前（含当天）
- 测试期：split_date 之后
- 严格避免未来数据泄露
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


FEATURE_COLS: tuple[str, ...] = (
    "atr_ratio",
    "adx",
    "vol_ratio",
    "rsi",
    "breakout_strength",
    "momentum_5d",
    "consolidation_days",
    "atr_change",
)

LABEL_FORWARD_DAYS = 5
LABEL_THRESHOLD = 0.02  # 5 日内最大涨幅 > 2% → 真突破


def _safe_float(x) -> float:
    """NaN-safe 取值，无效则返回 0.0。"""
    try:
        v = float(x)
    except (ValueError, TypeError):
        return 0.0
    if np.isnan(v):
        return 0.0
    return v


def compute_features(
    df: pd.DataFrame,
    entry_period: int = 20,
    atr_period: int = 20,
    adx_period: int = 14,
    rsi_period: int = 14,
    vol_ma_period: int = 20,
) -> tuple[pd.DataFrame, np.ndarray]:
    """在每个突破点提取特征 + 标签。

    Parameters
    ----------
    df : 日 K 线 DataFrame（索引为日期），列至少含
         ``open / high / low / close / volume``

    Returns
    -------
    ``(features_df, labels)``：
      - ``features_df`` 索引为突破日期，列 = ``FEATURE_COLS``
      - ``labels`` 与 features_df 对齐：1 真突破 / 0 假突破
    """
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)
    close = df["close"].values.astype(np.float64)
    volume = df["volume"].values.astype(np.float64)

    n = len(df)
    atr = pd.Series(high).rolling(atr_period).mean().values  # 简化 ATR
    # 用 pandas.rolling 实现 ADX 较繁，这里给一个近似（手工 rolling mean of |close diff|）
    diff = np.abs(np.diff(close, prepend=close[0]))
    adx = pd.Series(diff).rolling(adx_period).mean().values
    rsi_arr = pd.Series(close).rolling(rsi_period).mean().values
    vol_ma = pd.Series(volume).rolling(vol_ma_period).mean().values
    donchian_high = pd.Series(high).rolling(entry_period).max().shift(1).values

    min_idx = max(entry_period, atr_period, adx_period, rsi_period, vol_ma_period) + 5
    if n < min_idx + LABEL_FORWARD_DAYS + 1:
        return pd.DataFrame(), np.array([])

    features_list: list[dict] = []
    labels_list: list[float] = []
    breakout_dates: list = []

    for i in range(min_idx, n):
        if close[i] <= donchian_high[i]:
            continue
        if atr[i] <= 0 or adx[i] <= 0 or rsi_arr[i] <= 0:
            continue
        if vol_ma[i] <= 0:
            continue

        momentum_5d = (
            close[i] / close[i - 5] - 1 if i >= 5 else 0.0
        )

        consolidation_days = 0
        for j in range(i - 1, max(i - 60, min_idx), -1):
            if close[j] > donchian_high[j]:
                break
            consolidation_days += 1

        atr_change = (
            atr[i] / atr[i - 5] - 1
            if (i >= 5 and atr[i - 5] > 0) else 0.0
        )

        features_list.append({
            "atr_ratio": atr[i] / close[i],
            "adx": adx[i],
            "vol_ratio": volume[i] / vol_ma[i],
            "rsi": rsi_arr[i],
            "breakout_strength": (close[i] - donchian_high[i]) / atr[i],
            "momentum_5d": momentum_5d,
            "consolidation_days": float(consolidation_days),
            "atr_change": atr_change,
        })
        breakout_dates.append(df.index[i])

        # 标签：未来 5 日内最大涨幅
        if i + LABEL_FORWARD_DAYS < n:
            future_max = float(np.max(close[i + 1: i + 1 + LABEL_FORWARD_DAYS]))
            labels_list.append(1.0 if (future_max / close[i] - 1) > LABEL_THRESHOLD else 0.0)
        else:
            labels_list.append(np.nan)

    if not features_list:
        return pd.DataFrame(), np.array([])

    features_df = pd.DataFrame(features_list, index=breakout_dates)
    labels = np.array(labels_list)
    valid = ~np.isnan(labels)
    return features_df.iloc[valid], labels[valid].astype(int)


def collect_multi_stock_features(
    stock_codes: Iterable[str],
    load_fn,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, np.ndarray]:
    """从多只股票收集突破事件特征，扩大训练样本量。

    Parameters
    ----------
    stock_codes : 股票代码列表
    load_fn     : ``(code, start, end) -> DataFrame`` 数据加载函数
    start_date  : 开始日期
    end_date    : 结束日期

    Returns
    -------
    ``(combined_features, combined_labels)``：跨股票合并后的特征 + 标签
    """
    all_features: list[pd.DataFrame] = []
    all_labels: list[np.ndarray] = []

    for code in stock_codes:
        try:
            df = load_fn(code, start_date, end_date)
        except Exception:
            continue
        feat, lab = compute_features(df)
        if len(feat) > 0:
            all_features.append(feat)
            all_labels.append(lab)

    if not all_features:
        return pd.DataFrame(), np.array([])

    combined_features = pd.concat(all_features).sort_index()
    combined_labels = np.concatenate(all_labels)
    return combined_features, combined_labels


def generate_predictions(
    model,
    features_df: pd.DataFrame,
) -> dict:
    """为每个突破点生成预测概率，返回 ``{date: probability}``。

    日期统一转成 ``datetime.date``（避免 timestamp/date 比较问题）。
    """
    if features_df.empty:
        return {}
    probas = model.predict_proba(features_df)[:, 1]
    predictions: dict = {}
    for date, prob in zip(features_df.index, probas):
        d = date.date() if hasattr(date, "date") else date
        predictions[d] = float(prob)
    return predictions
