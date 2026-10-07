"""``data_collection.utils.sentiment`` 的单元测试。"""
from __future__ import annotations

from data_collection.utils.sentiment import (
    IMPORTANT_WORDS,
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    analyze_sentiment,
    check_important,
)


class TestAnalyzeSentiment:
    def test_positive_words(self):
        for word in ["涨停", "大涨", "利好", "增长", "突破", "新高", "预增", "增持"]:
            assert analyze_sentiment(f"公司{word}了") == "positive"

    def test_negative_words(self):
        for word in ["跌停", "大跌", "利空", "下降", "跌破", "新低", "预减", "减持"]:
            assert analyze_sentiment(f"公司{word}了") == "negative"

    def test_neutral_no_keywords(self):
        assert analyze_sentiment("日常公告") == "neutral"

    def test_positive_takes_priority_over_negative(self):
        # 标题同时含 POSITIVE 与 NEGATIVE → 优先 POSITIVE
        assert analyze_sentiment("大跌后涨停") == "positive"

    def test_empty_title(self):
        assert analyze_sentiment("") == "neutral"


class TestCheckImportant:
    def test_important_words(self):
        for word in ["资产重组", "业绩预增", "重大合同", "收购", "并购", "停牌", "复牌"]:
            assert check_important(f"公司{word}公告") is True

    def test_non_important(self):
        assert check_important("公司发布日常公告") is False

    def test_empty_title(self):
        assert check_important("") is False


def test_keyword_lists_non_empty() -> None:
    """保证三个词列表非空。"""
    assert len(POSITIVE_WORDS) > 0
    assert len(NEGATIVE_WORDS) > 0
    assert len(IMPORTANT_WORDS) > 0