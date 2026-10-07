"""采集器。

按数据类型组织，例如：
- DailyQuoteCollector（日线行情）
- FinancialStatementCollector（财务报表）
- AnnouncementCollector（公告）
"""
from data_collection.collectors.daily_quote import CollectReport, DailyQuoteCollector

__all__ = ["DailyQuoteCollector", "CollectReport"]