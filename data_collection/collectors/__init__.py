"""采集器。

按数据类型组织，例如：
- DailyQuoteCollector（日线行情）
- FinancialCollector（财务报表）
- MacroCollector（宏观经济指标）
- NewsCollector（个股新闻）
- ReportCollector（研报数据）
- CalendarCollector（财经日历）
- CatalystCollector（关键催化剂事件）
- StockMetaCollector（股票名 + 行业）
"""
from data_collection.collectors.calendar import CalendarCollector, CalendarReport
from data_collection.collectors.catalyst import CatalystCollector, CatalystReport
from data_collection.collectors.daily_quote import CollectReport, DailyQuoteCollector
from data_collection.collectors.financial import FinancialCollector, FinancialReport
from data_collection.collectors.macro import (
    DailyRateReport,
    MacroCollector,
    MonthlyReport,
)
from data_collection.collectors.news import NewsCollector, NewsReport
from data_collection.collectors.report import ReportCollector, ReportReport
from data_collection.collectors.stock_meta import StockMetaCollector, StockMetaReport

__all__ = [
    "CalendarCollector",
    "CalendarReport",
    "CatalystCollector",
    "CatalystReport",
    "CollectReport",
    "DailyQuoteCollector",
    "DailyRateReport",
    "FinancialCollector",
    "FinancialReport",
    "MacroCollector",
    "MonthlyReport",
    "NewsCollector",
    "NewsReport",
    "ReportCollector",
    "ReportReport",
    "StockMetaCollector",
    "StockMetaReport",
]