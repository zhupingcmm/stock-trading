"""数据源适配层。

不同数据源（akshare / tushare / wind / xtquant / llm 等）的统一抽象，
上层 ``collectors`` 只面向接口编程，不感知具体实现。
"""
from data_collection.sources.akshare import AkshareDataSource
from data_collection.sources.llm import QwenClient
from data_collection.sources.xtquant import XtQuantDataSource

__all__ = ["AkshareDataSource", "QwenClient", "XtQuantDataSource"]