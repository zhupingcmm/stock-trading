"""新闻标题情绪与重要性判断。

基于关键词匹配的简易方案，后续可替换为更精细的 NLP 模型。
"""
from __future__ import annotations

from typing import Literal

# 优先级：先匹配 POSITIVE 再匹配 NEGATIVE，最后才落到 NEUTRAL。
POSITIVE_WORDS: list[str] = [
    "涨停", "大涨", "利好", "增长", "突破", "新高", "预增", "增持",
    "盈利", "超预期", "重大突破", "战略合作", "中标",
]

NEGATIVE_WORDS: list[str] = [
    "跌停", "大跌", "利空", "下降", "跌破", "新低", "预减", "减持",
    "亏损", "违规", "处罚", "退市", "暴雷", "爆仓",
]

IMPORTANT_WORDS: list[str] = [
    "资产重组", "业绩预增", "业绩预减", "高送转", "股权激励",
    "定向增发", "股东减持", "股东增持", "重大合同", "中标",
    "收购", "并购", "停牌", "复牌", "退市", "回购",
]

Sentiment = Literal["positive", "negative", "neutral"]


def analyze_sentiment(title: str) -> Sentiment:
    """根据标题包含的关键词判断情绪。

    POSITIVE > NEGATIVE > NEUTRAL；命中任意一个即返回。
    """
    if not title:
        return "neutral"
    for word in POSITIVE_WORDS:
        if word in title:
            return "positive"
    for word in NEGATIVE_WORDS:
        if word in title:
            return "negative"
    return "neutral"


def check_important(title: str) -> bool:
    """判断标题是否包含重要关键词。"""
    if not title:
        return False
    return any(word in title for word in IMPORTANT_WORDS)